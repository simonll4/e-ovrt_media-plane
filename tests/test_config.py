"""Tests para la carga y validación de configuración."""

from pathlib import Path

import pytest

from eovrt_media.config import load_prompts_file, load_run_config, PromptsFile


CONFIGS_DIR = Path(__file__).parent.parent / "configs"
PROMPTS_PATH = CONFIGS_DIR / "prompts" / "cr01_cr02_v1.yaml"
GDINO_CONFIG = CONFIGS_DIR / "runs" / "gdino.yaml"
YOLOE_CONFIG = CONFIGS_DIR / "runs" / "yoloe.yaml"


class TestPromptsFile:
    """Tests para carga de archivo de prompts."""

    def test_load_prompts(self):
        prompts = load_prompts_file(PROMPTS_PATH)
        assert isinstance(prompts, PromptsFile)
        assert prompts.version == "cr01_cr02_v1"
        assert len(prompts.items) == 4

    def test_prompt_ids(self):
        prompts = load_prompts_file(PROMPTS_PATH)
        ids = [item.id for item in prompts.items]
        assert "person" in ids
        assert "helmet" in ids
        assert "vest" in ids

    def test_get_active_texts(self):
        prompts = load_prompts_file(PROMPTS_PATH)
        texts = prompts.get_active_texts(["person", "helmet"])
        assert texts == ["person", "safety helmet"]

    def test_get_active_texts_invalid_id(self):
        prompts = load_prompts_file(PROMPTS_PATH)
        with pytest.raises(ValueError, match="no encontrado"):
            prompts.get_active_texts(["nonexistent"])

    def test_prompt_aliases(self):
        prompts = load_prompts_file(PROMPTS_PATH)
        helmet = next(item for item in prompts.items if item.id == "helmet")
        assert "hard hat" in helmet.aliases
        assert "construction helmet" in helmet.aliases


class TestRunConfig:
    """Tests para carga de configuración de corrida."""

    def test_load_grounding_dino_config(self):
        config = load_run_config(GDINO_CONFIG)
        assert config.run.scenario == "DBE"
        assert config.run.name == "dbe_grounding_dino_cr01_cr02"
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
        texts = config.get_prompt_texts()
        assert len(texts) == 3
        assert "person" in texts

    def test_effective_dict(self):
        config = load_run_config(GDINO_CONFIG)
        effective = config.to_effective_dict()
        assert "run" in effective
        assert "source" in effective
        assert "model" in effective
        assert "resolved_prompts" in effective

    def test_config_not_found(self):
        with pytest.raises(FileNotFoundError):
            load_run_config(Path("nonexistent.yaml"))
