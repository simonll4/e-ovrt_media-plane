from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from eovrt_media.config.loader import load_run_config


def _write_config(tmp_path: Path, overrides: dict | None = None) -> Path:
    images_dir = tmp_path / "images"
    images_dir.mkdir(exist_ok=True)
    prompts_path = tmp_path / "prompts.yaml"
    prompts_path.write_text("version: v1\nitems:\n  - id: person\n    text: person\n")

    raw = {
        "run": {"scenario": "DBE"},
        "source": {"type": "image_folder", "path": str(images_dir)},
        "model": {"adapter": "mock", "device": "cpu"},
        "prompts": {"file": str(prompts_path)},
    }
    if overrides:
        raw.update(overrides)

    config_path = tmp_path / "run.yaml"
    config_path.write_text(yaml.safe_dump(raw))
    return config_path


def _minimal_config(tmp_path: Path, **overrides):
    source = {"type": "image_folder", "path": str(tmp_path / "images")}
    source.update(overrides.pop("source", {}))
    raw = {"source": source, **overrides}
    return load_run_config(_write_config(tmp_path, raw))


class TestConfigDerivation:
    def test_pulleable_source_derives_deterministic(self, tmp_path: Path):
        cfg = _minimal_config(tmp_path, source={"kind": "pulleable"})
        assert cfg.rate_control.policy == "deterministic"

    def test_single_host_derives_memory_backend(self, tmp_path: Path):
        cfg = _minimal_config(tmp_path)
        assert cfg.transport.backend == "memory"

    def test_explicit_policy_overrides_derived(self, tmp_path: Path):
        cfg = _minimal_config(tmp_path, rate_control={"policy": "bounded_freshness"})
        assert cfg.rate_control.policy == "bounded_freshness"

    def test_max_units_lives_in_run_section(self, tmp_path: Path):
        cfg = _minimal_config(tmp_path, run={"scenario": "DBE", "max_units": 10})
        assert cfg.run.max_units == 10


class TestConfigValidation:
    def test_two_node_with_memory_raises(self, tmp_path: Path):
        with pytest.raises(ValueError, match="two_node.*network"):
            _minimal_config(
                tmp_path,
                topology={"mode": "two_node"},
                transport={"backend": "memory"},
            )

    def test_stride_under_bounded_freshness_raises(self, tmp_path: Path):
        with pytest.raises(ValueError, match="stride.*deterministic"):
            _minimal_config(
                tmp_path,
                rate_control={"policy": "bounded_freshness", "stride": 2},
            )

    def test_buffer_size_under_deterministic_raises(self, tmp_path: Path):
        with pytest.raises(ValueError, match="buffer_size.*bounded_freshness"):
            _minimal_config(
                tmp_path,
                rate_control={"policy": "deterministic", "buffer_size": 3},
            )


class TestConfigGating:
    def test_two_node_topology_is_gated(self, tmp_path: Path):
        with pytest.raises(NotImplementedError, match="two_node.*implementado"):
            _minimal_config(
                tmp_path,
                topology={"mode": "two_node"},
                transport={"backend": "network", "endpoint": "tcp://localhost:5555"},
            )

    def test_ipc_backend_is_gated(self, tmp_path: Path):
        with pytest.raises(NotImplementedError, match="ipc.*implementado"):
            _minimal_config(tmp_path, transport={"backend": "ipc"})

    def test_fp16_payload_format_is_gated(self, tmp_path: Path):
        with pytest.raises(NotImplementedError, match="fp16.*implementado"):
            _minimal_config(tmp_path, transport={"payload_format": "fp16"})

    def test_camera_source_type_is_gated(self, tmp_path: Path):
        with pytest.raises(NotImplementedError, match="camera.*implementado"):
            _minimal_config(
                tmp_path,
                source={"type": "camera", "path": "/dev/video0"},
            )


class TestSamplingMigration:
    def test_sampling_key_raises_with_migration_message(self, tmp_path: Path):
        config_path = _write_config(tmp_path, {"sampling": {"every_n": 2}})
        with pytest.raises(ValueError, match="sampling.*rate_control"):
            load_run_config(config_path)


class TestRtspSourceConfig:
    def test_rtsp_derives_live_and_bounded_freshness(self, tmp_path: Path):
        cfg = _minimal_config(
            tmp_path,
            source={"type": "rtsp", "path": "rtsp://cam/stream", "url": "rtsp://cam/stream"},
        )
        assert cfg.source.kind == "live"
        assert cfg.rate_control.policy == "bounded_freshness"

    def test_rtsp_fields_have_defaults(self, tmp_path: Path):
        cfg = _minimal_config(
            tmp_path,
            source={"type": "rtsp", "path": "rtsp://cam/stream", "url": "rtsp://cam/stream"},
        )
        assert cfg.source.reconnect_retries == 5
        assert cfg.source.reconnect_delay_ms == 1000

    def test_oak_d_source_type_is_gated(self, tmp_path: Path):
        with pytest.raises(NotImplementedError, match="oak_d.*implementad"):
            _minimal_config(
                tmp_path,
                source={"type": "oak_d", "path": "oak://device"},
            )
