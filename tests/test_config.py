"""Tests para la carga y validación de configuración."""

from pathlib import Path

import pytest

from eovrt_media.config import load_prompts_file, load_run_config, PromptsFile
from eovrt_media.config.schemas import OutputsConfig


CONFIGS_DIR = Path(__file__).parent / "fixtures"
PROMPTS_PATH = CONFIGS_DIR / "prompts" / "cr01_cr02_v2_short.yaml"
GDINO_CONFIG = CONFIGS_DIR / "runs" / "gdino.yaml"
YOLOE_CONFIG = CONFIGS_DIR / "runs" / "yoloe.yaml"


class TestOutputsConfig:
    """Tests para los campos de salida de video anotado."""

    def test_annotated_video_defaults(self):
        cfg = OutputsConfig()
        assert cfg.save_annotated_video is False
        assert cfg.video_fps is None

    def test_annotated_video_explicit(self):
        cfg = OutputsConfig(save_annotated_video=True, video_fps=6.0)
        assert cfg.save_annotated_video is True
        assert cfg.video_fps == 6.0


class TestPromptsFile:
    """Tests para carga de archivo de prompts (formato único nuevo)."""

    def test_load_prompts(self):
        prompts = load_prompts_file(PROMPTS_PATH)
        assert isinstance(prompts, PromptsFile)
        assert prompts.resolved_set_id() == "cr01_cr02_v2_short"
        assert len(prompts.prompt_set.classes) == 3

    def test_prompt_ids(self):
        prompts = load_prompts_file(PROMPTS_PATH)
        ids = [c.id for c in prompts.prompt_set.classes]
        assert "person" in ids
        assert "helmet" in ids
        assert "vest" in ids

    def test_canonical_defaults_to_id(self):
        prompts = load_prompts_file(PROMPTS_PATH)
        helmet = next(c for c in prompts.prompt_set.classes if c.id == "helmet")
        assert helmet.canonical == "helmet"

    def test_build_plan_active_subset(self):
        prompts = load_prompts_file(PROMPTS_PATH)
        plan = prompts.build_plan("yoloe", ["person", "helmet"])
        assert plan.texts() == ["person", "helmet"]
        assert plan.by_index()[1].prompt_id == "helmet"

    def test_build_plan_invalid_id(self):
        prompts = load_prompts_file(PROMPTS_PATH)
        with pytest.raises(ValueError, match="no encontrado"):
            prompts.build_plan("yoloe", ["nonexistent"])

    def test_build_plan_empty_phrasings_list_errors(self):
        from eovrt_media.config.schemas import PromptClass, PromptSet, PromptsFile

        f = PromptsFile(prompt_set=PromptSet(id="x", classes=[
            PromptClass(id="helmet", phrasings={"gdino": [], "default": ["helmet"]}),
        ]))
        # Una entrada de backend presente pero vacía es error, no fallback a default.
        with pytest.raises(ValueError, match="ausente o vac"):
            f.build_plan("gdino")

    def test_build_plan_no_active_classes_errors(self):
        from eovrt_media.config.schemas import PromptClass, PromptSet, PromptsFile

        f = PromptsFile(prompt_set=PromptSet(id="x", classes=[
            PromptClass(id="helmet", enabled_by_default=False, phrasings={"default": ["helmet"]}),
        ]))
        with pytest.raises(ValueError, match="plan resultó vacío"):
            f.build_plan("default", active_ids=None)

    def test_phrasings_are_short_labels(self):
        prompts = load_prompts_file(PROMPTS_PATH)
        helmet = next(c for c in prompts.prompt_set.classes if c.id == "helmet")
        assert helmet.phrasings["default"] == ["helmet"]


class TestRunConfig:
    """Tests para carga de configuración de corrida."""

    def test_load_grounding_dino_config(self):
        config = load_run_config(GDINO_CONFIG)
        assert config.run.scenario == "DBE"
        assert config.run.name == "dbe_grounding_dino_demo_v2"
        assert config.model.adapter in ("grounding_dino", "grounding_dino_hf")
        assert config.source.type == "image_folder"

    def test_load_yoloe_config(self):
        config = load_run_config(YOLOE_CONFIG)
        assert config.run.scenario == "DBE"
        assert config.model.adapter in ("yoloe", "yoloe_ultralytics")
        assert config.model.weights == "models/yoloe/original/yoloe-26s-seg.pt"

    def test_prompts_loaded(self):
        config = load_run_config(GDINO_CONFIG)
        assert config.prompts_file is not None
        plan = config.build_prompt_plan("gdino")
        assert len(plan.texts()) == 3
        assert "person" in plan.texts()

    def test_effective_dict(self):
        config = load_run_config(GDINO_CONFIG)
        effective = config.to_effective_dict()
        assert "run" in effective
        assert "source" in effective
        assert "model" in effective
        assert "resolved_prompt_set" in effective
        assert "resolved_prompt_classes" in effective

    def test_config_not_found(self):
        with pytest.raises(FileNotFoundError):
            load_run_config(Path("nonexistent.yaml"))

    def test_experiment_section_defaults_none(self):
        from eovrt_media.config.schemas import RunConfig

        cfg = RunConfig(
            run={"name": "x"}, source={"path": "p"},
            model={"name": "mock"}, prompts={"ref": "r"},
        )
        assert cfg.experiment.id is None

    def test_experiment_section_explicit(self):
        from eovrt_media.config.schemas import RunConfig

        cfg = RunConfig(
            run={"name": "x"}, source={"path": "p"},
            model={"name": "mock"}, prompts={"ref": "r"},
            experiment={"id": "bench_v2_gdino_tiny"},
        )
        assert cfg.experiment.id == "bench_v2_gdino_tiny"
