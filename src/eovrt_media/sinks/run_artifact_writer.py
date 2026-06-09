"""Coordinador de persistencia de artefactos de corrida."""

from __future__ import annotations

import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Any

import yaml

from eovrt_media.contracts import DetectionEvent, MetricSample, RunSummary, ErrorEvent
from eovrt_media.sinks.jsonl_sink import JSONLSink, SummarySink

if TYPE_CHECKING:
    from eovrt_media.runtime.run_context import RunContext


class RunArtifactWriter:
    """Administra la escritura coordinada de todos los outputs de una corrida."""

    def __init__(self, run_context: RunContext) -> None:
        self.context = run_context
        self.run_dir = run_context.run_dir
        self.run_dir.mkdir(parents=True, exist_ok=True)

        self.detections_sink = None
        self.metrics_sink = None
        self.errors_sink = None

        outputs_cfg = self.context.config.outputs

        if outputs_cfg.save_detections_jsonl:
            self.detections_sink = JSONLSink(self.run_dir / "detections.jsonl")
            self.detections_sink.open()

        if outputs_cfg.save_metrics_jsonl:
            self.metrics_sink = JSONLSink(self.run_dir / "metrics.jsonl")
            self.metrics_sink.open()

        if outputs_cfg.save_errors_jsonl:
            self.errors_sink = JSONLSink(self.run_dir / "errors.jsonl")
            self.errors_sink.open()

        if outputs_cfg.save_previews:
            (self.run_dir / "previews").mkdir(exist_ok=True)

    def write_original_config(self, original_path: Path | str | None) -> None:
        """Copia el archivo de configuración original a la carpeta de salida."""
        if not original_path:
            return
        original_path = Path(original_path)
        if original_path.exists():
            shutil.copy(original_path, self.run_dir / "run_config.yaml")

    def write_effective_config(self) -> None:
        """Guarda la configuración efectiva realmente aplicada."""
        eff_dict = self.context.config.to_effective_dict()
        with open(self.run_dir / "effective_config.yaml", "w", encoding="utf-8") as f:
            yaml.dump(eff_dict, f, default_flow_style=False, allow_unicode=True)

    def write_detection(self, event: DetectionEvent) -> None:
        """Escribe un evento de detección."""
        if self.detections_sink:
            self.detections_sink.write_event(event)

    def write_metric(self, sample: MetricSample) -> None:
        """Escribe una muestra de métricas."""
        if self.metrics_sink:
            self.metrics_sink.write_metric(sample)

    def write_error(self, error: ErrorEvent) -> None:
        """Escribe un evento de error."""
        self.context.errors_count += 1
        if self.errors_sink:
            self.errors_sink.write_error(error)

    def write_summary(self, tracker: Any | None = None) -> None:
        """Genera y guarda el resumen final summary.json."""
        finished_at_str = (
            self.context.finished_at.isoformat()
            if self.context.finished_at
            else datetime.now(timezone.utc).isoformat()
        )

        dur = self.context.duration_seconds
        # Calcular FPS efectivos en todo el tramo de la corrida
        fps_eff = self.context.units_processed / dur if dur > 0 else 0.0

        avg_lat = 0.0
        p50_lat = 0.0
        p95_lat = 0.0

        if tracker is not None:
            # LatencyTracker viejo o nuevo
            if hasattr(tracker, "avg_latency_ms"):
                avg_lat = tracker.avg_latency_ms()
            if hasattr(tracker, "p50_latency_ms"):
                p50_lat = tracker.p50_latency_ms()
            if hasattr(tracker, "p95_latency_ms"):
                p95_lat = tracker.p95_latency_ms()

        summary = RunSummary(
            run_id=self.context.run_id,
            scenario=self.context.config.run.scenario,
            model_adapter=self.context.config.model.adapter,
            model_name=self.context.config.model.name,
            prompt_version=(
                self.context.config.prompts_file.resolved_version
                if self.context.config.prompts_file
                else "unknown"
            ),
            source_type=self.context.config.source.type,
            source_count=self.context.units_processed + self.context.units_failed,
            units_processed=self.context.units_processed,
            units_failed=self.context.units_failed,
            total_detections=self.context.total_detections,
            avg_latency_ms=round(avg_lat, 2),
            p50_latency_ms=round(p50_lat, 2),
            p95_latency_ms=round(p95_lat, 2),
            fps_effective=round(fps_eff, 2),
            device=self.context.config.model.device,
            duration_seconds=round(dur, 2),
            started_at=self.context.started_at.isoformat(),
            finished_at=finished_at_str,
        )

        summary_sink = SummarySink(self.run_dir / "summary.json")
        summary_sink.write(summary)

    def close(self) -> None:
        """Cierra todos los archivos abiertos por los sinks."""
        if self.detections_sink:
            self.detections_sink.close()
        if self.metrics_sink:
            self.metrics_sink.close()
        if self.errors_sink:
            self.errors_sink.close()
