"""Interfaz abstracta del canal productor→consumidor."""

from __future__ import annotations
from abc import ABC, abstractmethod
from eovrt_media.contracts.normalized_unit import NormalizedUnit, END


class TransportAdapter(ABC):
    @abstractmethod
    def offer(self, unit: NormalizedUnit) -> None:
        """Coloca una unidad en el canal (productor). Política definida por subclase."""

    @abstractmethod
    def request(self, **kwargs) -> NormalizedUnit | type[END]:
        """Obtiene la siguiente unidad del canal (consumidor). Bloquea si vacío."""

    @abstractmethod
    def close(self) -> None:
        """Señal END: el productor terminó. Coloca centinela en el canal."""
