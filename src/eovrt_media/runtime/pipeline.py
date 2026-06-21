"""Pipeline principal del plano de medios — orquestación DBE."""

from __future__ import annotations

import logging
from pathlib import Path

from rich.console import Console
from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn, TaskProgressColumn

from eovrt_media.models import create_adapter
from eovrt_media.config import RunConfig
from eovrt_media.contracts import DetectionEvent, MetricSample, ErrorEvent
from eovrt_media.metrics import (
    LatencyTracker,
    get_gpu_memory_allocated_mb,
    get_gpu_memory_peak_mb,
    reset_gpu_peak_memory,
)
from eovrt_media.sources import ImageFolderSource, VideoFileSource, BaseSource
from eovrt_media.preprocessing import load_image
from eovrt_media.postprocessing import DetectionNormalizer
from eovrt_media.sinks import RunArtifactWriter
from eovrt_media.runtime.run_context import RunContext
from eovrt_media.visualize import draw_detections

logger = logging.getLogger(__name__)


def create_source(config: RunConfig) -> BaseSource:
    """Crea una fuente visual según la configuración de corrida."""
    source_type = config.source.type.lower().strip()
    if source_type == "image_folder":
        return ImageFolderSource(
            folder_path=config.source.path,
            extensions=config.source.extensions,
            every_n=config.sampling.every_n,
            max_units=config.sampling.max_units,
        )
    elif source_type in ("video", "video_frame", "video_file"):
        return VideoFileSource(
            video_path=config.source.path,
            every_n=config.sampling.every_n,
            target_fps=config.sampling.target_fps,
            max_units=config.sampling.max_units,
        )
    else:
        raise ValueError(
            f"Tipo de fuente '{source_type}' no soportado. "
            f"Opciones: image_folder, video_file"
        )


def run_pipeline(config: RunConfig, console: Console | None = None) -> str:
    """Ejecuta el pipeline DBE completo de forma lineal y estructurada.

    Args:
        config: Configuración de corrida cargada y validada.
        console: Console de Rich para output formateado (opcional).

    Returns:
        El run_id generado de la corrida.
    """
    if console is None:
        console = Console()

    # 1. Crear contexto de corrida y persistir configs iniciales
    run_context = RunContext(config)
    artifact_writer = RunArtifactWriter(run_context)

    console.print(f"[bold green]▶ Corrida:[/bold green] {run_context.run_id}")
    console.print(f"[dim]  Directorio de salida: {run_context.run_dir}[/dim]")

    # Guardar config original y efectiva
    if config.config_path:
        artifact_writer.write_original_config(config.config_path)
    artifact_writer.write_effective_config()

    # 2. Cargar fuente visual
    source = create_source(config)
    source_count = len(source)
    console.print(f"[dim]  Fuente: {config.source.path} ({source_count} unidades)[/dim]")

    # 3. Obtener prompts activos
    prompt_texts = config.get_prompt_texts()
    prompt_items = config.get_prompt_items()
    prompt_version = config.prompts_file.resolved_version if config.prompts_file else "unknown"
    console.print(f"[dim]  Prompts activos ({prompt_version}): {prompt_texts}[/dim]")

    # 4. Crear normalizador de detecciones
    normalizer = DetectionNormalizer(
        min_confidence=config.postprocess.min_confidence,
        min_box_area_px=config.postprocess.min_box_area_px,
        normalize_boxes=config.postprocess.normalize_boxes,
    )

    # 5. Crear e iniciar adaptador de modelo OVD
    adapter = create_adapter(config.model)
    console.print(f"[dim]  Modelo/Adaptador: {config.model.name or config.model.adapter}[/dim]")
    console.print(f"[dim]  Dispositivo: {config.model.device}[/dim]\n")

    # Reset del pico de VRAM para que refleje solo esta corrida (incluida la carga del modelo)
    reset_gpu_peak_memory()

    with console.status("[bold cyan]Cargando modelo..."):
        adapter.load()
    console.print("[green]✓[/green] Modelo cargado en memoria\n")

    # Tracking de métricas de tiempo
    tracker = LatencyTracker()

    try:
        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            BarColumn(),
            TaskProgressColumn(),
            console=console,
        ) as progress:
            task = progress.add_task("Procesando unidades visuales...", total=source_count)

            for unit in source:
                timer = tracker.start_unit(unit.unit_id)

                # --- 1. LECTURA ---
                timer.start_read()
                try:
                    pil_image = load_image(unit)
                    timer.end_read()
                except Exception as e:
                    logger.error(f"Error leyendo unidad visual {unit.unit_id}: {e}")
                    timer.end_read()
                    
                    err_event = ErrorEvent(
                        run_id=run_context.run_id,
                        unit_id=unit.unit_id,
                        stage="read",
                        message=str(e),
                        recoverable=True,
                    )
                    artifact_writer.write_error(err_event)
                    run_context.units_failed += 1

                    # Métrica de fallo
                    metric = MetricSample(
                        run_id=run_context.run_id,
                        unit_id=unit.unit_id,
                        source_path=unit.source_path,
                        error=str(e),
                    )
                    artifact_writer.write_metric(metric)
                    progress.update(task, advance=1)
                    continue

                # --- 2. PREPROCESAMIENTO ---
                timer.start_preprocess()
                # Los pasos específicos del modelo los maneja el adaptador, aquí medimos la fase común
                timer.end_preprocess()

                # --- 3. INFERENCIA ---
                timer.start_inference()
                try:
                    raw_detections = adapter.predict(pil_image, prompt_texts)
                    timer.end_inference()
                except Exception as e:
                    logger.error(f"Error de inferencia en unidad {unit.unit_id}: {e}")
                    timer.end_inference()
                    
                    err_event = ErrorEvent(
                        run_id=run_context.run_id,
                        unit_id=unit.unit_id,
                        stage="inference",
                        message=str(e),
                        recoverable=True,
                    )
                    artifact_writer.write_error(err_event)
                    run_context.units_failed += 1

                    metric = MetricSample(
                        run_id=run_context.run_id,
                        unit_id=unit.unit_id,
                        source_path=unit.source_path,
                        error=str(e),
                    )
                    artifact_writer.write_metric(metric)
                    progress.update(task, advance=1)
                    continue

                # --- 4. POSTPROCESAMIENTO ---
                timer.start_postprocess()
                try:
                    detections = normalizer.normalize(
                        raw_detections=raw_detections,
                        width=unit.width,
                        height=unit.height,
                        model_name=config.model.name or config.model.adapter,
                        prompt_items=prompt_items,
                    )
                    timer.end_postprocess()
                except Exception as e:
                    logger.error(f"Error de postprocesamiento en unidad {unit.unit_id}: {e}")
                    timer.end_postprocess()
                    
                    err_event = ErrorEvent(
                        run_id=run_context.run_id,
                        unit_id=unit.unit_id,
                        stage="postprocess",
                        message=str(e),
                        recoverable=True,
                    )
                    artifact_writer.write_error(err_event)
                    run_context.units_failed += 1

                    metric = MetricSample(
                        run_id=run_context.run_id,
                        unit_id=unit.unit_id,
                        source_path=unit.source_path,
                        error=str(e),
                    )
                    artifact_writer.write_metric(metric)
                    progress.update(task, advance=1)
                    continue

                # --- 5. ESCRITURA ---
                timer.start_write()
                try:
                    tracker.finish_unit(timer, detection_count=len(detections))
                    granular = timer.get_granular_result()
                    gpu_mem = get_gpu_memory_allocated_mb()

                    # Construir y guardar DetectionEvent
                    event = DetectionEvent(
                        run_id=run_context.run_id,
                        unit_id=unit.unit_id,
                        source={
                            "source_id": unit.source_id or Path(unit.source_path).name,
                            "source_type": unit.source_type,
                            "frame_index": unit.frame_index,
                            "timestamp_ms": unit.timestamp_ms,
                            "width": unit.width,
                            "height": unit.height,
                        },
                        model={
                            "name": config.model.name or config.model.adapter,
                            "model_id": config.model.model_id,
                            "device": config.model.device,
                        },
                        prompts={
                            "prompt_set_id": prompt_version,
                        },
                        detections=detections,
                        timing={
                            "read_ms": granular.read_ms,
                            "preprocess_ms": granular.preprocess_ms,
                            "inference_ms": granular.inference_ms,
                            "postprocess_ms": granular.postprocess_ms,
                            "write_ms": granular.write_ms,
                            "total_ms": granular.total_ms,
                        },
                    )
                    artifact_writer.write_detection(event)

                    # Construir y guardar MetricSample
                    metric = MetricSample(
                        run_id=run_context.run_id,
                        unit_id=unit.unit_id,
                        source_path=unit.source_path,
                        fps_effective=round(1000.0 / granular.total_ms, 2) if granular.total_ms > 0 else 0.0,
                        latency_total_ms=granular.total_ms,
                        latency_inference_ms=granular.inference_ms,
                        detections_count=len(detections),
                        dropped_units=0,
                        device=config.model.device,
                        gpu_memory_allocated_mb=round(gpu_mem, 2),
                    )
                    artifact_writer.write_metric(metric)

                    # Anotaciones de Previews (limitar a preview_max)
                    if config.outputs.save_previews and detections and run_context.units_processed < config.outputs.preview_max:
                        preview_name = Path(unit.source_path).stem
                        if unit.frame_index is not None:
                            preview_name += f"_frame_{unit.frame_index:06d}"
                        preview_name += ".preview.jpg"
                        preview_path = run_context.run_dir / "previews" / preview_name
                        draw_detections(unit.source_path, detections, preview_path)

                    timer.end_write()
                    run_context.units_processed += 1
                    run_context.total_detections += len(detections)
                    run_context.record_detections(detections)

                except Exception as e:
                    logger.error(f"Error escribiendo outputs de unidad {unit.unit_id}: {e}")
                    timer.end_write()
                    
                    err_event = ErrorEvent(
                        run_id=run_context.run_id,
                        unit_id=unit.unit_id,
                        stage="write",
                        message=str(e),
                        recoverable=True,
                    )
                    artifact_writer.write_error(err_event)
                    run_context.units_failed += 1

                progress.update(task, advance=1)

    finally:
        # Cerrar escritor de artefactos (libera archivos JSONL)
        artifact_writer.close()
        # Cerrar/descargar adaptador
        adapter.close()

    # Finalizar contexto y guardar resumen + manifiesto
    run_context.gpu_memory_peak_mb = get_gpu_memory_peak_mb()
    run_context.finish()
    artifact_writer.write_summary(tracker)
    artifact_writer.write_manifest()

    # Imprimir métricas finales por pantalla
    console.print("\n[bold green]✓ Corrida completada[/bold green]")
    console.print(f"  Procesadas: {run_context.units_processed}/{source_count}")
    if run_context.units_failed > 0:
        console.print(f"  [red]Fallos/Errores: {run_context.units_failed}[/red]")
    console.print(f"  Detecciones totales: {run_context.total_detections}")
    if run_context.detections_by_label:
        by_label = ", ".join(
            f"{label}: {count}"
            for label, count in sorted(
                run_context.detections_by_label.items(), key=lambda kv: -kv[1]
            )
        )
        console.print(f"  Detecciones por label: {by_label}")
    console.print(f"  Latencia promedio: {tracker.avg_latency_ms():.1f} ms")
    console.print(f"  Latencia p95: {tracker.p95_latency_ms():.1f} ms")
    if run_context.gpu_memory_peak_mb > 0:
        console.print(f"  VRAM pico: {run_context.gpu_memory_peak_mb:.0f} MB")
    console.print(f"\n  [dim]Resultados guardados en: {run_context.run_dir}[/dim]\n")

    return run_context.run_id
