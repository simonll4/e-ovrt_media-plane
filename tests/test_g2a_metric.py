import json
import time
from pathlib import Path

from PIL import Image

from eovrt_media.config.loader import load_run_config_data
from eovrt_media.contracts.metrics import MetricSample
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


def test_metric_sample_has_the_capture_and_g2a_fields_with_defaults() -> None:
    """Aditivo: un metrics.jsonl viejo (sin estos campos) sigue validando."""
    sample = MetricSample(run_id="r", unit_id="u")

    assert sample.capture_monotonic_ns == 0
    assert sample.capture_wallclock_ms == 0.0
    assert sample.g2a_ms is None
    assert sample.schema_version == "media.metric.v2"


def test_metric_sample_g2a_ms_is_none_by_default_and_accepts_an_explicit_value() -> None:
    """Aditividad + semantica de "no medible": None nunca se confunde con un 0.0
    que podria ser un valor legitimo (revision de codigo sobre Task 3)."""
    assert MetricSample(run_id="r", unit_id="u").g2a_ms is None
    assert MetricSample(run_id="r", unit_id="u", g2a_ms=42.0).g2a_ms == 42.0


def test_metric_sample_accepts_the_new_fields() -> None:
    sample = MetricSample(run_id="r", unit_id="u", capture_monotonic_ns=5,
                          capture_wallclock_ms=1.5, g2a_ms=42.0)

    assert (sample.capture_monotonic_ns, sample.capture_wallclock_ms, sample.g2a_ms) == (
        5, 1.5, 42.0
    )


def test_execute_run_writes_g2a_per_unit(tmp_path) -> None:
    """Cada fila de metrics.jsonl trae los tres insumos de t_capture->alert,
    con `unit_id` como clave de join (spec 40 SS5.2.4)."""
    config = _config(tmp_path, "g2a-metric")
    run_id = _run(config)

    metrics_path = tmp_path / "runs" / run_id / "metrics.jsonl"
    rows = [json.loads(line) for line in metrics_path.read_text().splitlines() if line.strip()]
    assert rows, "la corrida no escribio metricas"

    now_ns = time.monotonic_ns()
    for row in rows:
        assert row["unit_id"]
        assert 0 < row["capture_monotonic_ns"] <= now_ns
        assert row["capture_wallclock_ms"] > 0.0
        # G2A positivo y acotado: una corrida mock no tarda 60 s por unidad.
        assert 0.0 < row["g2a_ms"] < 60_000.0
