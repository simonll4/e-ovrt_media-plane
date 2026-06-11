"""Tests para la resolución de referencias a catálogos en run configs."""

import textwrap
from pathlib import Path

import pytest

from eovrt_media.config import load_run_config


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(textwrap.dedent(content))


@pytest.fixture
def configs_root(tmp_path: Path) -> Path:
    """Árbol de catálogos mínimo: modelo, dataset y prompts."""
    configs = tmp_path / "configs"
    _write(
        configs / "models" / "yoloe" / "yoloe-26s.yaml",
        """
        family: yoloe
        variant: yoloe-26s
        lineage: original
        adapter: yoloe
        weights: models/yoloe/original/yoloe-26s-seg.pt
        device: cpu
        confidence_threshold: 0.25
        iou_threshold: 0.50
        image_size: 640
        """,
    )
    _write(
        configs / "datasets" / "dataset_v1.yaml",
        """
        type: image_folder
        path: data/samples/images/dataset_v1
        extensions: [".jpg", ".png"]
        """,
    )
    _write(
        configs / "prompts" / "epp_v1.yaml",
        """
        prompt_set:
          id: epp_v1
          items:
            - id: person
              text: "person"
            - id: helmet
              text: "helmet"
        """,
    )
    return configs


def _write_run_config(configs: Path, body: str) -> Path:
    run_path = configs / "runs" / "run.yaml"
    _write(run_path, body)
    return run_path


BASE_RUN = """
run:
  name: test_run
source:
  ref: dataset_v1
model:
  ref: yoloe/yoloe-26s
prompts:
  ref: epp_v1
"""


class TestRefResolution:
    def test_model_ref_resolves_catalog_fields(self, configs_root: Path):
        config = load_run_config(_write_run_config(configs_root, BASE_RUN))
        assert config.model.adapter == "yoloe"
        assert config.model.weights == "models/yoloe/original/yoloe-26s-seg.pt"
        assert config.model.family == "yoloe"
        assert config.model.lineage == "original"
        assert config.model.ref == "yoloe/yoloe-26s"

    def test_run_config_overrides_catalog(self, configs_root: Path):
        body = BASE_RUN.replace(
            "  ref: yoloe/yoloe-26s",
            "  ref: yoloe/yoloe-26s\n  device: cuda\n  confidence_threshold: 0.15",
        )
        config = load_run_config(_write_run_config(configs_root, body))
        assert config.model.device == "cuda"
        assert config.model.confidence_threshold == 0.15
        # Lo no pisado conserva el valor de catálogo
        assert config.model.iou_threshold == 0.50

    def test_source_ref_resolves_dataset(self, configs_root: Path):
        config = load_run_config(_write_run_config(configs_root, BASE_RUN))
        assert config.source.type == "image_folder"
        assert config.source.path == "data/samples/images/dataset_v1"
        assert config.source.ref == "dataset_v1"

    def test_prompts_ref_resolves_prompt_set(self, configs_root: Path):
        config = load_run_config(_write_run_config(configs_root, BASE_RUN))
        assert config.prompts_file is not None
        assert config.get_prompt_texts() == ["person", "helmet"]

    def test_unknown_model_ref_raises(self, configs_root: Path):
        body = BASE_RUN.replace("yoloe/yoloe-26s", "yoloe/nonexistent")
        with pytest.raises(FileNotFoundError, match="catálogo 'models'"):
            load_run_config(_write_run_config(configs_root, body))

    def test_ref_with_path_traversal_raises(self, configs_root: Path):
        body = BASE_RUN.replace("yoloe/yoloe-26s", "../datasets/dataset_v1")
        with pytest.raises(ValueError, match="Referencia inválida"):
            load_run_config(_write_run_config(configs_root, body))

    def test_inline_config_without_refs_still_works(self, configs_root: Path):
        body = """
        run:
          name: inline_run
        source:
          type: image_folder
          path: data/samples/images/dataset_v1
        model:
          name: mock
        prompts:
          file: ../prompts/epp_v1.yaml
        """
        run_path = _write_run_config(configs_root, body)
        config = load_run_config(run_path)
        assert config.model.adapter == "mock"
        assert config.get_prompt_texts() == ["person", "helmet"]
