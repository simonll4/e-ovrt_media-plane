"""RunManager: un run activo, stop/watchdog, summary como fuente de verdad."""
from __future__ import annotations

import json
import threading
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from eovrt_media.config.loader import find_plane_catalog_root, load_run_config_data
from eovrt_media.config.schemas import ModelSection
from eovrt_media.runtime.pipeline import RunControl, execute_run
from eovrt_media.service.events import EventBroadcaster, Subscriber
from eovrt_media.service.run_request import RunRequest, to_raw_run_config
from eovrt_media.service.settings import ServiceSettings


class RunBusyError(RuntimeError):
    def __init__(self, active_run_id: str) -> None:
        super().__init__(f"Ya hay un run activo: {active_run_id}")
        self.active_run_id = active_run_id


class UnknownRunError(KeyError):
    pass


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
        self, adapter: Any, model_section: ModelSection, settings: ServiceSettings
    ) -> None:
        self._adapter = adapter
        self._model_section = model_section
        self._settings = settings
        self._lock = threading.Lock()
        self._active: ActiveRun | None = None
        self._closing = threading.Event()
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
            active = ActiveRun(
                run_id=config.run.id,
                config=config,
                control=RunControl(),
                broadcaster=EventBroadcaster(),
                started_at=datetime.now(timezone.utc),
            )
            self._active = active
        thread = threading.Thread(
            target=self._execute, args=(active,), daemon=True, name="run-executor"
        )
        active.thread = thread
        thread.start()
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
                "status": active.status,
                "started_at": active.started_at.isoformat(),
                "model": self._model_section.ref,
            }
        summary_path = self._settings.runs_dir / run_id / "summary.json"
        if not summary_path.exists():
            raise UnknownRunError(run_id)
        summary = json.loads(summary_path.read_text())
        return {
            "run_id": run_id,
            "status": summary.get("status", "unknown"),
            "summary": summary,
        }

    def list_runs(self) -> list[dict[str, Any]]:
        runs: list[dict[str, Any]] = []
        with self._lock:
            active = self._active
        if active is not None:
            runs.append({"run_id": active.run_id, "status": active.status})
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
                    summary = json.loads(summary_path.read_text())
                    runs.append(
                        {"run_id": d.name, "status": summary.get("status", "unknown")}
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
        if active.control.stop_requested and status == "succeeded":
            status = "failed" if active.stop_cause == "stalled" else "stopped"
        self._finalize(active, status, error)

    def _finalize(self, active: ActiveRun, status: str, error: str | None) -> None:
        run_dir = self._settings.runs_dir / active.run_id
        run_dir.mkdir(parents=True, exist_ok=True)
        summary_path = run_dir / "summary.json"
        summary: dict[str, Any] = (
            json.loads(summary_path.read_text()) if summary_path.exists() else {}
        )
        summary.setdefault("run_id", active.run_id)
        summary["status"] = status
        summary["stop_cause"] = active.stop_cause
        summary["error"] = error
        summary_path.write_text(json.dumps(summary, indent=2))
        active.status = status
        active.error = error
        active.broadcaster.emit({"type": "state", "status": status, "error": error})
        active.finished.set()
        with self._lock:
            self._active = None

    def _watchdog_loop(self) -> None:
        while not self._closing.wait(timeout=5.0):
            with self._lock:
                active = self._active
            if active is None or active.stop_cause is not None:
                continue
            idle = time.monotonic() - active.broadcaster.last_event_monotonic
            if idle > self._settings.watchdog_seconds:
                active.stop_cause = "stalled"
                active.control.request_stop()
