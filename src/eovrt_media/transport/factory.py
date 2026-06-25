"""Factory de TransportAdapter según configuración."""

from __future__ import annotations

from eovrt_media.transport.base import TransportAdapter
from eovrt_media.transport.memory import MemoryTransportAdapter
from eovrt_media.transport.network import NetworkTransportAdapter


def create_transport(
    *,
    backend: str = "memory",
    policy: str = "deterministic",
    max_queue_size: int = 8,
    buffer_size: int = 2,
    max_staleness_ms: float | None = None,
    endpoint: str | None = None,
    heartbeat_endpoint: str | None = None,
    **kwargs,
) -> TransportAdapter:
    if backend == "memory":
        return MemoryTransportAdapter(
            policy=policy,
            max_queue_size=max_queue_size,
            buffer_size=buffer_size,
            max_staleness_ms=max_staleness_ms,
        )
    if backend == "network":
        if not endpoint:
            raise ValueError("backend=network requiere transport.endpoint configurado.")
        if not heartbeat_endpoint:
            raise ValueError("backend=network requiere transport.heartbeat_endpoint configurado.")
        return NetworkTransportAdapter(
            role=kwargs.get("role", "consumer"),
            endpoint=endpoint,
            heartbeat_endpoint=heartbeat_endpoint,
            policy=policy,
            buffer_size=buffer_size,
            max_staleness_ms=max_staleness_ms,
            heartbeat_interval_ms=kwargs.get("heartbeat_interval_ms", 1000),
            heartbeat_timeout_ms=kwargs.get("heartbeat_timeout_ms", 5000),
            codec=kwargs.get("codec", "raw"),
            quality=kwargs.get("quality", 90),
        )
    raise ValueError(f"backend desconocido: {backend!r}. Opciones: memory, network.")
