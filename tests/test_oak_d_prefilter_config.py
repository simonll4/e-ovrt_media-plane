"""Schema del prefilter EN-2 y knobs de latencia de oak_d (spec 2026-07-15 §6/§7/§8)."""
from __future__ import annotations

import pytest
from pydantic import ValidationError

from eovrt_media.config.schemas import OakDPrefilterConfig, SourceSection

OAK = {"type": "oak_d", "url": "192.168.1.50"}


def test_prefilter_defaults_off():
    s = SourceSection(**OAK)
    assert s.prefilter is None
    assert s.isp_scale is None
    assert s.xlink_chunk_size == 0


def test_prefilter_block_defaults():
    cfg = OakDPrefilterConfig(enabled=True)
    assert cfg.model_blob == "models/edge/person-detection-retail-0013_6shave.blob"
    assert cfg.confidence == 0.25
    assert cfg.keepalive_window_ms == 1500
    assert cfg.heartbeat_interval_ms == 2000
    assert cfg.stall_failopen_ms == 3000


def test_prefilter_confidence_out_of_range():
    with pytest.raises(ValidationError):
        OakDPrefilterConfig(confidence=0.0)
    with pytest.raises(ValidationError):
        OakDPrefilterConfig(confidence=1.0)


def test_prefilter_stall_must_cover_keepalive():
    with pytest.raises(ValidationError, match="stall_failopen_ms"):
        OakDPrefilterConfig(keepalive_window_ms=5000, stall_failopen_ms=1000)


def test_prefilter_accepted_for_oak_d():
    s = SourceSection(**OAK, prefilter={"enabled": True})
    assert s.prefilter is not None and s.prefilter.enabled


@pytest.mark.parametrize("source_type,extra", [
    ("rtsp", {"url": "rtsp://cam/1"}),
    ("image_folder", {"path": "/tmp/imgs"}),
    ("video_file", {"path": "/tmp/v.mp4"}),
])
def test_new_fields_rejected_on_non_oak_d(source_type, extra):
    with pytest.raises(ValidationError, match="oak_d"):
        SourceSection(type=source_type, **extra, prefilter={"enabled": True})
    with pytest.raises(ValidationError, match="oak_d"):
        SourceSection(type=source_type, **extra, isp_scale=(3, 4))
    with pytest.raises(ValidationError, match="oak_d"):
        SourceSection(type=source_type, **extra, xlink_chunk_size=0)  # seteado, aun con el valor default


def test_non_oak_d_without_new_fields_still_valid():
    # Invariante §8.2: configs existentes validan idéntico.
    s = SourceSection(type="rtsp", url="rtsp://cam/1")
    assert s.xlink_chunk_size == 0


def test_warmup_frames_default_es_cero():
    assert SourceSection(type="rtsp", url="rtsp://cam/1").warmup_frames == 0
    assert SourceSection(type="image_folder", path="/tmp/imgs").warmup_frames == 0


@pytest.mark.parametrize("source_type,extra", [
    ("rtsp", {"url": "rtsp://cam/1"}),
    ("oak_d", {"url": "192.168.1.50"}),
])
def test_warmup_frames_aceptado_en_fuentes_vivas(source_type, extra):
    assert SourceSection(type=source_type, **extra, warmup_frames=15).warmup_frames == 15


@pytest.mark.parametrize("source_type,extra", [
    ("image_folder", {"path": "/tmp/imgs"}),
    ("video_file", {"path": "/tmp/v.mp4"}),
])
def test_warmup_frames_rechazado_en_fuentes_no_vivas(source_type, extra):
    with pytest.raises(ValidationError, match="warmup_frames"):
        SourceSection(type=source_type, **extra, warmup_frames=10)


def test_warmup_frames_negativo_rechazado():
    with pytest.raises(ValidationError):
        SourceSection(type="rtsp", url="rtsp://cam/1", warmup_frames=-1)


def test_oak_d_reconnect_defaults_toleran_cold_boot():
    # Sin fijarlos, oak_d usa defaults pacientes para el cold-boot PoE (~8-40s).
    s = SourceSection(**OAK)
    assert s.reconnect_retries == 12
    assert s.reconnect_delay_ms == 4000


def test_oak_d_reconnect_explicitos_ganan():
    # Config explícita sobrescribe el bump.
    s = SourceSection(**OAK, reconnect_retries=2, reconnect_delay_ms=500)
    assert s.reconnect_retries == 2
    assert s.reconnect_delay_ms == 500


def test_rtsp_reconnect_defaults_inalterados():
    # RTSP conserva sus defaults (conecta en ~2s; no se toca).
    s = SourceSection(type="rtsp", url="rtsp://cam/1")
    assert s.reconnect_retries == 5
    assert s.reconnect_delay_ms == 1000


def test_isp_scale_shape_validated():
    assert SourceSection(**OAK, isp_scale=(3, 4)).isp_scale == (3, 4)
    assert SourceSection(**OAK, isp_scale=(2, 4)).isp_scale == (2, 4)  # simplifica a 1/2: ok
    with pytest.raises(ValidationError, match="isp_scale"):
        SourceSection(**OAK, isp_scale=(0, 4))
    with pytest.raises(ValidationError, match="isp_scale"):
        SourceSection(**OAK, isp_scale=(17, 5))   # num>16 irreducible
    with pytest.raises(ValidationError, match="isp_scale"):
        SourceSection(**OAK, isp_scale=(1, 64))   # den>63 irreducible


def test_xlink_chunk_size_range():
    assert SourceSection(**OAK, xlink_chunk_size=-1).xlink_chunk_size == -1
    assert SourceSection(**OAK, xlink_chunk_size=65536).xlink_chunk_size == 65536
    with pytest.raises(ValidationError, match="xlink_chunk_size"):
        SourceSection(**OAK, xlink_chunk_size=-2)
