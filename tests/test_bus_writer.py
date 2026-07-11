import json
import socket
from pathlib import Path

import msgpack
import pytest
import zmq
from PIL import Image

from eovrt_media.config.loader import load_run_config_data
from eovrt_media.contracts.events import DetectionEvent
from eovrt_media.models import create_adapter
from eovrt_media.runtime.pipeline import execute_run
from eovrt_media.service.bus_writer import BusPublishingArtifactWriter
from eovrt_media.transport.bus import (
    DETECTION_TOPIC_PREFIX,
    LIFECYCLE_TOPIC_PREFIX,
    BusPublisher,
)

REPO_ROOT = Path(__file__).resolve().parents[1]


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def _detection_event(unit_id: str) -> DetectionEvent:
    # OJO: en el media-plane `timing` es un campo REQUERIDO de DetectionEvent
    # (contracts/events.py:55, sin default), a diferencia del contrato del
    # control-plane donde tiene default_factory. Omitirlo es un ValidationError.
    return DetectionEvent.model_validate(
        {
            "run_id": "run-1",
            "unit_id": unit_id,
            "source": {
                "source_id": "cam-1",
                "source_type": "video",
                "frame_index": 0,
                "timestamp_ms": 0.0,
                "width": 640,
                "height": 480,
            },
            "model": {"name": "mock", "device": "cpu"},
            "prompts": {"prompt_set_id": "p1"},
            "detections": [],
            "timing": {},
        }
    )


class _RecordingWriter:
    """Sustituto del RunArtifactWriter: registra lo que se le persistio."""

    def __init__(self) -> None:
        self.detections: list[DetectionEvent] = []
        self.closed = False

    def write_detection(self, event: DetectionEvent) -> None:
        self.detections.append(event)

    def close(self) -> None:
        self.closed = True

    def write_summary(self, tracker) -> None:  # atributo delegado por __getattr__
        pass


@pytest.fixture()
def bus():
    endpoint = f"tcp://127.0.0.1:{_free_port()}"
    publisher = BusPublisher(endpoint)
    subscriber = zmq.Context.instance().socket(zmq.SUB)
    subscriber.setsockopt_string(zmq.SUBSCRIBE, DETECTION_TOPIC_PREFIX)
    subscriber.setsockopt_string(zmq.SUBSCRIBE, LIFECYCLE_TOPIC_PREFIX)
    subscriber.connect(endpoint)
    assert publisher.wait_for_subscriber(3000) is True
    yield publisher, subscriber
    subscriber.close(linger=0)
    publisher.close()


def test_payload_is_byte_identical_to_the_jsonl_line(bus) -> None:
    publisher, subscriber = bus
    inner = _RecordingWriter()
    writer = BusPublishingArtifactWriter(inner, publisher, "run-1")
    event = _detection_event("u1")

    writer.write_detection(event)

    _topic, raw = subscriber.recv_multipart()
    envelope = msgpack.unpackb(raw, raw=False)
    # Exactamente lo que JsonlSink.write_event escribe en detections.jsonl.
    assert envelope["payload"] == event.model_dump_json(exclude_none=True).encode("utf-8")
    assert envelope["topic"] == "media.detection.v1.run-1"
    assert envelope["key"] == "cam-1"
    # El JSONL sigue siendo la verdad: se persistio primero.
    assert inner.detections == [event]


def test_n_detections_produce_n_envelopes_then_run_finished(bus) -> None:
    publisher, subscriber = bus
    writer = BusPublishingArtifactWriter(_RecordingWriter(), publisher, "run-1")

    for index in range(5):
        writer.write_detection(_detection_event(f"u{index}"))
    writer.publish_run_finished("succeeded")

    topics = []
    envelopes = []
    for _ in range(6):
        topic, raw = subscriber.recv_multipart()
        topics.append(topic.decode())
        envelopes.append(msgpack.unpackb(raw, raw=False))

    assert topics[:5] == ["media.detection.v1.run-1"] * 5
    assert topics[5] == "run.lifecycle.v1.run-1"
    assert [envelope["seq"] for envelope in envelopes] == [0, 1, 2, 3, 4, 5]
    lifecycle = json.loads(envelopes[5]["payload"])
    assert lifecycle == {
        "schema_version": "run.lifecycle.v1",
        "event": "run_finished",
        "media_run_id": "run-1",
        "status": "succeeded",
    }


def test_writer_delegates_unknown_attributes_and_close(bus) -> None:
    publisher, _ = bus
    inner = _RecordingWriter()
    writer = BusPublishingArtifactWriter(inner, publisher, "run-1")

    writer.write_summary(tracker=None)
    writer.close()

    assert inner.closed is True


def test_bus_is_disabled_by_default() -> None:
    from eovrt_media.config.schemas import BusConfig

    assert BusConfig().enabled is False


def test_execute_run_survives_bus_publisher_bind_failure(tmp_path) -> None:
    """Hallazgo 1 (Critical): si BusPublisher.__init__ no puede bindear (puerto
    ya ocupado), la corrida debe degradar a "sin bus" y completarse igual — el
    JSONL es la verdad, el bus nunca rompe la corrida.

    Ocupamos el puerto con un socket TCP crudo antes de correr: mas
    deterministico que apuntar a un puerto privilegiado.
    """
    port = _free_port()
    occupied = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    occupied.bind(("127.0.0.1", port))
    occupied.listen(1)
    try:
        images = tmp_path / "imgs"
        images.mkdir(parents=True, exist_ok=True)
        for i in range(3):
            Image.new("RGB", (64, 48), (i * 10 % 255, 0, 0)).save(
                images / f"img_{i:03d}.png"
            )

        raw = {
            "run": {"id": "r_bus_bind_fail"},
            "source": {"type": "image_folder", "path": str(images)},
            "model": {"adapter": "mock"},
            "prompts": {
                "set_inline": {
                    "id": "t",
                    "classes": [{"id": "p", "phrasings": {"default": ["p"]}}],
                }
            },
            "outputs": {"run_dir": str(tmp_path / "runs"), "save_previews": False},
            "bus": {"enabled": True, "endpoint": f"tcp://127.0.0.1:{port}"},
        }
        config = load_run_config_data(raw, plane_root=REPO_ROOT / "configs")

        adapter = create_adapter(config.model)
        adapter.load()
        try:
            run_id = execute_run(config, adapter)
        finally:
            adapter.close()

        summary_path = tmp_path / "runs" / run_id / "summary.json"
        assert summary_path.exists()
        summary = json.loads(summary_path.read_text())
        assert summary["units_processed"] == 3
    finally:
        occupied.close()


def test_execute_run_publishes_envelopes_byte_identical_to_the_jsonl_lines(tmp_path) -> None:
    """Hallazgo 1 (Important): test end-to-end real, sin dobles.

    `test_payload_is_byte_identical_to_the_jsonl_line` (arriba) usa un
    `_RecordingWriter` y recomputa `event.model_dump_json(exclude_none=True)`
    para compararla consigo misma: es tautologico, nunca ejercita
    `JSONLSink.write_event`. Este test corre `execute_run` de punta a punta
    con `bus.enabled=True`, deja que el `JSONLSink` REAL escriba
    `detections.jsonl`, y compara sus lineas contra los `payload` de los
    envelopes REALMENTE publicados y recibidos por un SUB real. Si alguien
    toca una sola de las dos llamadas a `model_dump_json` (agrega
    `sort_keys`, cambia `exclude_none`, etc.) este test debe fallar.
    """
    images = tmp_path / "imgs"
    images.mkdir(parents=True, exist_ok=True)
    for i in range(5):
        Image.new("RGB", (64, 48), (i * 10 % 255, 0, 0)).save(images / f"img_{i:03d}.png")

    endpoint = f"tcp://127.0.0.1:{_free_port()}"
    run_id = "r_bus_jsonl_parity"

    raw = {
        "run": {"id": run_id},
        "source": {"type": "image_folder", "path": str(images)},
        "model": {"adapter": "mock"},
        "prompts": {
            "set_inline": {"id": "t", "classes": [{"id": "p", "phrasings": {"default": ["p"]}}]}
        },
        "outputs": {"run_dir": str(tmp_path / "runs"), "save_previews": False},
        # wait_for_subscriber_ms>0: bloquea el arranque hasta que el SUB de abajo
        # este realmente suscripto (regla spec 40 SS3.2), cerrando la ventana de
        # slow-joiner de PUB/SUB.
        "bus": {"enabled": True, "endpoint": endpoint, "wait_for_subscriber_ms": 3000},
    }
    config = load_run_config_data(raw, plane_root=REPO_ROOT / "configs")

    subscriber = zmq.Context.instance().socket(zmq.SUB)
    subscriber.setsockopt(zmq.RCVTIMEO, 5000)
    # Suscripto a los dos prefijos ANTES de arrancar la corrida (como un
    # consumidor real, ver Hallazgo 2).
    subscriber.setsockopt_string(zmq.SUBSCRIBE, DETECTION_TOPIC_PREFIX)
    subscriber.setsockopt_string(zmq.SUBSCRIBE, LIFECYCLE_TOPIC_PREFIX)
    subscriber.connect(endpoint)

    adapter = create_adapter(config.model)
    adapter.load()
    try:
        run_id = execute_run(config, adapter)
    finally:
        adapter.close()

    # Recolectar los envelopes de deteccion publicados, hasta el sentinela
    # run_finished (lifecycle) que cierra la corrida.
    envelopes = []
    try:
        while True:
            topic, raw_bytes = subscriber.recv_multipart()
            if topic.decode().startswith(LIFECYCLE_TOPIC_PREFIX):
                break
            envelopes.append(msgpack.unpackb(raw_bytes, raw=False))
    finally:
        subscriber.close(linger=0)

    detections_path = tmp_path / "runs" / run_id / "detections.jsonl"
    lines = detections_path.read_text().splitlines()

    assert len(lines) == 5
    assert len(envelopes) == len(lines)
    # Byte a byte, en el mismo orden: el payload del bus y la linea del JSONL
    # tienen que ser el mismo objeto.
    for envelope, line in zip(envelopes, lines):
        assert envelope["payload"] == line.encode("utf-8")


def test_getattr_on_missing_inner_raises_attributeerror_not_recursionerror(bus) -> None:
    """Hallazgo 2 (Minor): si _inner no llego a asignarse (p.ej. __init__ fallo
    antes), __getattr__ no debe recursar buscandose a si mismo."""
    publisher, _ = bus
    writer = BusPublishingArtifactWriter(_RecordingWriter(), publisher, "run-1")
    del writer.__dict__["_inner"]

    with pytest.raises(AttributeError):
        writer._inner
