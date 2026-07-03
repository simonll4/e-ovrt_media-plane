"""Carga y validación de configuración del plano de medios.

Las run configs componen secciones por referencia, resueltas contra DOS raíces
(ver ``find_plane_catalog_root`` / ``find_experiment_root`` y el spec
2026-06-27-experimental-setup-config-design §5):

- ``model.ref: <familia>/<variante>`` → ``<catálogo-plano>/models/<...>.yaml``
- ``source.ref: <nombre>``           → ``<catálogo-plano>/datasets/<nombre>.yaml``
- ``prompts.ref: <nombre>``          → ``<raíz-experimento>/prompts/<nombre>.yaml``
  (con fallback al catálogo del plano para configs co-ubicados/generados)

El catálogo del plano se autodescubre repo-relative (override ``--catalog-root`` /
``EOVRT_MEDIA_CATALOG_ROOT``); la raíz del experimento es el dir que contiene
``prompts/`` (p.ej. el repo ``e-ovrt_experimental-setup``). Los campos inline pisan
los del catálogo; el formato inline completo (sin refs) sigue siendo válido.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import TYPE_CHECKING, Any

import yaml

from eovrt_media.config.schemas import PromptsFile, RunConfig

if TYPE_CHECKING:
    from eovrt_media.config.schemas import ModelSection


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


def find_plane_catalog_root(
    config_path: Path | None = None, override: str | Path | None = None
) -> Path:
    """Raíz del catálogo de capacidades del media-plane (``configs/``).

    Orden de resolución:
    1. ``override`` explícito (flag CLI ``--catalog-root``).
    2. variable de entorno ``EOVRT_MEDIA_CATALOG_ROOT``.
    3. un ancestro ``configs`` del propio ``config_path`` (configs co-ubicados:
       los del repo y los árboles temporales de tests).
    4. el ``configs/`` del repo media-plane, relativo al paquete instalado
       (caso del manifiesto externo en ``e-ovrt_experimental-setup``).
    """
    if override is not None:
        return Path(override).resolve()
    env = os.environ.get("EOVRT_MEDIA_CATALOG_ROOT")
    if env:
        return Path(env).resolve()
    if config_path is not None:
        resolved = Path(config_path).resolve()
        for parent in resolved.parents:
            if parent.name == "configs":
                return parent
    # src/eovrt_media/config/loader.py → parents[3] == raíz del repo
    return Path(__file__).resolve().parents[3] / "configs"


def find_experiment_root(manifest_path: Path) -> Path:
    """Raíz del repo de experimentos: ancestro que contiene ``prompts/``.

    Para manifiestos co-ubicados con ``configs/prompts/`` devuelve ese ``configs``;
    para manifiestos en ``e-ovrt_experimental-setup`` devuelve la raíz del repo.
    Si no hay ``prompts/`` en ningún ancestro, cae al directorio del manifiesto.
    """
    resolved = Path(manifest_path).resolve()
    for parent in [resolved.parent, *resolved.parents]:
        if (parent / "prompts").is_dir():
            return parent
    return resolved.parent


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


def resolve_model_ref(ref: str, catalog_root: str | Path | None = None) -> ModelSection:
    """Resuelve un MODEL_REF contra configs/models/ → ModelSection (para el servicio)."""
    from eovrt_media.config.schemas import ModelSection

    plane_root = find_plane_catalog_root(None, catalog_root)
    base = _load_catalog_entry(plane_root, "models", ref)
    return ModelSection(**{**base, "ref": ref})


def load_run_config_data(
    raw: dict[str, Any],
    *,
    plane_root: Path,
    experiment_root: Path | None = None,
    datasets_root: Path | None = None,  # se usa en Task 4
    config_path: Path | None = None,
) -> RunConfig:
    """Valida una run config desde un dict ya parseado (API del servicio o archivo)."""
    if not isinstance(raw, dict):
        raise ValueError("Configuración inválida (se esperaba mapping)")
    if "sampling" in raw:
        _raise_sampling_migration_error()

    _resolve_section_ref(raw, "model", "models", plane_root)
    _resolve_section_ref(raw, "source", "datasets", plane_root)
    _derive_defaults(raw)

    # prompts.ref → ``prompts/<ref>.yaml`` en la raíz del experimento; si ahí no
    # existe (configs co-ubicados/generados del plano), cae al catálogo del plano.
    # ``file`` explícito gana sobre ``ref``.
    prompts_data = raw.get("prompts")
    if (
        isinstance(prompts_data, dict)
        and prompts_data.get("ref")
        and not prompts_data.get("file")
        and not prompts_data.get("set_inline")  # Task 3
    ):
        ref = prompts_data["ref"]
        roots = [experiment_root] if experiment_root is not None else []
        roots.append(plane_root)
        for root in roots:
            candidate = root / "prompts" / f"{ref}.yaml"
            if candidate.exists():
                break
        prompts_data["file"] = str(candidate)

    config = RunConfig(**raw)
    config.config_path = config_path

    # Resolver prompts: precedencia set_inline > file > ref
    if config.prompts.set_inline is not None:
        config.prompts_file = PromptsFile(prompt_set=config.prompts.set_inline)
    elif config.prompts.file:
        prompts_path = Path(config.prompts.file)
        if not prompts_path.is_absolute() and config_path is not None:
            # Intentar relativa al directorio del config primero
            relative_to_config = config_path.parent / prompts_path
            if relative_to_config.exists():
                prompts_path = relative_to_config
            # Si no, usar relativa al CWD
        config.prompts_file = load_prompts_file(prompts_path)

    _validate_deployment(config)
    return config


def load_run_config(
    config_path: Path, catalog_root: str | Path | None = None
) -> RunConfig:
    """Carga una configuración de corrida completa, incluyendo el archivo de prompts.

    Resuelve referencias contra dos raíces: ``model``/``source`` contra el
    catálogo del plano (``find_plane_catalog_root``) y ``prompts`` contra la raíz
    del experimento (``find_experiment_root``, donde vive el manifiesto).
    """
    config_path = Path(config_path)
    if not config_path.exists():
        raise FileNotFoundError(f"Archivo de configuración no encontrado: {config_path}")
    with open(config_path) as f:
        raw = yaml.safe_load(f) or {}
    if not isinstance(raw, dict):
        raise ValueError(f"Configuración inválida (se esperaba mapping): {config_path}")
    return load_run_config_data(
        raw,
        plane_root=find_plane_catalog_root(config_path, catalog_root),
        experiment_root=find_experiment_root(config_path),
        config_path=config_path,
    )
