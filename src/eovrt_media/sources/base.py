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
        """Devuelve la cantidad total de unidades visuales disponibles.

        Contrato para fuentes vivas (longitud indefinida):
        Las implementaciones de fuentes en vivo (e.g. RtspSource, LiveSource,
        OakDSource) DEBEN hacer ``raise TypeError(...)`` en lugar de retornar
        un número.  Retornar -1 viola el contrato ``__len__ >= 0`` de Python
        (ValueError en CPython 3.9+); retornar ``sys.maxsize`` provoca
        MemoryError en ``list()``.  El ``TypeError`` es la única forma
        compatible con CPython para señalar "sin longitud definida" y aun así
        permitir que ``list(source)`` funcione mediante iteración pura.
        """
