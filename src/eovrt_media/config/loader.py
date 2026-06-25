"""Carga y validación de configuración del plano de medios.

Las run configs pueden componer secciones por referencia a los catálogos
bajo ``configs/``:

- ``model.ref: <familia>/<variante>`` → ``configs/models/<...>.yaml``
- ``source.ref: <nombre>``           → ``configs/datasets/<nombre>.yaml``
- ``prompts.ref: <nombre>``          → ``configs/prompts/<nombre>.yaml``

Los campos declarados inline en la run config pisan los del catálogo, de modo
que un experimento solo necesita expresar lo que cambia respecto del default.
El formato inline completo (sin refs) sigue siendo válido.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from eovrt_media.config.schemas import PromptsFile, RunConfig


_SUPPORTED_SOURCE_TYPES = ("image_folder", "video_file", "rtsp", "oak_d")
_PULLEABLE_TYPES = {"image_folder", "video_file"}
_LIVE_TYPES = {"rtsp", "oak_d"}


def _raise_sampling_migration_error() -> None:
    raise ValueError(
        "La sección 'sampling' fue eliminada. Migrar al nuevo esquema:\n"
        "  sampling.every_n     → rate_control.stride\n"
        "  sampling.max_units   → run.max_units\n"
        "  sampling.target_fps  → eliminado (la tasa emerge del consumidor)\n"
        "  sampling.mode        → eliminado (reemplazado por rate_control.policy)"
    )


def _derive_defaults(raw: dict[str, Any]) -> None:
    """Materializa defaults de despliegue antes de validar con Pydantic."""
    source = raw.setdefault("source", {})
    if not isinstance(source, dict):
        return

    source_type = str(source.get("type", "image_folder")).lower().strip()
    if source_type not in _SUPPORTED_SOURCE_TYPES:
        migration = (
            " Migrar source.type=camera a rtsp o oak_d."
            if source_type == "camera"
            else ""
        )
        raise ValueError(
            f"source.type={source_type} no está soportado. Valores válidos: "
            f"{', '.join(_SUPPORTED_SOURCE_TYPES)}.{migration}"
        )
    if "kind" not in source:
        if source_type in _PULLEABLE_TYPES:
            source["kind"] = "pulleable"
        elif source_type in _LIVE_TYPES:
            source["kind"] = "live"

    rate_control = raw.setdefault("rate_control", {})
    if not isinstance(rate_control, dict):
        return
    if "policy" not in rate_control:
        rate_control["policy"] = (
            "bounded_freshness" if source.get("kind") == "live" else "deterministic"
        )

    topology = raw.setdefault("topology", {})
    transport = raw.setdefault("transport", {})
    if not isinstance(topology, dict) or not isinstance(transport, dict):
        return
    if "backend" not in transport:
        transport["backend"] = (
            "network" if topology.get("mode", "single_host") == "two_node" else "memory"
        )


def _validate_deployment(config: RunConfig) -> None:
    """Valida coherencia de despliegue y bloquea características declaradas."""
    rate_control = config.rate_control
    rate_fields = rate_control.model_fields_set

    if config.source.kind not in {"pulleable", "live"}:
        raise ValueError("source.kind debe ser 'pulleable' o 'live'.")
    if rate_control.policy not in {"deterministic", "bounded_freshness"}:
        raise ValueError(
            "rate_control.policy debe ser 'deterministic' o 'bounded_freshness'."
        )
    if config.topology.mode not in {"single_host", "two_node"}:
        raise ValueError("topology.mode debe ser 'single_host' o 'two_node'.")
    if config.transport.backend not in {"memory", "network"}:
        raise ValueError("transport.backend debe ser memory o network.")
    if config.transport.payload_format not in {"uint8_rgb", "fp32", "fp16"}:
        raise ValueError("transport.payload_format debe ser uint8_rgb, fp32 o fp16.")

    if rate_control.policy == "bounded_freshness" and rate_fields.intersection(
        {"stride", "max_queue_size", "overflow"}
    ):
        raise ValueError(
            "'stride', 'max_queue_size' y 'overflow' solo aplican a "
            "policy=deterministic. Para bounded_freshness usar 'buffer_size'."
        )
    if rate_control.policy == "deterministic" and rate_fields.intersection(
        {"buffer_size", "max_staleness_ms"}
    ):
        raise ValueError(
            "'buffer_size' y 'max_staleness_ms' solo aplican a "
            "policy=bounded_freshness. Para deterministic usar 'max_queue_size'."
        )

    if config.topology.mode == "two_node" and config.transport.backend != "network":
        raise ValueError("topology.mode=two_node requiere transport.backend=network.")
    if config.topology.mode == "single_host" and config.transport.backend == "network":
        raise ValueError(
            "topology.mode=single_host no permite transport.backend=network. "
            "Usar backend=memory para un solo host."
        )
    if config.transport.endpoint and config.transport.backend != "network":
        raise ValueError("transport.endpoint solo aplica a transport.backend=network.")
    if config.transport.heartbeat_endpoint and config.transport.backend != "network":
        raise ValueError(
            "transport.heartbeat_endpoint solo aplica a transport.backend=network."
        )
    if config.transport.backend == "network" and not config.transport.endpoint:
        raise ValueError("transport.backend=network requiere transport.endpoint.")
    if config.transport.backend == "network" and not config.transport.heartbeat_endpoint:
        raise ValueError(
            "transport.backend=network requiere transport.heartbeat_endpoint."
        )

    if config.source.type.lower() == "oak_d":
        raise NotImplementedError(
            "source.type=oak_d (OAK-D Pro PoE) está declarado pero no implementado."
        )


def load_prompts_file(path: Path) -> PromptsFile:
    """Carga y valida un archivo de prompts YAML."""
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"Archivo de prompts no encontrado: {path}")
    with open(path) as f:
        raw = yaml.safe_load(f)
    return PromptsFile(**raw)


def find_configs_root(config_path: Path) -> Path:
    """Determina el directorio raíz de catálogos (``configs/``) para un config.

    Busca un ancestro llamado ``configs``; si el config vive fuera del árbol
    de configs (p. ej. en tests), usa ``configs/`` junto al archivo o al CWD.
    """
    resolved = Path(config_path).resolve()
    for parent in resolved.parents:
        if parent.name == "configs":
            return parent
    sibling = resolved.parent / "configs"
    if sibling.is_dir():
        return sibling
    return Path.cwd() / "configs"


def _load_catalog_entry(configs_root: Path, catalog: str, ref: str) -> dict[str, Any]:
    """Carga una entrada de catálogo como diccionario crudo."""
    if ".." in Path(ref).parts or Path(ref).is_absolute():
        raise ValueError(
            f"Referencia inválida '{ref}': debe ser un nombre relativo dentro del "
            f"catálogo '{catalog}' (sin '..' ni rutas absolutas)"
        )
    ref_path = configs_root / catalog / f"{ref}.yaml"
    if not ref_path.exists():
        raise FileNotFoundError(
            f"Referencia '{ref}' no encontrada en el catálogo '{catalog}': {ref_path}"
        )
    with open(ref_path) as f:
        data = yaml.safe_load(f) or {}
    if not isinstance(data, dict):
        raise ValueError(f"Entrada de catálogo inválida (se esperaba mapping): {ref_path}")
    return data


def _resolve_section_ref(
    raw: dict[str, Any], section: str, catalog: str, configs_root: Path
) -> None:
    """Expande ``raw[section]['ref']`` mezclando catálogo + overrides inline."""
    section_data = raw.get(section)
    if not isinstance(section_data, dict):
        return
    ref = section_data.get("ref")
    if not ref:
        return
    base = _load_catalog_entry(configs_root, catalog, ref)
    overrides = {k: v for k, v in section_data.items() if k != "ref"}
    raw[section] = {**base, **overrides, "ref": ref}


def load_run_config(config_path: Path) -> RunConfig:
    """Carga una configuración de corrida completa, incluyendo el archivo de prompts."""
    config_path = Path(config_path)
    if not config_path.exists():
        raise FileNotFoundError(f"Archivo de configuración no encontrado: {config_path}")

    with open(config_path) as f:
        raw = yaml.safe_load(f) or {}
    if not isinstance(raw, dict):
        raise ValueError(f"Configuración inválida (se esperaba mapping): {config_path}")
    if "sampling" in raw:
        _raise_sampling_migration_error()

    configs_root = find_configs_root(config_path)
    _resolve_section_ref(raw, "model", "models", configs_root)
    _resolve_section_ref(raw, "source", "datasets", configs_root)
    _derive_defaults(raw)

    # prompts.ref → ruta dentro del catálogo de prompts (file explícito gana)
    prompts_data = raw.get("prompts")
    if isinstance(prompts_data, dict) and prompts_data.get("ref") and not prompts_data.get("file"):
        prompts_data["file"] = str(configs_root / "prompts" / f"{prompts_data['ref']}.yaml")

    config = RunConfig(**raw)
    config.config_path = config_path

    # Resolver ruta del archivo de prompts relativa al config o al CWD
    prompts_path = Path(config.prompts.file)
    if not prompts_path.is_absolute():
        # Intentar relativa al directorio del config primero
        relative_to_config = config_path.parent / prompts_path
        if relative_to_config.exists():
            prompts_path = relative_to_config
        # Si no, usar relativa al CWD

    config.prompts_file = load_prompts_file(prompts_path)
    _validate_deployment(config)

    return config
