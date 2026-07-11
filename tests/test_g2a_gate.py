"""Gate: los tres insumos de t_capture->alert existen y son coherentes (spec 40 SS5.2.4)."""

import json
from pathlib import Path

import pytest
from PIL import Image

from eovrt_media.config.loader import load_run_config_data
from eovrt_media.models import create_adapter
from eovrt_media.runtime.pipeline import execute_run

REPO_ROOT = Path(__file__).resolve().parents[1]
SET_INLINE = {"id": "t", "classes": [{"id": "p", "phrasings": {"default": ["p"]}}]}


def _make_images(folder: Path, n: int) -> None:
    folder.mkdir(parents=True, exist_ok=True)
    for i in range(n):
        Image.new("RGB", (64, 48), (i * 10 % 255, 0, 0)).save(folder / f"img_{i:03d}.png")


def _config(tmp_path: Path, run_id: str, warmup_units: int = 0):
    images = tmp_path / "images"
    _make_images(images, 6)
    raw = {
        "run": {"id": run_id, "warmup_units": warmup_units},
        "source": {"type": "image_folder", "path": str(images)},
        "model": {"adapter": "mock"},
        "prompts": {"set_inline": SET_INLINE},
        "outputs": {"run_dir": str(tmp_path / "runs"), "save_previews": False},
    }
    return load_run_config_data(raw, plane_root=REPO_ROOT / "configs")


def _run(config) -> str:
    adapter = create_adapter(config.model)
    adapter.load()
    try:
        return execute_run(config, adapter)
    finally:
        adapter.close()


@pytest.mark.parametrize("warmup", [0, 2])
def test_run_emits_capture_stamps_g2a_and_source_clock(tmp_path, warmup) -> None:
    config = _config(tmp_path, f"gate-{warmup}", warmup_units=warmup)
    run_id = _run(config)

    run_dir = tmp_path / "runs" / run_id
    metrics = [
        json.loads(line) for line in (run_dir / "metrics.jsonl").read_text().splitlines()
        if line.strip()
    ]
    summary = json.loads((run_dir / "summary.json").read_text())

    # 1. Los tres campos por unidad, con `unit_id` como clave de join.
    assert {"unit_id", "capture_monotonic_ns", "capture_wallclock_ms", "g2a_ms"} <= set(metrics[0])
    assert all(row["g2a_ms"] > 0.0 for row in metrics)
    # capture_monotonic_ns tiene que venir de la LECTURA de la unidad, no de un
    # default fijo: si el reloj de captura no se estampa, esto lo caza.
    assert all(row["capture_monotonic_ns"] > 0 for row in metrics)

    # 2. La fuente declara su reloj (image_folder => fuente no temporal).
    assert summary["source_clock"] == "none"

    # 3. El bloque G2A declara warm-up y estado, y no miente sobre el conteo.
    g2a = summary["g2a"]
    assert g2a["warmup_units"] == warmup
    assert g2a["count"] == max(len(metrics) - warmup, 0)
    assert g2a["state"] == "computed"
    assert g2a["p50_ms"] > 0.0
    assert (g2a["budget_min_ms"], g2a["budget_max_ms"]) == (50.0, 250.0)


def test_g2a_is_monotonic_with_the_unit_latency(tmp_path) -> None:
    """El G2A de una unidad no puede ser MENOR que su propia latencia de inferencia:
    la contiene por construccion. Si lo fuera, el reloj de captura esta mal estampado
    (p.ej. re-estampado despues de la normalizacion en vez de al leer la unidad)."""
    config = _config(tmp_path, "gate-monotonic")
    run_id = _run(config)

    metrics_path = tmp_path / "runs" / run_id / "metrics.jsonl"
    rows = [json.loads(line) for line in metrics_path.read_text().splitlines() if line.strip()]
    assert rows
    for row in rows:
        assert row["g2a_ms"] >= row["latency_inference_ms"], row["unit_id"]
