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

from eovrt_media.config.schemas import RunConfig, PromptsFile


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
        raw = yaml.safe_load(f)

    configs_root = find_configs_root(config_path)
    _resolve_section_ref(raw, "model", "models", configs_root)
    _resolve_section_ref(raw, "source", "datasets", configs_root)

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

    return config
