"""Pipeline del plano de medios con productor/consumidor desacoplados."""

from __future__ import annotations

import logging
import queue
import threading
import time

from rich.console import Console
from rich.progress import BarColumn, Progress, SpinnerColumn, TaskProgressColumn, TextColumn

from eovrt_media.config import RunConfig
from eovrt_media.contracts import DetectionEvent, ErrorEvent, MetricSample
from eovrt_media.contracts.normalized_unit import END, PayloadFormat
from eovrt_media.metrics import (
    LatencyTracker,
    get_gpu_memory_allocated_mb,
    get_gpu_memory_peak_mb,
    reset_gpu_peak_memory,
)
from eovrt_media.models import create_adapter
from eovrt_media.postprocessing import DetectionNormalizer
from eovrt_media.preprocessing import normalize_spatial
from eovrt_media.runtime.run_context import RunContext
from eovrt_media.sinks import RunArtifactWriter
from eovrt_media.sources import BaseSource, ImageFolderSource, VideoFileSource
from eovrt_media.transport import RateGate, create_transport
from eovrt_media.visualize import draw_detections

logger = logging.getLogger(__name__)


def create_source(config: RunConfig) -> BaseSource:
    """Crea una fuente; RateGate aplica el stride después de la ingesta."""
    source_type = config.source.type.lower().strip()
    if source_type == "image_folder":
        return ImageFolderSource(
            folder_path=config.source.path,
            extensions=config.source.extensions,
            every_n=1,
            max_units=config.run.max_units,
        )
    if source_type in {"video", "video_frame", "video_file"}:
        return VideoFileSource(
            video_path=config.source.path,
            every_n=1,
            target_fps=None,
            max_units=config.run.max_units,
        )
    if source_type == "rtsp":
        from eovrt_media.sources import RtspSource

        return RtspSource(
            url=config.source.url or config.source.path,
            reconnect_retries=config.source.reconnect_retries,
            reconnect_delay_ms=config.source.reconnect_delay_ms,
            max_units=config.run.max_units,
        )
    if source_type == "oak_d":
        from eovrt_media.sources import OakDSource

        return OakDSource(
            url=config.source.url or config.source.path,
            max_units=config.run.max_units,
        )
    raise ValueError(
        f"Tipo de fuente '{source_type}' no soportado o no implementado. "
        "Usar image_folder, video_file, rtsp u oak_d."
    )


def _producer_thread(
    source: BaseSource,
    rate_gate: RateGate,
    spec,
    payload_format: PayloadFormat,
    transport,
    run_id: str,
    errors_queue: queue.SimpleQueue,
    timings: dict[str, float],
) -> None:
    """Ingesta, filtra, normaliza y ofrece unidades al canal."""
    try:
        for source_index, unit in enumerate(source):
            if not rate_gate.should_pass(source_index):
                continue
            try:
                normalize_started = time.perf_counter()
                normalized = normalize_spatial(unit, spec, payload_format)
                normalized.run_id = run_id
                timings[normalized.unit_id] = (time.perf_counter() - normalize_started) * 1000.0

                offer_started = time.perf_counter()
                transport.offer(normalized)
                timings["backpressure_wait_ms"] = timings.get("backpressure_wait_ms", 0.0) + (
                    (time.perf_counter() - offer_started) * 1000.0
                )
            except Exception as exc:
                errors_queue.put(("normalize", unit.unit_id, str(exc)))
    except Exception as exc:
        errors_queue.put(("source", None, str(exc)))
    finally:
        transport.close()


def _drain_producer_errors(
    errors_queue: queue.SimpleQueue,
    artifact_writer: RunArtifactWriter,
    run_context: RunContext,
) -> int:
    """Persiste errores del productor sin detener el consumidor."""
    count = 0
    while True:
        try:
            stage, unit_id, message = errors_queue.get_nowait()
        except queue.Empty:
            return count
        artifact_writer.write_error(
            ErrorEvent(
                run_id=run_context.run_id,
                unit_id=unit_id or "unknown",
                stage=stage,
                message=message,
                recoverable=True,
            )
        )
        run_context.units_failed += 1
        count += 1


def run_pipeline(config: RunConfig, console: Console | None = None) -> str:
    """Ejecuta una corrida mediante un productor y un consumidor en memoria."""
    console = console or Console()
    run_context = RunContext(config)
    artifact_writer = RunArtifactWriter(run_context)
    tracker = LatencyTracker()
    adapter = None
    producer = None

    console.print(f"[bold green]▶ Corrida:[/bold green] {run_context.run_id}")
    console.print(f"[dim]  Directorio de salida: {run_context.run_dir}[/dim]")

    try:
        if config.config_path:
            artifact_writer.write_original_config(config.config_path)
        artifact_writer.write_effective_config()

        source = create_source(config)
        try:
            source_count = len(source)
            progress_total: int | None = source_count if source_count >= 0 else None
        except TypeError:
            source_count = -1
            progress_total = None
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
        with console.status("[bold cyan]Cargando modelo..."):
            adapter.load()

        rate_control = config.rate_control
        transport = create_transport(
            backend=config.transport.backend,
            policy=rate_control.policy,
            max_queue_size=rate_control.max_queue_size,
            buffer_size=rate_control.buffer_size,
            max_staleness_ms=rate_control.max_staleness_ms,
            endpoint=config.transport.endpoint,
        )
        timings: dict[str, float] = {"backpressure_wait_ms": 0.0}
        producer = threading.Thread(
            target=_producer_thread,
            args=(
                source,
                RateGate(stride=rate_control.stride),
                adapter.input_spec,
                PayloadFormat(config.transport.payload_format),
                transport,
                run_context.run_id,
                run_context._errors_queue,
                timings,
            ),
            daemon=True,
            name="pipeline-producer",
        )
        producer.start()

        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            BarColumn(),
            TaskProgressColumn(),
            console=console,
        ) as progress:
            task = progress.add_task("Procesando unidades visuales...", total=progress_total)
            while True:
                item = transport.request()
                producer_errors = _drain_producer_errors(
                    run_context._errors_queue, artifact_writer, run_context
                )
                if producer_errors:
                    progress.update(task, advance=producer_errors)
                if item is END:
                    break

                timer = tracker.start_unit(item.unit_id)
                timer.record_normalize_ms(timings.get(item.unit_id, 0.0))
                timer.start_inference()
                try:
                    raw_detections = adapter.forward(item, prompt_texts)
                except Exception as exc:
                    timer.end_inference()
                    tracker.finish_unit(timer, error=str(exc))
                    artifact_writer.write_error(
                        ErrorEvent(
                            run_id=run_context.run_id,
                            unit_id=item.unit_id,
                            stage="inference",
                            message=str(exc),
                            recoverable=True,
                        )
                    )
                    run_context.units_failed += 1
                    progress.update(task, advance=1)
                    continue
                timer.end_inference()

                timer.start_postprocess()
                try:
                    detections = normalizer.normalize(
                        raw_detections=raw_detections,
                        width=item.orig_width,
                        height=item.orig_height,
                        model_name=config.model.name or config.model.adapter or "unknown",
                        prompt_items=prompt_items,
                        transform=item.transform,
                    )
                except Exception as exc:
                    timer.end_postprocess()
                    tracker.finish_unit(timer, error=str(exc))
                    artifact_writer.write_error(
                        ErrorEvent(
                            run_id=run_context.run_id,
                            unit_id=item.unit_id,
                            stage="postprocess",
                            message=str(exc),
                            recoverable=True,
                        )
                    )
                    run_context.units_failed += 1
                    progress.update(task, advance=1)
                    continue
                timer.end_postprocess()

                timer.start_write()
                try:
                    granular = timer.get_granular_result()
                    source_type = "video_frame" if item.frame_index is not None else "image"
                    artifact_writer.write_detection(
                        DetectionEvent(
                            run_id=run_context.run_id,
                            unit_id=item.unit_id,
                            source={
                                "source_id": item.source_id or item.unit_id,
                                "source_type": source_type,
                                "frame_index": item.frame_index,
                                "timestamp_ms": item.timestamp_ms,
                                "width": item.orig_width,
                                "height": item.orig_height,
                            },
                            model={
                                "name": config.model.name or config.model.adapter or "unknown",
                                "model_id": config.model.model_id,
                                "device": config.model.device,
                            },
                            prompts={"prompt_set_id": prompt_version},
                            detections=detections,
                            timing={
                                "preprocess_ms": granular.normalize_ms,
                                "inference_ms": granular.inference_ms,
                                "postprocess_ms": granular.postprocess_ms,
                                "write_ms": granular.write_ms,
                                "total_ms": granular.total_ms,
                            },
                            source_path=item.source_id,
                        )
                    )
                    if (
                        config.outputs.save_previews
                        and detections
                        and item.source_path
                        and item.frame_index is None
                        and run_context.units_processed < config.outputs.preview_max
                    ):
                        preview_path = (
                            run_context.run_dir / "previews" / f"{item.unit_id}.preview.jpg"
                        )
                        draw_detections(item.source_path, detections, preview_path)
                    artifact_writer.write_metric(
                        MetricSample(
                            run_id=run_context.run_id,
                            unit_id=item.unit_id,
                            source_path=item.source_id,
                            fps_effective=(
                                round(1000.0 / granular.total_ms, 2)
                                if granular.total_ms > 0
                                else 0.0
                            ),
                            latency_total_ms=granular.total_ms,
                            latency_inference_ms=granular.inference_ms,
                            latency_normalize_ms=granular.normalize_ms,
                            detections_count=len(detections),
                            device=config.model.device,
                            gpu_memory_allocated_mb=round(get_gpu_memory_allocated_mb(), 2),
                        )
                    )
                    timer.end_write()
                    tracker.finish_unit(timer, detection_count=len(detections))
                    run_context.units_processed += 1
                    run_context.total_detections += len(detections)
                    run_context.record_detections(detections)
                except Exception as exc:
                    timer.end_write()
                    tracker.finish_unit(timer, error=str(exc))
                    artifact_writer.write_error(
                        ErrorEvent(
                            run_id=run_context.run_id,
                            unit_id=item.unit_id,
                            stage="write",
                            message=str(exc),
                            recoverable=True,
                        )
                    )
                    run_context.units_failed += 1
                progress.update(task, advance=1)

        _drain_producer_errors(run_context._errors_queue, artifact_writer, run_context)
        run_context.units_dropped = getattr(transport, "units_dropped", 0)
        run_context.backpressure_wait_ms = timings["backpressure_wait_ms"]
    finally:
        if producer is not None:
            producer.join(timeout=30.0)
        if adapter is not None:
            adapter.close()
        artifact_writer.close()

    run_context.gpu_memory_peak_mb = get_gpu_memory_peak_mb()
    run_context.finish()
    artifact_writer.write_summary(tracker)
    artifact_writer.write_provenance()
    artifact_writer.write_manifest()
    return run_context.run_id
