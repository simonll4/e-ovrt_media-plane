"""Contratos estáticos del despliegue two-node de infra/twonode/ (Fase 2)."""
from __future__ import annotations

from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).parent.parent
TWONODE_DIR = REPO_ROOT / "infra" / "twonode"
PLANE_CATALOG_ROOT = REPO_ROOT / "configs"


def _load_compose(name: str) -> dict:
    return yaml.safe_load((TWONODE_DIR / name).read_text())


def test_single_host_compose_runs_the_complete_two_node_stack() -> None:
    compose = _load_compose("docker-compose.yml")

    assert set(compose["services"]) == {"node-a", "node-b"}
    assert compose["services"]["node-b"]["depends_on"] == ["node-a"]
    assert compose["services"]["node-a"]["expose"] == ["5555", "5556"]


def test_two_host_manifests_do_not_start_a_remote_peer_locally() -> None:
    edge = _load_compose("docker-compose.node-a.yml")
    gpu = _load_compose("docker-compose.node-b.yml")

    assert set(edge["services"]) == {"node-a"}
    assert edge["services"]["node-a"]["ports"] == ["5555:5555", "5556:5556"]
    assert set(gpu["services"]) == {"node-b"}


def test_node_entrypoints_use_the_run_node_tool() -> None:
    compose = _load_compose("docker-compose.yml")

    dockerfile = (TWONODE_DIR / "Dockerfile.node-a").read_text()
    assert '"-m", "eovrt_media.tools.run_node", "--role", "a"' in dockerfile
    assert '".[edge]"' in dockerfile  # edge sin torch

    node_b = compose["services"]["node-b"]
    assert node_b["image"] == "eovrt/media-plane:latest"  # reusa la imagen DBE
    assert node_b["entrypoint"][-3:] == ["run_node", "--role", "b"] or (
        "eovrt_media.tools.run_node" in " ".join(node_b["entrypoint"])
        and node_b["entrypoint"][-1] == "b"
    )


def test_twonode_configs_load_and_declare_network_transport(tmp_path: Path) -> None:
    from eovrt_media.config.loader import load_run_config

    # Las configs reales usan `prompts.ref: cr01_cr02_bench_v2`, resuelto en
    # despliegue porque docker-compose monta el prompts/ del repo hermano
    # e-ovrt_experimental-setup en /app/configs/prompts (= EOVRT_MEDIA_CATALOG_ROOT
    # + "prompts", el fallback de `load_run_config_data`). Localmente ese mount no
    # existe, así que para este test se copia cada config a tmp_path reemplazando
    # `prompts.ref` por un `prompts.set_inline` mínimo — el contrato bajo prueba es
    # topología/transporte/timeout, no la resolución del catálogo de prompts.
    #
    # `catalog_root` se pasa explícito (apuntando al `configs/` real del repo) para
    # esquivar un gotcha preexistente de `find_plane_catalog_root`: como resuelve
    # la raíz del catálogo buscando el primer ancestro llamado literalmente
    # "configs", cargar directo desde infra/twonode/configs/ matchearía ese
    # directorio antes de llegar al fallback real.
    for name, endpoint_prefix in [
        ("two_node_a.yaml", "tcp://0.0.0.0:"),
        ("two_node_b.yaml", "tcp://node-a:"),
    ]:
        raw = yaml.safe_load((TWONODE_DIR / "configs" / name).read_text())
        raw["prompts"] = {
            "set_inline": {
                "id": "twonode-contract-smoke",
                "classes": [{"id": "person", "phrasings": {"default": ["person"]}}],
            },
            "active_ids": ["person"],
        }
        config_copy = tmp_path / name
        config_copy.write_text(yaml.safe_dump(raw), encoding="utf-8")

        config = load_run_config(config_copy, catalog_root=PLANE_CATALOG_ROOT)
        assert config.topology.mode == "two_node"
        assert config.transport.backend == "network"
        assert config.transport.endpoint.startswith(endpoint_prefix)
        assert config.transport.request_timeout_ms == 10000
