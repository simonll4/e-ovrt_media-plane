"""Pre-flight del adaptador por corrida (prepare_run).

El benchmark 2026-07-23 (docs/operacion/61) midió que la PRIMERA inferencia de
cada corrida paga el binding lazy de prompts (set_classes de YOLOE: text encoder
en fp32 + round-trip float→half, ~1.1 s) y, en la primera corrida del proceso,
el autotune CUDA (~3.3 s) — con la fuente ya produciendo, lo que dropea decenas
de frames por queue_full. prepare_run(plan) mueve ese costo ANTES de abrir la
fuente.
"""

from pathlib import Path
from unittest.mock import MagicMock

import cv2
import numpy as np
import pytest
from PIL import Image

from eovrt_media.config import load_run_config
from eovrt_media.config.prompt_plan import PromptPlan
from eovrt_media.models.mock_detector import MockDetectorAdapter
from eovrt_media.models.yoloe_adapter import YOLOEUltralyticsAdapter
from eovrt_media.runtime.pipeline import execute_run

CONFIGS_DIR = Path(__file__).parent / "fixtures"


def _create_test_images(folder: Path, count: int = 3) -> None:
    folder.mkdir(parents=True, exist_ok=True)
    for i in range(count):
        img = np.zeros((480, 640, 3), dtype=np.uint8)
        img[:] = (50 + i * 30, 100, 200)
        cv2.imwrite(str(folder / f"test_{i:03d}.jpg"), img)


@pytest.fixture
def mock_config(tmp_path):
    images_dir = tmp_path / "images"
    _create_test_images(images_dir, count=3)
    config = load_run_config(CONFIGS_DIR / "runs" / "gdino.yaml")
    config.model.adapter = "mock"
    config.model.name = "mock"
    config.source.path = str(images_dir)
    config.outputs.base_dir = str(tmp_path / "runs")
    config.outputs.run_dir = str(tmp_path / "runs")
    return config


class _SpyAdapter(MockDetectorAdapter):
    """Registra el orden de prepare_run vs forward."""

    def __init__(self):
        super().__init__()
        self.events: list[tuple[str, object]] = []

    def prepare_run(self, plan: PromptPlan) -> None:
        self.events.append(("prepare_run", plan))
        super().prepare_run(plan)

    def forward(self, unit, plan):
        self.events.append(("forward", plan))
        return super().forward(unit, plan)


class TestPipelineCallsPrepareRun:
    def test_prepare_run_se_llama_con_el_plan_antes_del_primer_forward(self, mock_config):
        adapter = _SpyAdapter()
        adapter.load()
        execute_run(mock_config, adapter)

        kinds = [kind for kind, _ in adapter.events]
        assert "prepare_run" in kinds, "execute_run nunca llamó prepare_run"
        assert "forward" in kinds, "la corrida no procesó unidades"
        assert kinds.index("prepare_run") < kinds.index("forward")

        prepare_plan = next(plan for kind, plan in adapter.events if kind == "prepare_run")
        forward_plan = next(plan for kind, plan in adapter.events if kind == "forward")
        assert prepare_plan is forward_plan, "el pre-flight debe usar el plan REAL del run"


class TestBasePrepareRun:
    def test_base_hace_una_inferencia_dummy_con_el_plan_real(self):
        adapter = MockDetectorAdapter()
        adapter.load()
        plan = PromptPlan.from_texts(["person"], "default")
        calls: list[tuple[object, object]] = []
        original = adapter.predict

        def spy_predict(image, p):
            calls.append((image, p))
            return original(image, p)

        adapter.predict = spy_predict
        adapter.prepare_run(plan)

        assert len(calls) == 1
        image, seen_plan = calls[0]
        assert seen_plan is plan
        assert isinstance(image, Image.Image)
        assert image.size == adapter.input_spec.target_size


class TestYoloePrepareRun:
    def _fake_model(self):
        fake = MagicMock()
        result = MagicMock()
        result.boxes = None
        fake.predict.return_value = [result]
        return fake

    def test_prepare_run_bindea_clases_y_no_las_rebindea_en_predict(self):
        adapter = YOLOEUltralyticsAdapter(device="cpu")
        adapter.model = self._fake_model()
        plan = PromptPlan.from_texts(["person"], "yoloe")

        adapter.prepare_run(plan)

        adapter.model.set_classes.assert_called_once_with(["person"])
        assert adapter.model.predict.call_count == 1, "el pre-flight debe inferir en dummy"

        adapter.predict(Image.new("RGB", (8, 8)), plan)
        assert adapter.model.set_classes.call_count == 1, (
            "el primer frame real no debe pagar set_classes de nuevo"
        )
