import json
from pathlib import Path

import pytest
from PIL import Image

from eovrt_media.config.loader import load_run_config_data
from eovrt_media.metrics.g2a import G2AAccumulator
from eovrt_media.models import create_adapter
from eovrt_media.runtime.pipeline import execute_run

REPO_ROOT = Path(__file__).resolve().parents[1]
SET_INLINE = {"id": "t", "classes": [{"id": "p", "phrasings": {"default": ["p"]}}]}


def _make_images(folder: Path, n: int) -> None:
    folder.mkdir(parents=True, exist_ok=True)
    for i in range(n):
        Image.new("RGB", (64, 48), (i * 10 % 255, 0, 0)).save(folder / f"img_{i:03d}.png")


def test_percentiles_over_a_known_sample() -> None:
    acc = G2AAccumulator()
    for value in range(1, 101):  # 1..100 ms
        acc.add(float(value))

    summary = acc.summarize(warmup_units=0, applicability_state="computed", causes=[])

    assert summary.state == "computed"
    assert summary.count == 100
    assert summary.p50_ms == pytest.approx(50.5, abs=0.6)
    assert summary.p95_ms == pytest.approx(95.0, abs=1.0)
    assert summary.p99_ms == pytest.approx(99.0, abs=1.0)
    assert summary.avg_ms == pytest.approx(50.5, abs=0.1)


def test_warmup_units_are_excluded_from_the_percentiles() -> None:
    """El warm-up (primeras N unidades) distorsiona el P95: se declara y se excluye."""
    acc = G2AAccumulator()
    acc.add(10_000.0)  # carga de kernels CUDA en la primera unidad
    acc.add(10_000.0)
    for _ in range(50):
        acc.add(20.0)

    summary = acc.summarize(warmup_units=2, applicability_state="computed", causes=[])

    assert summary.warmup_units == 2
    assert summary.count == 50, "las unidades de warm-up no cuentan"
    assert summary.p95_ms == pytest.approx(20.0)
    assert summary.avg_ms == pytest.approx(20.0)


def test_budget_verdict_uses_p95() -> None:
    acc = G2AAccumulator()
    for _ in range(10):
        acc.add(100.0)
    assert acc.summarize(0, "computed", []).p95_within_budget is True

    slow = G2AAccumulator()
    for _ in range(10):
        slow.add(400.0)
    verdict = slow.summarize(0, "computed", [])
    assert verdict.p95_within_budget is False
    assert (verdict.budget_min_ms, verdict.budget_max_ms) == (50.0, 250.0)


def test_two_node_does_not_publish_meaningless_percentiles() -> None:
    """Los relojes monotonicos de dos hosts no son comparables: se declara, no se inventa."""
    acc = G2AAccumulator()
    for _ in range(10):
        acc.add(-5.0)  # basura tipica de restar relojes de hosts distintos

    summary = acc.summarize(
        warmup_units=0,
        applicability_state="not_interpretable",
        causes=["cross_node_monotonic_clock"],
    )

    assert summary.state == "not_interpretable"
    assert summary.causes == ["cross_node_monotonic_clock"]
    assert (summary.p50_ms, summary.p95_ms, summary.p99_ms, summary.avg_ms) == (0.0, 0.0, 0.0, 0.0)
    assert summary.count == 10  # se informa cuantas unidades hubo, sin interpretarlas
    assert summary.p95_within_budget is False


def test_no_units_is_not_a_silent_zero() -> None:
    summary = G2AAccumulator().summarize(0, "computed", [])

    assert summary.state == "applicable_not_computed"
    assert summary.causes == ["no_units_processed"]
    assert summary.count == 0


def test_warmup_larger_than_the_sample_is_not_computed() -> None:
    acc = G2AAccumulator()
    acc.add(20.0)

    summary = acc.summarize(warmup_units=5, applicability_state="computed", causes=[])

    assert summary.state == "applicable_not_computed"
    assert summary.causes == ["all_units_in_warmup"]
    assert summary.count == 0


def test_two_node_run_writes_null_g2a_rows_and_a_not_interpretable_summary(tmp_path) -> None:
    """Revision de codigo sobre Task 3: el summary declarando `not_interpretable`
    no alcanza si `metrics.jsonl` sigue trayendo un `g2a_ms` crudo — un
    consumidor aguas abajo (el plano de control, joineando por unit_id) lo
    leeria como un numero real cuando en realidad son relojes monotonicos de
    dos hosts distintos, no comparables (spec 40 SS4).

    Se ejercita el camino REAL: `execute_run()` en lugar de un stub, con un
    `config` cuyo `topology.mode` es "two_node". No se levantan dos nodos de
    verdad (`run_node_a`/`run_node_b`, sockets ZeroMQ) porque no hace falta:
    el loader (`_derive_defaults`) solo fuerza `transport.backend: network`
    cuando `topology.mode` ya es "two_node" AL MOMENTO DE CARGAR la config, y
    ese backend exige `transport.endpoint`/`heartbeat_endpoint` reales
    (`_validate_deployment`). Por eso se carga una config normal
    (single_host/memory, la unica combinacion valida sin red real) y se
    parchea el atributo `topology.mode` sobre el objeto YA VALIDADO, despues
    de `load_run_config_data` — igual que hace `tests/test_two_node.py` para
    sus propios fixtures. `run_consumer_loop` y `write_summary` leen
    `config.topology.mode` en tiempo de ejecucion (no en tiempo de carga), asi
    que este parche ejercita el codigo de produccion real de ambos.
    """
    images = tmp_path / "images"
    _make_images(images, 5)
    raw = {
        "run": {"id": "g2a-two-node"},
        "source": {"type": "image_folder", "path": str(images)},
        "model": {"adapter": "mock"},
        "prompts": {"set_inline": SET_INLINE},
        "outputs": {"run_dir": str(tmp_path / "runs"), "save_previews": False},
    }
    config = load_run_config_data(raw, plane_root=REPO_ROOT / "configs")
    config.topology.mode = "two_node"  # transporte sigue siendo memory: no hace falta red real

    adapter = create_adapter(config.model)
    adapter.load()
    try:
        run_id = execute_run(config, adapter)
    finally:
        adapter.close()

    metrics_path = tmp_path / "runs" / run_id / "metrics.jsonl"
    rows = [json.loads(line) for line in metrics_path.read_text().splitlines() if line.strip()]
    assert rows, "la corrida no escribio metricas"
    assert all(row["g2a_ms"] is None for row in rows), "two_node no debe publicar g2a_ms crudo"

    summary = json.loads((tmp_path / "runs" / run_id / "summary.json").read_text())
    assert summary["g2a"]["state"] == "not_interpretable"
    assert summary["g2a"]["causes"] == ["cross_node_monotonic_clock"]
    # Hubo unidades procesadas: el count NO debe caer a "no_units_processed"
    # solo porque el acumulador (a proposito) quedo vacio.
    assert summary["g2a"]["count"] == 0
