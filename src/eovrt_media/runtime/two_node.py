"""Orquestación de los dos nodos para topología distribuida."""
from __future__ import annotations

import queue

from rich.console import Console

from eovrt_media.config import RunConfig
from eovrt_media.contracts.normalized_unit import PayloadFormat
from eovrt_media.metrics import LatencyTracker, get_gpu_memory_peak_mb, reset_gpu_peak_memory
from eovrt_media.models import create_adapter
from eovrt_media.postprocessing import DetectionNormalizer
from eovrt_media.runtime.pipeline import create_source, run_consumer_loop, run_producer_loop
from eovrt_media.runtime.run_context import RunContext
from eovrt_media.sinks import RunArtifactWriter
from eovrt_media.transport import RateGate, create_transport


def run_node_a(config: RunConfig, console: Console | None = None) -> None:
    """Nodo A: ingesta + rate control + normalización + servidor de red."""
    _ = console or Console()
    source = create_source(config)
    adapter = create_adapter(config.model)
    rate_control = config.rate_control
    transport = create_transport(
        backend="network",
        role="producer",
        policy=rate_control.policy,
        buffer_size=rate_control.buffer_size,
        max_staleness_ms=rate_control.max_staleness_ms,
        endpoint=config.transport.endpoint,
        heartbeat_interval_ms=config.transport.heartbeat_interval_ms,
        heartbeat_timeout_ms=config.transport.heartbeat_timeout_ms,
        codec=config.transport.compression.codec,
        quality=config.transport.compression.quality,
    )
    errors_queue: queue.SimpleQueue = queue.SimpleQueue()
    timings: dict[str, float] = {"backpressure_wait_ms": 0.0}
    try:
        run_producer_loop(
            source,
            RateGate(stride=rate_control.stride),
            adapter.input_spec,
            PayloadFormat(config.transport.payload_format),
            transport,
            run_id="",
            errors_queue=errors_queue,
            timings=timings,
        )
        transport.wait_for_consumer()
    finally:
        transport.shutdown()


def run_node_b(config: RunConfig, console: Console | None = None) -> str:
    """Nodo B: cliente de red + inferencia + postproceso + artefactos."""
    _ = console or Console()
    run_context = RunContext(config)
    artifact_writer = RunArtifactWriter(run_context)
    tracker = LatencyTracker()
    artifact_writer.write_effective_config()

    prompt_texts = config.get_prompt_texts()
    prompt_items = config.get_prompt_items()
    prompt_version = config.prompts_file.resolved_version if config.prompts_file else "unknown"

    normalizer = DetectionNormalizer(
        min_confidence=config.postprocess.min_confidence,
        min_box_area_px=config.postprocess.min_box_area_px,
        normalize_boxes=config.postprocess.normalize_boxes,
    )
    adapter = create_adapter(config.model)
    reset_gpu_peak_memory()
    adapter.load()

    transport = create_transport(
        backend="network",
        role="consumer",
        endpoint=config.transport.endpoint,
        heartbeat_interval_ms=config.transport.heartbeat_interval_ms,
        heartbeat_timeout_ms=config.transport.heartbeat_timeout_ms,
    )
    try:
        run_consumer_loop(
            transport,
            adapter,
            normalizer,
            artifact_writer,
            run_context,
            tracker,
            config,
            prompt_texts,
            prompt_items,
            prompt_version,
            timings={},
            progress=None,
            task=None,
            drain_errors=False,
        )
    finally:
        transport.shutdown()
        adapter.close()
        artifact_writer.close()

    run_context.gpu_memory_peak_mb = get_gpu_memory_peak_mb()
    run_context.finish()
    artifact_writer.write_summary(tracker)
    artifact_writer.write_provenance()
    artifact_writer.write_manifest()
    return run_context.run_id
