"""RunManager: un run activo, stop/watchdog, summary como fuente de verdad."""
from __future__ import annotations

import json
import logging
import threading
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from eovrt_media.config.loader import find_plane_catalog_root, load_run_config_data
from eovrt_media.config.schemas import ModelSection
from eovrt_media.runtime.pipeline import RunControl, execute_run
from eovrt_media.service.activity_slot import ActivitySlot
from eovrt_media.service.events import EventBroadcaster, Subscriber
from eovrt_media.service.retention import gc_runs_dir
from eovrt_media.service.run_request import RunRequest, to_raw_run_config
from eovrt_media.service.settings import ServiceSettings
from eovrt_media.sinks.jsonl_sink import atomic_write_json

logger = logging.getLogger(__name__)

# Cada cuántos segundos de wall-clock corre el GC de retención desde el
# watchdog (gc_runs_dir sólo se invocaba al startup — Fix 2 hardening F2).
_GC_INTERVAL_SECONDS = 3600.0


class RunBusyError(RuntimeError):
    def __init__(self, active_run_id: str) -> None:
        super().__init__(f"Ya hay un run activo: {active_run_id}")
        self.active_run_id = active_run_id


class UnknownRunError(KeyError):
    pass


# Splits del BENCH con GT disponible: un único COCO
# (construction_site_safety_bench.json) cubre val y test.
BENCH_SPLITS = frozenset({"bench_v2_test", "bench_v2_val"})


def bench_metadata(run_dir: Path) -> dict[str, Any]:
    """`bench_split`/`evaluated` derivados de los artefactos del run.

    Barato (2 stats por run); la provenance ilegible/ausente degrada a
    bench_split=None en vez de romper get/list.
    """
    bench_split = None
    provenance_path = run_dir / "run_provenance.json"
    if provenance_path.exists():
        try:
            provenance = json.loads(provenance_path.read_text())
        except (json.JSONDecodeError, OSError):
            provenance = {}
        split = provenance.get("split")
        if split in BENCH_SPLITS:
            bench_split = split
    return {
        "bench_split": bench_split,
        "evaluated": (run_dir / "eval_perception.json").exists(),
    }


@dataclass
class ActiveRun:
    run_id: str
    config: Any
    control: RunControl
    broadcaster: EventBroadcaster
    started_at: datetime
    thread: threading.Thread | None = None
    status: str = "running"
    stop_cause: str | None = None
    error: str | None = None
    finished: threading.Event = field(default_factory=threading.Event)


class RunManager:
    def __init__(
        self,
        adapter: Any,
        model_section: ModelSection,
        settings: ServiceSettings,
        slot: ActivitySlot | None = None,
    ) -> None:
        self._adapter = adapter
        self._model_section = model_section
        self._settings = settings
        self._slot = slot if slot is not None else ActivitySlot()
        self._lock = threading.Lock()
        self._active: ActiveRun | None = None
        self._closing = threading.Event()
        self._gc_interval_seconds = _GC_INTERVAL_SECONDS
        self._last_gc_monotonic = time.monotonic()
        self._watchdog = threading.Thread(
            target=self._watchdog_loop, daemon=True, name="run-watchdog"
        )
        self._watchdog.start()

    # --- API ---

    def start_run(self, request: RunRequest) -> str:
        with self._lock:
            if self._active is not None:
                raise RunBusyError(self._active.run_id)
            raw = to_raw_run_config(request, self._model_section)
            raw.setdefault("outputs", {})["run_dir"] = str(self._settings.runs_dir)
            config = load_run_config_data(
                raw,
                plane_root=find_plane_catalog_root(None, self._settings.catalog_root),
                datasets_root=self._settings.datasets_root,
            )
            config.run.id = self._new_run_id(config)
            self._slot.acquire("run", config.run.id)  # SlotBusyError si preview activa
            active = ActiveRun(
                run_id=config.run.id,
                config=config,
                control=RunControl(),
                broadcaster=EventBroadcaster(),
                started_at=datetime.now(timezone.utc),
            )
            self._active = active
        try:
            thread = threading.Thread(
                target=self._execute, args=(active,), daemon=True, name="run-executor"
            )
            active.thread = thread
            thread.start()
        except Exception:
            with self._lock:
                self._active = None
                self._slot.release("run")
            raise
        return active.run_id

    def stop(self, run_id: str, cause: str = "stop") -> None:
        with self._lock:
            active = self._active
            if active is None or active.run_id != run_id:
                raise UnknownRunError(run_id)
            if active.stop_cause is None:
                active.stop_cause = cause
        active.control.request_stop()

    def stop_active(self, cause: str) -> None:
        with self._lock:
            active = self._active
        if active is not None:
            self.stop(active.run_id, cause=cause)

    def join_active(self, timeout: float) -> None:
        with self._lock:
            active = self._active
        if active is not None:
            active.finished.wait(timeout=timeout)

    def get(self, run_id: str) -> dict[str, Any]:
        with self._lock:
            active = self._active
        if active is not None and active.run_id == run_id:
            return {
                "run_id": run_id,
                "name": active.config.run.name,
                "status": active.status,
                "started_at": active.started_at.isoformat(),
                "model": self._model_section.ref,
                "live": True,
                **bench_metadata(self._settings.runs_dir / run_id),
            }
        summary_path = self._settings.runs_dir / run_id / "summary.json"
        if not summary_path.exists():
            # Sin summary pero con effective_config: run en curso de otro proceso
            # (p.ej. two-node) que comparte runs_dir — visible como running.
            if (self._settings.runs_dir / run_id / "effective_config.yaml").exists():
                return {
                    "run_id": run_id,
                    "name": None,
                    "status": "running",
                    "live": False,
                    **bench_metadata(self._settings.runs_dir / run_id),
                }
            raise UnknownRunError(run_id)
        try:
            summary = json.loads(summary_path.read_text())
        except (json.JSONDecodeError, OSError) as exc:
            # Summary corrupto/truncado (kill/OOM a mitad de escritura) o borrado
            # por un DELETE concurrente (TOCTOU): tratamos el run como inexistente
            # en vez de propagar un 500.
            logger.warning("summary ilegible para run_id=%s: %s", run_id, exc)
            raise UnknownRunError(run_id) from exc
        return {
            "run_id": run_id,
            "name": summary.get("name"),
            "status": summary.get("status", "unknown"),
            "summary": summary,
            "live": False,
            **bench_metadata(self._settings.runs_dir / run_id),
        }

    def list_runs(self) -> list[dict[str, Any]]:
        runs: list[dict[str, Any]] = []
        with self._lock:
            active = self._active
        if active is not None:
            runs.append(
                {
                    "run_id": active.run_id,
                    "name": active.config.run.name,
                    "status": active.status,
                    "live": True,
                    **bench_metadata(self._settings.runs_dir / active.run_id),
                }
            )
        runs_dir = self._settings.runs_dir
        if runs_dir.is_dir():
            dirs = sorted(
                (d for d in runs_dir.iterdir() if d.is_dir()),
                key=lambda d: d.stat().st_mtime,
                reverse=True,
            )
            for d in dirs:
                if active is not None and d.name == active.run_id:
                    continue
                summary_path = d / "summary.json"
                if summary_path.exists():
                    try:
                        summary = json.loads(summary_path.read_text())
                    except (json.JSONDecodeError, OSError) as exc:
                        # Summary corrupto/truncado o borrado por un DELETE
                        # concurrente (TOCTOU, FileNotFoundError es OSError):
                        # se omite el run en vez de romper el listado completo.
                        logger.warning(
                            "Omitiendo run %s: summary ilegible (%s)", d.name, exc
                        )
                        continue
                    runs.append(
                        {
                            "run_id": d.name,
                            "name": summary.get("name"),
                            "status": summary.get("status", "unknown"),
                            "live": False,
                            **bench_metadata(d),
                        }
                    )
                elif (d / "effective_config.yaml").exists():
                    runs.append(
                        {
                            "run_id": d.name,
                            "name": None,
                            "status": "running",
                            "live": False,
                            **bench_metadata(d),
                        }
                    )
        return runs

    def subscribe(self, run_id: str) -> Subscriber:
        with self._lock:
            active = self._active
        if active is None or active.run_id != run_id:
            raise UnknownRunError(run_id)
        return active.broadcaster.subscribe()

    def unsubscribe(self, run_id: str, sub: Subscriber) -> None:
        with self._lock:
            active = self._active
        if active is not None and active.run_id == run_id:
            active.broadcaster.unsubscribe(sub)

    def shutdown(self) -> None:
        self._closing.set()

    # --- interno ---

    def _new_run_id(self, config: Any) -> str:
        ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        model = (self._model_section.name or self._model_section.adapter or "model").lower()
        # sufijo único: el default de RunContext (segundos) colisiona (Spec A §3.1)
        return f"run_{ts}_{config.run.scenario.lower()}_{model}_{uuid.uuid4().hex[:6]}"

    def _execute(self, active: ActiveRun) -> None:
        status, error = "succeeded", None
        try:
            execute_run(
                active.config,
                self._adapter,
                control=active.control,
                event_sink=active.broadcaster,
            )
        except Exception as exc:  # noqa: BLE001 — el estado failed captura la causa
            status, error = "failed", str(exc)
            logger.exception("Run %s falló durante la ejecución", active.run_id)
        if active.control.stop_requested and status == "succeeded":
            status = "failed" if active.stop_cause == "stalled" else "stopped"
        self._finalize(active, status, error)

    def _finalize(self, active: ActiveRun, status: str, error: str | None) -> None:
        try:
            run_dir = self._settings.runs_dir / active.run_id
            run_dir.mkdir(parents=True, exist_ok=True)
            summary_path = run_dir / "summary.json"
            summary: dict[str, Any] = {}
            if summary_path.exists():
                try:
                    summary = json.loads(summary_path.read_text())
                except (json.JSONDecodeError, OSError) as exc:
                    logger.warning(
                        "summary ilegible al finalizar run_id=%s, se reconstruye desde cero: %s",
                        active.run_id,
                        exc,
                    )
            summary.setdefault("run_id", active.run_id)
            if status == "succeeded" and not summary.get("units_processed", 0):
                # Una fuente que nunca entregó una unidad retorna limpio y nada
                # lanza: la RTSP agota sus reintentos ("No route to host" ×5),
                # la carpeta vacía sólo loguea un warning. El run salía
                # "succeeded" con error=None y stop_cause=None — falla
                # silenciosa. Para un sistema cuyo trabajo es capturar
                # evidencia irrepetible, cero unidades nunca es un éxito: en
                # una corrida live equivale a tildar el checklist sin datos.
                status = "failed"
                error = error or (
                    "la corrida no procesó ninguna unidad: la fuente no entregó "
                    "datos (¿cámara inalcanzable, ruta vacía o sin permisos?)"
                )
                logger.error(
                    "Run %s terminó sin procesar unidades; se marca failed", active.run_id
                )
            summary["status"] = status
            summary["stop_cause"] = active.stop_cause
            summary["error"] = error
            atomic_write_json(summary_path, summary)
            active.status = status
            active.error = error
            active.broadcaster.emit({"type": "state", "status": status, "error": error})
            active.finished.set()
        finally:
            with self._lock:
                self._active = None
                self._slot.release("run")

    def _watchdog_loop(self) -> None:
        while not self._closing.wait(timeout=5.0):
            self._watchdog_tick()

    def _watchdog_tick(self) -> None:
        """Una pasada del watchdog; extraído de `_watchdog_loop` para poder
        testearlo sin depender del timing real del hilo."""
        self._maybe_gc()
        with self._lock:
            active = self._active
        if active is None or active.stop_cause is not None:
            return
        idle = time.monotonic() - active.broadcaster.last_event_monotonic
        if idle > self._settings.watchdog_seconds:
            logger.warning(
                "Watchdog: run %s sin eventos hace %.1fs (> %.1fs), deteniendo por stall",
                active.run_id,
                idle,
                self._settings.watchdog_seconds,
            )
            try:
                # stop() hace el check-and-set de stop_cause bajo lock, así que
                # un stop() concurrente (p.ej. cause="stop") gana la carrera y
                # el watchdog no lo pisa con "stalled".
                self.stop(active.run_id, cause="stalled")
            except UnknownRunError:
                # El run terminó entre la lectura de staleness y este stop():
                # ya no hay nada que detener.
                pass

    def _maybe_gc(self) -> None:
        """Corre `gc_runs_dir` cada `_gc_interval_seconds` de wall-clock,
        medidos sobre los ticks del watchdog (que ya corre en su propio
        thread). Antes, el GC de retención sólo se disparaba al startup del
        servicio, así que con retención configurada nunca se aplicaba en un
        servicio de larga vida hasta el próximo reinicio."""
        now = time.monotonic()
        if now - self._last_gc_monotonic < self._gc_interval_seconds:
            return
        self._last_gc_monotonic = now
        with self._lock:
            active = self._active
        exclude = {active.run_id} if active is not None else None
        removed = gc_runs_dir(self._settings, exclude=exclude)
        if removed:
            logger.info("GC periódico de retención: %d runs eliminados", len(removed))
