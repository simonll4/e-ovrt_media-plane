from __future__ import annotations

from pathlib import Path
from urllib.parse import urlparse

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


def _endpoint_port(endpoint: str) -> int | None:
    parsed = urlparse(endpoint)
    return parsed.port


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

    @pytest.mark.parametrize(
        ("field", "value"),
        [("heartbeat_interval_ms", 0), ("heartbeat_timeout_ms", -1)],
    )
    def test_heartbeat_timing_requires_positive_values(
        self, tmp_path: Path, field: str, value: int
    ):
        with pytest.raises(ValueError, match=field):
            _minimal_config(
                tmp_path,
                topology={"mode": "two_node"},
                transport={
                    "backend": "network",
                    "endpoint": "tcp://127.0.0.1:5555",
                    "heartbeat_endpoint": "tcp://127.0.0.1:5556",
                    field: value,
                },
            )


class TestConfigGating:
    def test_two_node_with_network_is_valid(self, tmp_path: Path):
        cfg = _minimal_config(
            tmp_path,
            topology={"mode": "two_node"},
            transport={
                "backend": "network",
                "endpoint": "tcp://127.0.0.1:5555",
                "heartbeat_endpoint": "tcp://127.0.0.1:5556",
            },
        )
        assert cfg.topology.mode == "two_node"
        assert cfg.transport.backend == "network"
        assert cfg.transport.heartbeat_timeout_ms == 5000

    def test_network_transport_requires_heartbeat_endpoint(self, tmp_path: Path):
        with pytest.raises(ValueError, match="heartbeat_endpoint"):
            _minimal_config(
                tmp_path,
                topology={"mode": "two_node"},
                transport={"backend": "network", "endpoint": "tcp://127.0.0.1:5555"},
            )

    def test_ipc_backend_is_invalid(self, tmp_path: Path):
        with pytest.raises(ValueError, match="backend debe ser"):
            _minimal_config(tmp_path, transport={"backend": "ipc"})

    def test_fp16_payload_format_is_valid(self, tmp_path: Path):
        cfg = _minimal_config(tmp_path, transport={"payload_format": "fp16"})
        assert cfg.transport.payload_format == "fp16"

    def test_two_node_network_config_accepts_fp16_with_endpoint(self, tmp_path: Path):
        cfg = _minimal_config(
            tmp_path,
            topology={"mode": "two_node"},
            transport={
                "backend": "network",
                "endpoint": "tcp://127.0.0.1:5555",
                "heartbeat_endpoint": "tcp://127.0.0.1:5556",
                "payload_format": "fp16",
            },
        )
        assert cfg.transport.payload_format == "fp16"
        assert cfg.transport.endpoint == "tcp://127.0.0.1:5555"

    def test_network_run_configs_declare_dedicated_heartbeat_endpoint(self):
        network_configs = []
        config_roots = (Path("configs") / "runs", Path("deploy") / "configs")
        config_paths = sorted(
            path for root in config_roots if root.exists() for path in root.rglob("*.yaml")
        )
        for config_path in config_paths:
            raw = yaml.safe_load(config_path.read_text()) or {}
            transport = raw.get("transport") or {}
            topology = raw.get("topology") or {}
            if transport.get("backend") != "network" and topology.get("mode") != "two_node":
                continue

            network_configs.append(config_path)
            endpoint = transport.get("endpoint")
            heartbeat_endpoint = transport.get("heartbeat_endpoint")
            assert endpoint, f"{config_path} must declare transport.endpoint"
            assert heartbeat_endpoint, (
                f"{config_path} must declare transport.heartbeat_endpoint"
            )
            assert heartbeat_endpoint != endpoint, (
                f"{config_path} must use a dedicated heartbeat endpoint"
            )
            assert _endpoint_port(heartbeat_endpoint) != _endpoint_port(endpoint), (
                f"{config_path} heartbeat must use a port distinct from data"
            )
            if Path("configs") / "runs" in config_path.parents:
                load_run_config(config_path)

        assert network_configs, "Expected at least one network run config"

    def test_camera_source_type_is_rejected_with_migration_guidance(self, tmp_path: Path):
        with pytest.raises(ValueError) as exc_info:
            _minimal_config(
                tmp_path,
                source={"type": "camera", "path": "/dev/video0"},
            )

        message = str(exc_info.value)
        assert "source.type=camera no está soportado" in message
        assert "image_folder, video_file, rtsp, oak_d" in message
        assert "Migrar source.type=camera a rtsp o oak_d" in message


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
