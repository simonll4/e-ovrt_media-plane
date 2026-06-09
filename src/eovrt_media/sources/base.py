"""Interfaz base para las fuentes de datos visuales."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Iterator

from eovrt_media.contracts import VisualUnit


class BaseSource(ABC):
    """Interfaz común para todas las fuentes de unidades visuales."""

    @abstractmethod
    def __iter__(self) -> Iterator[VisualUnit]:
        """Itera sobre la fuente produciendo instancias de VisualUnit."""

    @abstractmethod
    def __len__(self) -> int:
        """Devuelve la cantidad total de unidades visuales disponibles."""
