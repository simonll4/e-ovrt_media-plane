from eovrt_media.sources.registry import (
    create_source,
    list_plugins,
)
from eovrt_media.config.loader import load_run_config_data
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SET_INLINE = {"id": "t", "classes": [{"id": "p", "phrasings": {"default": ["p"]}}]}


def _config(tmp_path, **source):
    raw = {
        "run": {},
        "source": source,
        "model": {"adapter": "mock"},
        "prompts": {"set_inline": SET_INLINE},
    }
    return load_run_config_data(raw, plane_root=REPO_ROOT / "configs")


def test_list_plugins_expone_los_cuatro():
    plugins = {p["id"]: p for p in list_plugins()}
    assert set(plugins) == {"image_folder", "video_file", "rtsp", "oak_d"}
    assert plugins["image_folder"]["kind"] == "bounded"
    assert plugins["rtsp"]["kind"] == "live"
    assert plugins["oak_d"]["available"] is False
    assert plugins["image_folder"]["available"] is True


def test_create_source_image_folder(tmp_path):
    config = _config(tmp_path, type="image_folder", path=str(tmp_path))
    source = create_source(config)
    assert type(source).__name__ == "ImageFolderSource"


def test_pipeline_reexporta_create_source():
    from eovrt_media.runtime.pipeline import create_source as pipeline_create_source
    from eovrt_media.sources.registry import create_source as registry_create_source
    assert pipeline_create_source is registry_create_source
