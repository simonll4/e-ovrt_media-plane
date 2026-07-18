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
    import importlib.util

    plugins = {p["id"]: p for p in list_plugins()}
    assert set(plugins) == {"image_folder", "video_file", "rtsp", "oak_d"}
    assert plugins["image_folder"]["kind"] == "bounded"
    assert plugins["rtsp"]["kind"] == "live"
    # oak_d disponible si y solo si el SDK DepthAI está instalado (extra edge):
    # el catálogo nunca debe anunciar un plugin que solo puede fallar.
    depthai_instalado = importlib.util.find_spec("depthai") is not None
    assert plugins["oak_d"]["available"] is depthai_instalado
    assert plugins["image_folder"]["available"] is True


def test_create_source_image_folder(tmp_path):
    config = _config(tmp_path, type="image_folder", path=str(tmp_path))
    source = create_source(config)
    assert type(source).__name__ == "ImageFolderSource"


def test_pipeline_reexporta_create_source():
    from eovrt_media.runtime.pipeline import create_source as pipeline_create_source
    from eovrt_media.sources.registry import create_source as registry_create_source
    assert pipeline_create_source is registry_create_source


def test_source_section_acepta_source_id():
    from eovrt_media.config.schemas import SourceSection

    section = SourceSection(type="image_folder", path="/x", source_id="cb_b01_p7")
    assert section.source_id == "cb_b01_p7"


def test_source_section_source_id_default_none():
    from eovrt_media.config.schemas import SourceSection

    section = SourceSection(type="image_folder", path="/x")
    assert section.source_id is None


def test_create_source_propaga_source_id(tmp_path):
    config = _config(tmp_path, type="image_folder", path=str(tmp_path), source_id="cb_b01_p7")
    source = create_source(config)
    assert source.source_id == "cb_b01_p7"


def test_create_source_sin_source_id_no_lo_setea(tmp_path):
    config = _config(tmp_path, type="image_folder", path=str(tmp_path))
    source = create_source(config)
    assert source.source_id is None


def test_create_source_oak_d(tmp_path):
    from eovrt_media.sources.oak_d_source import OakDSource

    config = _config(
        tmp_path, type="oak_d", url="192.168.1.50", fps=5, resolution="720p"
    )
    source = create_source(config)
    assert isinstance(source, OakDSource)
    assert source.url == "192.168.1.50"
    assert source.fps == 5
    assert source.resolution == "720p"
    # Default de oak_d sin fijar: bump de cold-boot PoE (ver SourceSection).
    assert source.reconnect_retries == 12
