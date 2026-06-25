"""Timer y tracking de latencias para el plano de medios."""

from __future__ import annotations

import statistics
import time
from dataclasses import dataclass


@dataclass
class TimingResult:
    """Resultado de timing heredado para compatibilidad."""

    unit_id: str
    inference_ms: float
    total_ms: float
    detection_count: int
    error: str | None = None


@dataclass
class UnitTimingResult:
    """Mapeo granular de tiempos requerido por la MEMORIA."""

    unit_id: str
    normalize_ms: float = 0.0
    inference_ms: float = 0.0
    postprocess_ms: float = 0.0
    write_ms: float = 0.0
    total_ms: float = 0.0


class UnitTimer:
    """Timer para medir tiempos de procesamiento de una unidad visual."""

    def __init__(self, unit_id: str) -> None:
        self.unit_id = unit_id
        self._start = time.perf_counter()

        self._normalize_ms = 0.0

        self.inference_start = None
        self.inference_end = None

        self.postprocess_start = None
        self.postprocess_end = None

        self.write_start = None
        self.write_end = None

    def record_normalize_ms(self, duration_ms: float) -> None:
        """Registra normalización medida en el hilo productor."""
        self._normalize_ms = duration_ms

    def start_inference(self) -> None:
        self.inference_start = time.perf_counter()

    def end_inference(self) -> None:
        self.inference_end = time.perf_counter()

    def start_postprocess(self) -> None:
        self.postprocess_start = time.perf_counter()

    def end_postprocess(self) -> None:
        self.postprocess_end = time.perf_counter()

    def start_write(self) -> None:
        self.write_start = time.perf_counter()

    def end_write(self) -> None:
        self.write_end = time.perf_counter()

    def get_granular_result(self) -> UnitTimingResult:
        """Devuelve el desglose granular medido en ms."""
        now = time.perf_counter()
        total_ms = (now - self._start) * 1000.0

        norm = self._normalize_ms
        inf = (self.inference_end - self.inference_start) * 1000.0 if (self.inference_start and self.inference_end) else 0.0
        post = (self.postprocess_end - self.postprocess_start) * 1000.0 if (self.postprocess_start and self.postprocess_end) else 0.0
        write = (self.write_end - self.write_start) * 1000.0 if (self.write_start and self.write_end) else 0.0

        return UnitTimingResult(
            unit_id=self.unit_id,
            normalize_ms=round(norm, 2),
            inference_ms=round(inf, 2),
            postprocess_ms=round(post, 2),
            write_ms=round(write, 2),
            total_ms=round(total_ms, 2),
        )

    def finish(self, detection_count: int = 0, error: str | None = None) -> TimingResult:
        """Finaliza y devuelve el resultado legacy (para compatibilidad)."""
        res = self.get_granular_result()
        return TimingResult(
            unit_id=self.unit_id,
            inference_ms=res.inference_ms or res.total_ms,
            total_ms=res.total_ms,
            detection_count=detection_count,
            error=error,
        )


class LatencyTracker:
    """Trackea latencia por unidad visual y calcula estadísticas agregadas."""

    def __init__(self) -> None:
        self.results: list[TimingResult] = []
        self.granular_results: list[UnitTimingResult] = []

    def start_unit(self, unit_id: str) -> UnitTimer:
        """Inicia el timer para una unidad visual."""
        return UnitTimer(unit_id=unit_id)

    def finish_unit(
        self,
        timer: UnitTimer,
        detection_count: int = 0,
        error: str | None = None,
    ) -> TimingResult:
        """Finaliza el timer y registra el resultado."""
        res = timer.finish(detection_count=detection_count, error=error)
        self.results.append(res)
        self.granular_results.append(timer.get_granular_result())
        return res

    def get_latencies_ms(self) -> list[float]:
        """Devuelve todas las latencias totales en ms (sin errores)."""
        return [r.total_ms for r in self.results if r.error is None]

    def avg_latency_ms(self) -> float:
        """Latencia promedio en ms."""
        latencies = self.get_latencies_ms()
        return statistics.mean(latencies) if latencies else 0.0

    def p50_latency_ms(self) -> float:
        """Percentil 50 de latencia en ms."""
        latencies = self.get_latencies_ms()
        return statistics.median(latencies) if latencies else 0.0

    def p95_latency_ms(self) -> float:
        """Percentil 95 de latencia en ms."""
        latencies = self.get_latencies_ms()
        if not latencies:
            return 0.0
        sorted_lat = sorted(latencies)
        idx = int(len(sorted_lat) * 0.95)
        idx = min(idx, len(sorted_lat) - 1)
        return sorted_lat[idx]

    def p99_latency_ms(self) -> float:
        """Percentil 99 de latencia."""
        latencies = self.get_latencies_ms()
        if not latencies:
            return 0.0
        sorted_lat = sorted(latencies)
        return sorted_lat[min(int(len(sorted_lat) * 0.99), len(sorted_lat) - 1)]
