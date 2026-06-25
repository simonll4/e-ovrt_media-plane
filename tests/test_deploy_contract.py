"""Contratos estáticos para los artefactos de despliegue Docker."""

from __future__ import annotations

import re
from pathlib import Path

import yaml


REPO_ROOT = Path(__file__).parent.parent
DEPLOY_DIR = REPO_ROOT / "deploy"


def _load_compose(name: str) -> dict:
    return yaml.safe_load((DEPLOY_DIR / name).read_text())


def test_local_compose_runs_the_complete_two_node_stack() -> None:
    compose = _load_compose("docker-compose.yml")

    assert set(compose["services"]) == {"node-a", "node-b"}
    assert compose["services"]["node-b"]["depends_on"] == ["node-a"]


def test_two_host_manifests_do_not_start_a_remote_peer_locally() -> None:
    edge_compose = _load_compose("docker-compose.node-a.yml")
    gpu_compose = _load_compose("docker-compose.node-b.yml")

    assert set(edge_compose["services"]) == {"node-a"}
    assert edge_compose["services"]["node-a"]["ports"] == ["5555:5555", "5556:5556"]
    assert set(gpu_compose["services"]) == {"node-b"}
    assert "depends_on" not in gpu_compose["services"]["node-b"]


def test_node_b_image_pins_clip_and_downloads_mobileclip_during_build() -> None:
    dockerfile = (DEPLOY_DIR / "docker" / "Dockerfile.node-b").read_text()

    assert re.search(r"CLIP\.git@[0-9a-f]{40}", dockerfile)
    assert "MobileCLIPTS(torch.device(\"cpu\"), weight=\"mobileclip2_b.ts\")" in dockerfile
    assert "RUN test -s /app/mobileclip2_b.ts" in dockerfile
