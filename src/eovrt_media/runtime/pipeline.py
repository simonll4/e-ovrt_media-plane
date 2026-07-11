"""Pipeline del plano de medios con productor/consumidor desacoplados."""

from __future__ import annotations

import logging
import queue
import threading
import time
from collections.abc import Callable

from rich.console import Console
from rich.progress import BarColumn, Progress, SpinnerColumn, TaskProgressColumn, TextColumn

from eovrt_media.config import RunConfig
from eovrt_media.contracts import DetectionEvent, ErrorEvent, MetricSample
from eovrt_media.contracts.normalized_unit import END, STALL, PayloadFormat
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
from eovrt_media.sinks.video_annotation_writer import VideoAnnotationWriter
from eovrt_media.sources import BaseSource
from eovrt_media.sources.registry import create_source  # noqa: F401  (API pública estable)
from eovrt_media.transport import RateGate, create_transport
from eovrt_media.visualize import draw_detections_rgb

logger = logging.getLogger(__name__)

STOP_DRAIN_SECONDS = 2.0
"""Ventana de drenaje tras `RunControl.request_stop()` antes de forzar la
salida del consumer si el transporte no entrega ni una unidad ni `END`.

Cubre el caso de una fuente que ignora `stop()` (p.ej. un RTSP colgado en un
`recv` a nivel C): el productor nunca cierra el transporte, así que sin este
límite el consumer (y por lo tanto `execute_run`) quedaría bloqueado para
siempre en `transport.request()`.
"""

_STOP_POLL_INTERVAL_S = 0.2
"""Granularidad de sondeo del consumer cuando hay un `RunControl` asociado.

Se usa desde el arranque del loop (no sólo tras pedir el stop) para que el
consumer nunca quede atrapado dentro de una única llamada bloqueante a
`transport.request()`: sin este sondeo periódico, un stop pedido mientras el
consumer está a mitad de una espera indefinida no podría detectarse hasta
que llegara una unidad o el canal cerrara — exactamente el escenario que
este mecanismo previene.
"""

PRODUCER_JOIN_TIMEOUT_AFTER_STALL_S = 2.0
"""Timeout de `producer.join()` cuando el consumer forzó su salida por stall.

Si el consumer tuvo que tratar la ventana de drenaje agotada como `END`, es
porque el productor probablemente sigue bloqueado en la fuente (que ignoró
`stop()`) y jamás va a unirse. Esperar los 30s genéricos no aporta nada en
ese caso; el hilo productor queda como daemon-leak acotado (uno por
stop-con-fuente-colgada) que muere al terminar el proceso.
"""


def run_producer_loop(
    source: BaseSource,
    rate_gate: RateGate,
    spec,
    payload_format: PayloadFormat,
    transport,
    run_id: str,
    errors_queue: queue.SimpleQueue,
    timings: dict[str, float],
    should_continue: Callable[[], bool] | None = None,
) -> None:
    """Ingesta, filtra, normaliza y ofrece unidades al canal."""
    try:
        for source_index, unit in enumerate(source):
            if not rate_gate.should_pass(source_index):
                continue
            if should_continue is not None and not should_continue():
                logger.warning("Productor detenido por pérdida de liveness del consumidor.")
                break
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


def run_consumer_loop(
    transport,
    adapter,
    normalizer,
    artifact_writer,
    run_context,
    tracker,
    config,
    plan,
    prompt_set_id,
    timings: dict[str, float],
    progress=None,
    task=None,
    drain_errors: bool = True,
    control: "RunControl | None" = None,
) -> bool:
    """Consume del transporte hasta END: inferencia → postproceso → escritura.

    Si se pasa `control`, el loop sondea el transporte con timeout corto (en
    vez de bloquear indefinidamente en una sola llamada) para poder
    re-chequear `control.stop_requested` en cualquier momento — incluso si la
    llamada anterior a `transport.request()` seguía "en vuelo" cuando se pidió
    el stop. Una vez pedido el stop se abre una ventana de drenaje acotada
    (`STOP_DRAIN_SECONDS`); si vence sin que el transporte entregue unidad ni
    `END` (productor colgado en una fuente que ignora `stop()`), se trata como
    `END` para no bloquear a `execute_run` para siempre.

    Retorna `True` si el loop tuvo que forzar esa salida por stall (útil para
    que el caller acote el timeout de `producer.join()`, ya que ese productor
    probablemente nunca se va a unir). Retorna `False` en toda otra
    terminación (END real, con o sin stop pedido).

    Sin `control` (por ejemplo, la ruta two-node vía `run_node_b`), el
    comportamiento es IDÉNTICO al histórico: una única llamada bloqueante a
    `transport.request()` por iteración.
    """
    preview_attempts = 0
    video_writer = (
        VideoAnnotationWriter(
            run_context.run_dir / "annotated.mp4",
            fps_override=config.outputs.video_fps,
        )
        if config.outputs.save_annotated_video
        else None
    )
    stalled = False
    drain_deadline: float | None = None
    while True:
        if control is not None:
            item = transport.request(timeout=_STOP_POLL_INTERVAL_S)
            if item is STALL:
                if not control.stop_requested:
                    continue  # aún no se pidió stop: seguir esperando en silencio
                if drain_deadline is None:
                    drain_deadline = time.monotonic() + STOP_DRAIN_SECONDS
                if time.monotonic() < drain_deadline:
                    continue  # dentro de la ventana de drenaje: reintentar
                logger.warning(
                    "Consumer: ventana de drenaje agotada tras request_stop() sin "
                    "END del productor — se fuerza la salida (posible fuente colgada)."
                )
                item = END
                stalled = True
        else:
            item = transport.request()
        if drain_errors:
            producer_errors = _drain_producer_errors(
                run_context._errors_queue, artifact_writer, run_context
            )
            if producer_errors and progress is not None and task is not None:
                progress.update(task, advance=producer_errors)
        if item is END:
            if video_writer is not None:
                video_writer.close()
            break

        timer = tracker.start_unit(item.unit_id)
        timer.record_normalize_ms(timings.get(item.unit_id, 0.0))
        timer.start_inference()
        try:
            raw_detections = adapter.forward(item, plan)
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
            if progress is not None and task is not None:
                progress.update(task, advance=1)
            continue
        timer.end_inference()

        # G2A = captura -> resultado algoritmico disponible (spec 40 SS5.1). Se cierra
        # aca, antes del postproceso: la descomposicion de spec 42 SS5 es
        # t_capture + t_transport + t_preprocess + t_inference. Mismo reloj monotonico
        # que estampo la captura.
        g2a_ms = (time.monotonic_ns() - item.capture_monotonic_ns) / 1_000_000.0

        # En topologia two_node la captura la estampa el Nodo A y el G2A se
        # cierra en el Nodo B: `time.monotonic_ns()` es del sistema, con
        # origen arbitrario por host, asi que la resta entre dos maquinas no
        # significa nada (spec 40 SS4). No se acumula ni se publica un
        # g2a_ms fabricado: la fila trae `null` y el consumidor aguas abajo
        # (que joinea por unit_id) no puede confundirlo con un valor real.
        if config.topology.mode == "two_node":
            g2a_ms_for_metric = None
        else:
            run_context.g2a.add(g2a_ms)
            g2a_ms_for_metric = round(g2a_ms, 3)
        run_context.source_clock = item.source_clock

        if (
            config.outputs.save_previews
            and preview_attempts < config.outputs.preview_max
        ):
            preview_path = run_context.run_dir / "previews" / f"{item.unit_id}.preview.jpg"
            preview_attempts += 1
            try:
                draw_detections_rgb(item.payload, raw_detections, preview_path)
            except Exception as exc:
                artifact_writer.write_error(
                    ErrorEvent(
                        run_id=run_context.run_id,
                        unit_id=item.unit_id,
                        stage="preview",
                        message=str(exc),
                        recoverable=True,
                    )
                )

        if video_writer is not None:
            try:
                video_writer.add(item.payload, raw_detections, item.timestamp_ms)
            except Exception as exc:
                artifact_writer.write_error(
                    ErrorEvent(
                        run_id=run_context.run_id,
                        unit_id=item.unit_id,
                        stage="annotated_video",
                        message=str(exc),
                        recoverable=True,
                    )
                )

        timer.start_postprocess()
        try:
            detections = normalizer.normalize(
                raw_detections=raw_detections,
                width=item.orig_width,
                height=item.orig_height,
                model_name=config.model.name or config.model.adapter or "unknown",
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
            if progress is not None and task is not None:
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
                    prompts={"prompt_set_id": prompt_set_id},
                    detections=detections,
                    timing={
                        "normalize_ms": granular.normalize_ms,
                        "inference_ms": granular.inference_ms,
                        "postprocess_ms": granular.postprocess_ms,
                        "write_ms": granular.write_ms,
                        "total_ms": granular.total_ms,
                    },
                )
            )
            artifact_writer.write_metric(
                MetricSample(
                    run_id=run_context.run_id,
                    unit_id=item.unit_id,
                    source_path=item.source_id,
                    capture_monotonic_ns=item.capture_monotonic_ns,
                    capture_wallclock_ms=item.capture_wallclock_ms,
                    g2a_ms=g2a_ms_for_metric,
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
        if progress is not None and task is not None:
            progress.update(task, advance=1)

    return stalled


class RunControl:
    """Control de vida de un run: stop cooperativo desde otro thread."""

    def __init__(self) -> None:
        self._stop = threading.Event()
        self._source: BaseSource | None = None

    def bind_source(self, source: BaseSource) -> None:
        self._source = source

    def request_stop(self) -> None:
        self._stop.set()
        if self._source is not None:
            self._source.stop()  # destraba fuentes live bloqueadas en captura

    @property
    def stop_requested(self) -> bool:
        return self._stop.is_set()


def execute_run(
    config: RunConfig,
    adapter,
    *,
    console: Console | None = None,
    control: RunControl | None = None,
    event_sink=None,
) -> str:
    """Ejecuta un run con un adapter YA CARGADO (no lo crea, no lo cierra).

    Camino del servicio (Spec A §6): el modelo vive a nivel proceso; stop vía
    RunControl; telemetría opcional por event_sink (decorando el writer).
    """
    run_context = RunContext(config)
    artifact_writer = RunArtifactWriter(run_context)
    if event_sink is not None:
        from eovrt_media.service.events import EventEmittingArtifactWriter

        artifact_writer = EventEmittingArtifactWriter(artifact_writer, event_sink)

    bus_publisher = None
    if config.bus.enabled:
        from eovrt_media.service.bus_writer import BusPublishingArtifactWriter
        from eovrt_media.transport.bus import BusPublisher

        try:
            bus_publisher = BusPublisher(
                config.bus.endpoint,
                hwm=config.bus.hwm,
                wait_for_subscriber_ms=config.bus.wait_for_subscriber_ms,
            )
            artifact_writer = BusPublishingArtifactWriter(
                artifact_writer, bus_publisher, run_context.run_id
            )
        except Exception:  # noqa: BLE001 — el bus nunca rompe la corrida
            logger.warning(
                "bus: no se pudo levantar el publicador (endpoint=%s); "
                "la corrida continua sin bus, el JSONL es la verdad",
                config.bus.endpoint,
                exc_info=True,
            )
            if bus_publisher is not None:
                bus_publisher.close()
            bus_publisher = None

    tracker = LatencyTracker()
    producer = None
    consumer_stalled = False
    bus_status = "succeeded"

    if console is not None:
        console.print(f"[bold green]▶ Corrida:[/bold green] {run_context.run_id}")
        console.print(f"[dim]  Directorio de salida: {run_context.run_dir}[/dim]")

    try:
        try:
            if config.config_path:
                artifact_writer.write_original_config(config.config_path)
            artifact_writer.write_effective_config()

            source = create_source(config)
            run_context.source_clock = getattr(source, "SOURCE_CLOCK", "none")
            if control is not None:
                control.bind_source(source)
            try:
                source_count = len(source)
                progress_total: int | None = source_count if source_count >= 0 else None
            except TypeError:
                progress_total = None
            normalizer = DetectionNormalizer(
                min_confidence=config.postprocess.min_confidence,
                min_box_area_px=config.postprocess.min_box_area_px,
                normalize_boxes=config.postprocess.normalize_boxes,
            )
            plan = config.build_prompt_plan(adapter.PROMPT_BACKEND)
            prompt_set_id = (
                config.prompts_file.resolved_set_id() if config.prompts_file else "unknown"
            )
            reset_gpu_peak_memory()

            rate_control = config.rate_control
            transport = create_transport(
                backend=config.transport.backend,
                policy=rate_control.policy,
                max_queue_size=rate_control.max_queue_size,
                buffer_size=rate_control.buffer_size,
                max_staleness_ms=rate_control.max_staleness_ms,
                endpoint=config.transport.endpoint,
            )
            should_continue = (
                (lambda: not control.stop_requested) if control is not None else None
            )
            timings: dict[str, float] = {"backpressure_wait_ms": 0.0}
            producer = threading.Thread(
                target=run_producer_loop,
                args=(
                    source,
                    RateGate(stride=rate_control.stride),
                    adapter.input_spec,
                    PayloadFormat(config.transport.payload_format),
                    transport,
                    run_context.run_id,
                    run_context._errors_queue,
                    timings,
                    should_continue,
                ),
                daemon=True,
                name="pipeline-producer",
            )
            producer.start()

            def _consume(progress=None, task=None) -> None:
                nonlocal consumer_stalled
                consumer_stalled = run_consumer_loop(
                    transport=transport,
                    adapter=adapter,
                    normalizer=normalizer,
                    artifact_writer=artifact_writer,
                    run_context=run_context,
                    tracker=tracker,
                    config=config,
                    plan=plan,
                    prompt_set_id=prompt_set_id,
                    timings=timings,
                    progress=progress,
                    task=task,
                    drain_errors=True,
                    control=control,
                )

            try:
                if console is not None:
                    with Progress(
                        SpinnerColumn(),
                        TextColumn("[progress.description]{task.description}"),
                        BarColumn(),
                        TaskProgressColumn(),
                        console=console,
                    ) as progress:
                        task = progress.add_task(
                            "Procesando unidades visuales...", total=progress_total
                        )
                        _consume(progress, task)
                else:
                    _consume()
            except KeyboardInterrupt:
                if console is not None:
                    console.print(
                        "\n[yellow]⚠ Corrida interrumpida — guardando artefactos...[/yellow]"
                    )
                source.stop()
                transport.close()
                producer.join(timeout=5.0)

            _drain_producer_errors(run_context._errors_queue, artifact_writer, run_context)
            run_context.units_dropped = getattr(transport, "units_dropped", 0)
            run_context.backpressure_wait_ms = timings["backpressure_wait_ms"]
        finally:
            if producer is not None:
                join_timeout = (
                    PRODUCER_JOIN_TIMEOUT_AFTER_STALL_S if consumer_stalled else 30.0
                )
                producer.join(timeout=join_timeout)
            artifact_writer.close()

        run_context.gpu_memory_peak_mb = get_gpu_memory_peak_mb()
        run_context.finish()
        artifact_writer.write_summary(tracker)
        artifact_writer.write_provenance()
        artifact_writer.write_manifest()
        if control is not None and control.stop_requested:
            bus_status = "stopped"
        return run_context.run_id
    except BaseException:
        bus_status = "failed"
        raise
    finally:
        if bus_publisher is not None:
            # Sentinela END de la corrida 1:1 (ADR-007): sale pase lo que pase,
            # incluso si el run murio. Nunca deja al consumidor colgado.
            try:
                artifact_writer.publish_run_finished(bus_status)
            except Exception:  # noqa: BLE001 — el bus nunca rompe la corrida
                logger.warning("bus: no se pudo publicar run_finished", exc_info=True)
            bus_publisher.close()


def run_pipeline(config: RunConfig, console: Console | None = None) -> str:
    """Ejecuta una corrida creando y cargando el adapter (camino standalone/tests)."""
    console = console or Console()
    adapter = create_adapter(config.model)
    with console.status("[bold cyan]Cargando modelo..."):
        adapter.load()
    try:
        return execute_run(config, adapter, console=console)
    finally:
        adapter.close()
