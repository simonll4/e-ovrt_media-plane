"""Orquestación de los dos nodos para topología distribuida."""
from __future__ import annotations

import json
import logging
import queue
from pathlib import Path

from rich.console import Console

from eovrt_media.config import RunConfig
from eovrt_media.contracts.normalized_unit import PayloadFormat
from eovrt_media.metrics import LatencyTracker, get_gpu_memory_peak_mb, reset_gpu_peak_memory
from eovrt_media.models import create_adapter
from eovrt_media.postprocessing import DetectionNormalizer
from eovrt_media.runtime.pipeline import create_source, run_consumer_loop, run_producer_loop
from eovrt_media.runtime.run_context import RunContext
from eovrt_media.sinks import RunArtifactWriter
from eovrt_media.sinks.jsonl_sink import atomic_write_json
from eovrt_media.transport import RateGate, create_transport

logger = logging.getLogger(__name__)


def _wait_for_consumer_end(
    transport,
    *,
    heartbeat_timeout_ms: int,
    poll_interval_s: float | None = None,
) -> None:
    """Wait until Nodo B consumes END, as long as its heartbeat remains alive."""
    wait_timeout_s = (
        poll_interval_s if poll_interval_s is not None else heartbeat_timeout_ms / 1000.0
    )
    while True:
        if transport.wait_for_consumer(timeout_s=wait_timeout_s):
            return
        if transport.has_seen_peer() and transport.is_peer_alive():
            continue
        raise RuntimeError(
            "Nodo B no consumió END antes del timeout de heartbeat "
            f"({heartbeat_timeout_ms} ms)."
        )


def run_node_a(config: RunConfig, console: Console | None = None) -> None:
    """Nodo A: ingesta + rate control + normalización + servidor de red."""
    _ = console or Console()
    source = create_source(config)
    adapter = create_adapter(config.model)
    rate_control = config.rate_control
    transport = create_transport(
        backend="network",
        role="producer",
        policy=rate_control.policy,
        buffer_size=rate_control.buffer_size,
        max_staleness_ms=rate_control.max_staleness_ms,
        endpoint=config.transport.endpoint,
        heartbeat_endpoint=config.transport.heartbeat_endpoint,
        heartbeat_interval_ms=config.transport.heartbeat_interval_ms,
        heartbeat_timeout_ms=config.transport.heartbeat_timeout_ms,
        codec=config.transport.compression.codec,
        quality=config.transport.compression.quality,
    )
    errors_queue: queue.SimpleQueue = queue.SimpleQueue()
    timings: dict[str, float] = {"backpressure_wait_ms": 0.0}

    def consumer_is_available() -> bool:
        return not transport.has_seen_peer() or transport.is_peer_alive()

    try:
        run_producer_loop(
            source,
            RateGate(stride=rate_control.stride),
            adapter.input_spec,
            PayloadFormat(config.transport.payload_format),
            transport,
            # Nodo B crea el run_id canónico porque es dueño de artefactos y sinks.
            run_id="",
            errors_queue=errors_queue,
            timings=timings,
            should_continue=consumer_is_available,
        )
        _wait_for_consumer_end(
            transport,
            heartbeat_timeout_ms=config.transport.heartbeat_timeout_ms,
        )
    finally:
        transport.shutdown()


def _finalize_summary_status(summary_path: Path, *, status: str, error: str | None) -> None:
    """Read-modify-write del summary, mismo patrón que RunManager._finalize():
    write_summary() no conoce status/error (son del ciclo de vida, no del pipeline)."""
    try:
        summary = json.loads(summary_path.read_text())
    except (OSError, json.JSONDecodeError):
        summary = {}
    summary["status"] = status
    summary["error"] = error
    atomic_write_json(summary_path, summary)


def run_node_b(config: RunConfig, console: Console | None = None) -> str:
    """Nodo B: cliente de red + inferencia + postproceso + artefactos."""
    _ = console or Console()
    run_context = RunContext(config)
    artifact_writer = RunArtifactWriter(run_context)

    bus_publisher = None
    if config.bus.enabled:
        from eovrt_media.service.bus_writer import BusPublishingArtifactWriter
        from eovrt_media.transport.bus import BusPublisher

        # Spec 42 SS2: en two-node el publisher vive en el Nodo B; el Nodo A no
        # publica nada. El try/finally que envuelve el resto de esta funcion
        # garantiza la finalizacion con status explicito (run_finished sale pase
        # lo que pase, ver el finally al final de la funcion).
        try:
            bus_publisher = BusPublisher(
                config.bus.endpoint,
                hwm=config.bus.hwm,
                wait_for_subscriber_ms=config.bus.wait_for_subscriber_ms,
            )
            artifact_writer = BusPublishingArtifactWriter(
                artifact_writer, bus_publisher, run_context.run_id
            )
        except Exception:  # noqa: BLE001 — el bus nunca rompe la corrida
            logger.warning(
                "bus: no se pudo levantar el publicador (endpoint=%s); "
                "la corrida continua sin bus, el JSONL es la verdad",
                config.bus.endpoint,
                exc_info=True,
            )
            if bus_publisher is not None:
                bus_publisher.close()
            bus_publisher = None

    bus_status = "succeeded"
    try:
        tracker = LatencyTracker()
        artifact_writer.write_effective_config()
        artifact_writer.write_debug_event(node="B", stage="run", event="node.start")

        prompt_set_id = (
            config.prompts_file.resolved_set_id() if config.prompts_file else "unknown"
        )

        transport = create_transport(
            backend="network",
            role="consumer",
            endpoint=config.transport.endpoint,
            heartbeat_endpoint=config.transport.heartbeat_endpoint,
            heartbeat_interval_ms=config.transport.heartbeat_interval_ms,
            heartbeat_timeout_ms=config.transport.heartbeat_timeout_ms,
            request_timeout_ms=config.transport.request_timeout_ms,
        )
        artifact_writer.write_debug_event(node="B", stage="transport", event="transport.start")
        normalizer = DetectionNormalizer(
            min_confidence=config.postprocess.min_confidence,
            min_box_area_px=config.postprocess.min_box_area_px,
            normalize_boxes=config.postprocess.normalize_boxes,
        )
        adapter = create_adapter(config.model)
        plan = config.build_prompt_plan(adapter.PROMPT_BACKEND)
        reset_gpu_peak_memory()
        failure: Exception | None = None
        try:
            try:
                artifact_writer.write_debug_event(
                    node="B", stage="model", event="model.load_start"
                )
                adapter.load()
                artifact_writer.write_debug_event(node="B", stage="model", event="model.load_end")
                run_consumer_loop(
                    transport,
                    adapter,
                    normalizer,
                    artifact_writer,
                    run_context,
                    tracker,
                    config,
                    plan,
                    prompt_set_id,
                    timings={},
                    progress=None,
                    task=None,
                    drain_errors=False,
                )
            finally:
                transport.shutdown()
                adapter.close()
                artifact_writer.close()
        except Exception as exc:  # noqa: BLE001 — status failed captura la causa (como RunManager._execute)
            failure = exc

        run_context.gpu_memory_peak_mb = get_gpu_memory_peak_mb()
        run_context.finish()
        artifact_writer.write_summary(tracker)
        artifact_writer.write_provenance()
        artifact_writer.write_manifest()
        _finalize_summary_status(
            run_context.run_dir / "summary.json",
            status="failed" if failure is not None else "succeeded",
            error=str(failure) if failure is not None else None,
        )
        if failure is not None:
            bus_status = "failed"
            raise failure
        return run_context.run_id
    except BaseException:
        bus_status = "failed"
        raise
    finally:
        # El run_finished sale pase lo que pase (ADR-007): si el consumidor del
        # plano de control no lo recibe, queda colgado esperando para siempre.
        if bus_publisher is not None:
            try:
                artifact_writer.publish_run_finished(bus_status)
            except Exception:  # noqa: BLE001 — el bus nunca rompe la corrida
                logger.warning("bus: no se pudo publicar run_finished", exc_info=True)
            bus_publisher.close()
