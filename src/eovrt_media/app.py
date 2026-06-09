"""API programática para el plano de medios E-OVRT."""

from __future__ import annotations

from pathlib import Path
from rich.console import Console

from eovrt_media.config import load_run_config
from eovrt_media.runtime import run_pipeline


def run_media_plane(config_path: str | Path, console: Console | None = None) -> str:
    """Ejecuta el plano de medios pasándole una ruta de configuración.

    Args:
        config_path: Ruta al archivo YAML de configuración de corrida.
        console: Instancia de Console de Rich (opcional).

    Returns:
        El run_id de la corrida generada.
    """
    config = load_run_config(Path(config_path))
    return run_pipeline(config, console=console)


def validate_media_plane_config(config_path: str | Path) -> bool:
    """Carga y valida un archivo de configuración sin ejecutar el pipeline.

    Retorna True si es válido, o levanta una excepción de validación de Pydantic
    o FileNotFoundError en caso de error.
    """
    try:
        load_run_config(Path(config_path))
        return True
    except Exception:
        raise
