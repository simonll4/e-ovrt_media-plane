"""Factory de TransportAdapter según configuración."""

from __future__ import annotations

from eovrt_media.transport.base import TransportAdapter
from eovrt_media.transport.memory import MemoryTransportAdapter
from eovrt_media.transport.declared import IpcTransportAdapter, NetworkTransportAdapter


def create_transport(
    *,
    backend: str = "memory",
    policy: str = "deterministic",
    max_queue_size: int = 8,
    buffer_size: int = 2,
    max_staleness_ms: float | None = None,
    endpoint: str | None = None,
) -> TransportAdapter:
    if backend == "memory":
        return MemoryTransportAdapter(
            policy=policy,
            max_queue_size=max_queue_size,
            buffer_size=buffer_size,
            max_staleness_ms=max_staleness_ms,
        )
    if backend == "ipc":
        return IpcTransportAdapter()
    if backend == "network":
        if not endpoint:
            raise ValueError("backend=network requiere transport.endpoint configurado.")
        return NetworkTransportAdapter(endpoint=endpoint)
    raise ValueError(f"backend desconocido: {backend!r}. Opciones: memory, ipc, network.")
