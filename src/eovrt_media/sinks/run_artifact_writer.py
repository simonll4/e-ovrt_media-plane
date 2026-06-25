"""Coordinador de persistencia de artefactos de corrida."""

from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Any

import yaml

from eovrt_media.contracts import (
    DetectionEvent,
    ErrorEvent,
    MetricSample,
    RunDescriptor,
    RunSummary,
)
from eovrt_media.sinks.jsonl_sink import JSONLSink, SummarySink

if TYPE_CHECKING:
    from eovrt_media.runtime.run_context import RunContext


def _get_code_version() -> str | None:
    """Obtiene el commit hash corto del código, si el repo git está disponible."""
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            capture_output=True,
            text=True,
            timeout=5,
            cwd=Path(__file__).resolve().parent,
        )
        if result.returncode == 0:
            return result.stdout.strip()
    except Exception:
        pass
    return None


def _compute_source_fingerprint(source_path: str) -> str:
    """Devuelve SHA-256 del listado ordenado ``path:tamaño`` de una fuente."""
    folder = Path(source_path)
    if not folder.is_dir():
        return ""
    entries = sorted(
        f"{path.name}:{path.stat().st_size}" for path in folder.iterdir() if path.is_file()
    )
    return hashlib.sha256("\n".join(entries).encode()).hexdigest()


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

    def write_provenance(self) -> None:
        """Guarda procedencia de la fuente y una huella reproducible de sus archivos."""
        source = self.context.config.source
        provenance = {
            "run_id": self.context.run_id,
            "dataset_id": source.dataset_id,
            "view": source.view,
            "split": source.split,
            "vocabulary": source.vocabulary,
            "source_fingerprint": _compute_source_fingerprint(source.path),
        }
        with open(self.run_dir / "run_provenance.json", "w", encoding="utf-8") as file:
            json.dump(provenance, file, indent=2, ensure_ascii=False)

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
        p99_lat = 0.0

        if tracker is not None:
            avg_lat = tracker.avg_latency_ms()
            p50_lat = tracker.p50_latency_ms()
            p95_lat = tracker.p95_latency_ms()
            p99_lat = tracker.p99_latency_ms()

        config = self.context.config
        descriptor = RunDescriptor(
            scenario=config.run.scenario,
            topology=config.topology.mode,
            transport={
                "backend": config.transport.backend,
                "payload_format": config.transport.payload_format,
            },
            rate_control={
                "policy": config.rate_control.policy,
                "stride": config.rate_control.stride,
                "max_queue_size": config.rate_control.max_queue_size,
            },
            source_kind=config.source.kind or "pulleable",
            model=config.model.name or config.model.adapter or "unknown",
            prompt_set=(
                config.prompts_file.resolved_version if config.prompts_file else None
            ),
            device=config.model.device,
            code_version=_get_code_version(),
        )

        summary = RunSummary(
            run_id=self.context.run_id,
            scenario=self.context.config.run.scenario,
            model_name=self.context.config.model.name or self.context.config.model.adapter,
            prompt_set_id=(
                self.context.config.prompts_file.resolved_version
                if self.context.config.prompts_file
                else "unknown"
            ),
            source_type=self.context.config.source.type,
            source_count=self.context.units_processed + self.context.units_failed,
            units_processed=self.context.units_processed,
            units_failed=self.context.units_failed,
            total_detections=self.context.total_detections,
            detections_by_label=dict(
                sorted(self.context.detections_by_label.items(), key=lambda kv: -kv[1])
            ),
            detections_by_prompt_id=dict(
                sorted(self.context.detections_by_prompt_id.items(), key=lambda kv: -kv[1])
            ),
            avg_latency_ms=round(avg_lat, 2),
            p50_latency_ms=round(p50_lat, 2),
            p95_latency_ms=round(p95_lat, 2),
            p99_latency_ms=round(p99_lat, 2),
            fps_effective=round(fps_eff, 2),
            gpu_memory_peak_mb=round(self.context.gpu_memory_peak_mb, 2),
            device=self.context.config.model.device,
            duration_seconds=round(dur, 2),
            started_at=self.context.started_at.isoformat(),
            finished_at=finished_at_str,
            units_dropped=self.context.units_dropped,
            backpressure_wait_ms=round(self.context.backpressure_wait_ms, 2),
            max_staleness_observed_ms=round(self.context.max_staleness_observed_ms, 2),
            run_descriptor=descriptor,
        )

        summary_sink = SummarySink(self.run_dir / "summary.json")
        summary_sink.write(summary)

    def write_manifest(self) -> None:
        """Guarda run_manifest.json con metadatos de trazabilidad de la corrida.

        Llamar al final de la corrida para que la lista de archivos esté completa.
        """
        manifest = {
            "run_id": self.context.run_id,
            "started_at": self.context.started_at.isoformat(),
            "finished_at": (
                self.context.finished_at.isoformat() if self.context.finished_at else None
            ),
            "code_version": _get_code_version(),
            "output_dir": str(self.run_dir),
            "config_file": (
                str(self.context.config.config_path)
                if self.context.config.config_path
                else None
            ),
            "generated_files": sorted(
                p.name + ("/" if p.is_dir() else "")
                for p in self.run_dir.iterdir()
                if p.name != "run_manifest.json"
            ),
        }
        with open(self.run_dir / "run_manifest.json", "w", encoding="utf-8") as f:
            json.dump(manifest, f, indent=2, ensure_ascii=False)

    def close(self) -> None:
        """Cierra todos los archivos abiertos por los sinks."""
        if self.detections_sink:
            self.detections_sink.close()
        if self.metrics_sink:
            self.metrics_sink.close()
        if self.errors_sink:
            self.errors_sink.close()
