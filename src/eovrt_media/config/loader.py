"""Carga y validación de configuración del plano de medios."""

from __future__ import annotations

from pathlib import Path
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


def load_run_config(config_path: Path) -> RunConfig:
    """Carga una configuración de corrida completa, incluyendo el archivo de prompts."""
    config_path = Path(config_path)
    if not config_path.exists():
        raise FileNotFoundError(f"Archivo de configuración no encontrado: {config_path}")

    with open(config_path) as f:
        raw = yaml.safe_load(f)

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
