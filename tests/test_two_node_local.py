from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from eovrt_media.runtime.two_node_local import (
    LocalTwoNodeOptions,
    build_run_config,
    resolve_source,
    write_generated_config,
)


def test_bench_val_source_resolves_catalog_ref() -> None:
    options = LocalTwoNodeOptions(source="bench-val", max_units=7)

    source = resolve_source(options)

    assert source == {"ref": "bench_v2_val"}


def test_video_source_requires_video_path() -> None:
    options = LocalTwoNodeOptions(source="video")

    with pytest.raises(ValueError, match="--video"):
        resolve_source(options)


def test_video_source_uses_inline_video_file(tmp_path: Path) -> None:
    video = tmp_path / "sample.mp4"
    video.write_bytes(b"not-a-real-video")
    options = LocalTwoNodeOptions(source="video", video=video)

    source = resolve_source(options)

    assert source == {"type": "video_file", "path": str(video)}


def test_ezviz_source_uses_rtsp_url_from_option() -> None:
    options = LocalTwoNodeOptions(source="ezviz", rtsp_url="rtsp://user:secret@cam/live")

    source = resolve_source(options)

    assert source["type"] == "rtsp"
    assert source["path"] == "rtsp://user:secret@cam/live"
    assert source["url"] == "rtsp://user:secret@cam/live"
    assert source["reconnect_retries"] == 5
    assert source["reconnect_delay_ms"] == 1000


def test_ezviz_source_requires_url() -> None:
    options = LocalTwoNodeOptions(source="ezviz")

    with pytest.raises(ValueError, match="EZVIZ_RTSP_URL"):
        resolve_source(options)


def test_build_run_config_sets_two_node_network_defaults(tmp_path: Path) -> None:
    options = LocalTwoNodeOptions(
        source="bench-val",
        codec="raw",
        payload_format="uint8_rgb",
        max_units=3,
        device="cpu",
        model_ref="mock",
        prompts_ref="cr01_cr02_bench_v2",
        save_previews=False,
    )

    raw = build_run_config(
        options,
        endpoint="tcp://127.0.0.1:5601",
        heartbeat_endpoint="tcp://127.0.0.1:5602",
    )

    assert raw["run"]["scenario"] == "EBE"
    assert raw["run"]["max_units"] == 3
    assert raw["source"] == {"ref": "bench_v2_val"}
    assert raw["model"] == {"ref": "mock", "device": "cpu"}
    assert raw["prompts"] == {
        "ref": "cr01_cr02_bench_v2",
        "active_ids": ["person", "helmet", "vest", "bare_head"],
    }
    assert raw["topology"] == {"mode": "two_node"}
    assert raw["transport"]["backend"] == "network"
    assert raw["transport"]["endpoint"] == "tcp://127.0.0.1:5601"
    assert raw["transport"]["heartbeat_endpoint"] == "tcp://127.0.0.1:5602"
    assert raw["transport"]["compression"] == {"codec": "raw", "quality": 90}
    assert raw["outputs"]["save_previews"] is False


def test_write_generated_config_persists_yaml(tmp_path: Path) -> None:
    raw = {
        "run": {"scenario": "EBE", "name": "local_two_node_bench_val"},
        "source": {"ref": "bench_v2_val"},
        "model": {"ref": "mock", "device": "cpu"},
        "prompts": {"ref": "cr01_cr02_bench_v2", "active_ids": ["person"]},
        "topology": {"mode": "two_node"},
        "transport": {
            "backend": "network",
            "endpoint": "tcp://127.0.0.1:5601",
            "heartbeat_endpoint": "tcp://127.0.0.1:5602",
            "payload_format": "uint8_rgb",
            "compression": {"codec": "jpeg", "quality": 90},
        },
    }

    path = write_generated_config(raw, tmp_path, stem="bench_val")

    assert path == tmp_path / "bench_val.yaml"
    assert yaml.safe_load(path.read_text()) == raw
