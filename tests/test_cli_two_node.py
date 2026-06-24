"""Integración loopback de run-producer / run-consumer en el mismo proceso."""
from __future__ import annotations

import json
import socket
import threading
from pathlib import Path

import cv2
import numpy as np

from eovrt_media.config import load_run_config
from eovrt_media.runtime.two_node import run_node_a, run_node_b


CONFIGS_DIR = Path(__file__).parent.parent / "configs"


def _images(folder: Path, count: int = 4) -> None:
    folder.mkdir(parents=True, exist_ok=True)
    for i in range(count):
        cv2.imwrite(
            str(folder / f"img_{i:03d}.jpg"), np.full((48, 64, 3), i * 20, dtype=np.uint8)
        )


def _loopback_endpoint() -> str:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return f"tcp://127.0.0.1:{sock.getsockname()[1]}"


def test_two_node_loopback_produces_detections(tmp_path):
    images = tmp_path / "imgs"
    _images(images, 4)

    cfg = load_run_config(CONFIGS_DIR / "runs" / "mock.yaml")
    cfg.model.adapter = "mock"
    cfg.source.path = str(images)
    cfg.topology.mode = "two_node"
    cfg.transport.backend = "network"
    cfg.transport.endpoint = _loopback_endpoint()
    cfg.outputs.base_dir = str(tmp_path / "runs")
    cfg.outputs.run_dir = str(tmp_path / "runs")
    cfg.outputs.save_previews = False

    node_a = threading.Thread(target=run_node_a, args=(cfg,), daemon=True)
    node_a.start()

    run_id = run_node_b(cfg)
    node_a.join(timeout=10.0)

    assert node_a.is_alive() is False
    detections = (Path(cfg.outputs.base_dir) / run_id / "detections.jsonl").read_text()
    events = [json.loads(line) for line in detections.splitlines()]
    assert len(events) == 4
