"""Tests de HARDWARE contra la OAK-D real (spec §10, E2E).

Gateo: EOVRT_OAK_D_HW_URL=<ip> pytest tests/test_oak_d_hw_e2e.py -q -x
Sin la env var: SKIP (la suite normal y CI no se ven afectadas).
Con la env var pero cámara inalcanzable: FAIL inmediato en el fixture de
conexión (verificación PRIMERO; ningún test llega a colgarse esperando frames).
"""
from __future__ import annotations

import os
import time
from pathlib import Path

import pytest

from eovrt_media.config.schemas import OakDPrefilterConfig
from eovrt_media.sources.oak_d_source import OakDSource

OAK_URL = os.environ.get("EOVRT_OAK_D_HW_URL")
BLOB = Path(__file__).resolve().parents[1] / "models/edge/person-detection-retail-0013_6shave.blob"

pytestmark = pytest.mark.skipif(
    not OAK_URL, reason="test de hardware: exportar EOVRT_OAK_D_HW_URL=<ip de la OAK-D>"
)


@pytest.fixture(scope="module")
def camera_reachable():
    """Handshake una sola vez ANTES de todos los tests de hardware."""
    dai = pytest.importorskip("depthai", reason="pip install -e '.[edge]'")
    try:
        with dai.Device(dai.Pipeline(), dai.DeviceInfo(OAK_URL)) as dev:
            assert dev.getConnectedCameras(), "device sin cámaras conectadas"
    except Exception as exc:
        pytest.fail(
            f"OAK-D inalcanzable en {OAK_URL}: {exc} — "
            "correr `python scripts/check_oak_d.py` para diagnóstico."
        )
    return OAK_URL


def _collect(source: OakDSource, timeout_s: float = 30.0) -> list:
    """Consume la fuente con presupuesto de tiempo (nunca colgarse)."""
    units = []
    it = iter(source)
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        try:
            units.append(next(it))
        except StopIteration:
            break
        if source.max_units is not None and len(units) >= source.max_units:
            break
    source.stop()
    return units


def test_raw_stream_yields_frames_with_capture_latency(camera_reachable):
    source = OakDSource(url=camera_reachable, fps=10, max_units=5)
    units = _collect(source)
    assert len(units) == 5
    for u in units:
        assert u.pixel_data is not None and u.width > 0
        # Timesync PoE <0.5 ms; tolerar hasta 2 s por picos de red.
        assert u.capture_to_host_ms is not None
        assert 0.0 <= u.capture_to_host_ms < 2000.0


def test_isp_scale_reduces_transmitted_resolution(camera_reachable):
    source = OakDSource(url=camera_reachable, fps=10, isp_scale=(1, 2), max_units=1)
    units = _collect(source)
    assert len(units) == 1
    assert units[0].width == 960 and units[0].height == 540  # 1080p * 1/2


@pytest.mark.skipif(not BLOB.is_file(), reason="falta el blob: make download-prefilter-blob")
def test_prefilter_gate_streams_and_reports_stats(camera_reachable):
    """Agnóstico de escena: el heartbeat (2 s) garantiza flujo aunque no haya
    nadie; los contadores deben llegar y cerrar la aritmética del gate.

    NOTA: no se puede fijar `max_units=4` y asumir que el primer tick de
    stats (1 Hz, medido en el reloj del Script on-device) ya habrá llegado
    para entonces. Los primeros frames, ANTES de que la NN entregue su
    primer resultado, se reenvían sin gating ("warmup" fail-open) sin
    importar si hay alguien en escena — es una propiedad estructural del
    arranque, no un artefacto de escena. Se midió en hardware real (2026-07-15,
    OAK-D en 192.168.1.50): con 6 frames pedidos, los 6 llegaron en <0.5 s
    mientras el primer mensaje de stats tardó ~1.1 s en aparecer, dejando
    `prefilter_stats is None` si se corta apenas se alcanza `max_units`. Por
    eso acá se sigue consumiendo (con un piso generoso de frames) hasta que
    las stats realmente lleguen, en vez de asumir que 4 heartbeats siempre
    alcanzan.
    """
    source = OakDSource(
        url=camera_reachable, fps=10, max_units=40,
        prefilter=OakDPrefilterConfig(enabled=True, model_blob=str(BLOB)),
    )
    units = []
    it = iter(source)
    deadline = time.monotonic() + 40.0  # peor caso: varios heartbeats + margen
    while time.monotonic() < deadline:
        try:
            units.append(next(it))
        except StopIteration:
            break
        if len(units) >= 4 and source.prefilter_stats is not None:
            break
        if source.max_units is not None and len(units) >= source.max_units:
            break
    source.stop()
    assert len(units) >= 4, "el fail-open/heartbeat debe garantizar frames"
    assert source.prefilter_stats is not None, "stats del Script no llegaron"
    s = source.prefilter_stats
    assert s["seen"] == s["forwarded"] + s["dropped_no_person"]
    # No comparar contra len(units): "stats" es una foto periódica (1 Hz) del
    # estado on-device en el instante del tick, mientras que "rgb" es una cola
    # aparte que el host puede drenar más rápido. Medido en hardware real: con
    # 4+ frames ya recibidos por el host, el primer tick de stats reportó
    # forwarded=2 — la foto quedó atrás, no es un bug del gate. Solo se
    # verifica que el gate esté efectivamente forwardeando (>=1), no que su
    # contador esté sincronizado con lo que el host ya consumió.
    assert s["forwarded"] >= 1
    assert s["nn_results"] > 0, "la NN on-device no produjo resultados (¿blob?)"


@pytest.mark.skipif(not BLOB.is_file(), reason="falta el blob: make download-prefilter-blob")
def test_prefilter_empty_scene_rate_is_heartbeat_bound(camera_reachable):
    """Solo interpretable con la escena VACÍA (sin personas en el FOV): el gate
    debe dropear la mayoría de los frames "seen" y solo dejar pasar heartbeats.
    Si hay una persona en el encuadre el test se auto-SKIPea usando los
    contadores del gate.

    Discriminador: los contadores ON-DEVICE (`seen`/`forwarded`/
    `dropped_no_person`), NO el wall-clock. El `elapsed` de `_collect()`
    incluye el connect/XLink de `dai.Device` (~9 s por conexión, a veces con
    reintentos), que cae DENTRO de la región cronometrada. Eso ya alcanza para
    que `elapsed >= 3.0` valga por sí solo — con o sin gating real — así que
    una `elapsed`-based assertion es un gate roto que dejaría pasar un bug
    donde TODOS los frames se reenvían. Medido en hardware real
    (2026-07-15, 192.168.1.50): ~29 s para 3 frames pedidos con
    `max_units=3`, muy por encima de los ~6 s que predicen 3 heartbeats de
    2 s — la diferencia es overhead de conexión, no evidencia de gating.
    """
    source = OakDSource(
        url=camera_reachable, fps=10, max_units=40,
        prefilter=OakDPrefilterConfig(enabled=True, model_blob=str(BLOB),
                                       heartbeat_interval_ms=2000),
    )
    units = []
    it = iter(source)
    deadline = time.monotonic() + 45.0
    # Piso de "seen" para no quedarnos con la primera foto trivial de stats
    # (p.ej. seen=1, forwarded=1, dropped=0 durante el warm-up fail-open).
    SEEN_FLOOR = 15
    while time.monotonic() < deadline:
        try:
            units.append(next(it))
        except StopIteration:
            break
        stats = source.prefilter_stats
        if stats is not None and stats.get("seen", 0) >= SEEN_FLOOR:
            break
        if source.max_units is not None and len(units) >= source.max_units:
            break
    source.stop()
    stats = source.prefilter_stats or {}
    if stats.get("forwarded_by_reason", {}).get("person", 0) > 0:
        pytest.skip("hay una persona en el FOV: tasa no acotada por heartbeat")
    assert stats, "stats del Script no llegaron"
    assert stats["seen"] >= SEEN_FLOOR, (
        f"no se alcanzó el piso de frames vistos on-device ({stats})"
    )
    # El discriminador real: en escena vacía, el gate debe haber dropeado la
    # mayoría de los frames vistos y dejado pasar solo los heartbeats.
    assert stats["seen"] > stats["forwarded"], (
        f"el gate no dropeó nada — sospecha de gate roto ({stats})"
    )
    assert stats["dropped_no_person"] > 0, (
        f"el gate no reporta drops por ausencia de persona ({stats})"
    )
