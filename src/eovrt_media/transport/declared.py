"""Backends de transporte declarados, pendientes de implementación."""

from __future__ import annotations

from eovrt_media.contracts.normalized_unit import NormalizedUnit, END
from eovrt_media.transport.base import TransportAdapter


class IpcTransportAdapter(TransportAdapter):
    """Backend IPC (shared-memory ring buffer) — declarado, no implementado."""

    def offer(self, unit: NormalizedUnit) -> None:
        raise NotImplementedError(
            "backend=ipc está declarado pero no implementado. "
            "Usar backend=memory para un host o implementar IpcTransportAdapter."
        )

    def request(self, **kwargs) -> NormalizedUnit | type[END]:
        raise NotImplementedError(
            "backend=ipc está declarado pero no implementado."
        )

    def close(self) -> None:
        raise NotImplementedError("backend=ipc no implementado.")
