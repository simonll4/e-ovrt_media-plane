"""Acumulador de la metrica compuesta G2A (spec 40 SS5.1, spec 42 SS5).

G2A = captura/lectura del frame -> resultado algoritmico disponible.
Presupuesto declarado: 50-250 ms. El veredicto se toma sobre el P95.
"""

from __future__ import annotations

import statistics

from eovrt_media.contracts.events import G2ASummary

BUDGET_MIN_MS = 50.0
BUDGET_MAX_MS = 250.0


def _percentile(sorted_values: list[float], fraction: float) -> float:
    """Percentil por indice (mismo criterio que `LatencyTracker`, para no mezclar metodos)."""
    if not sorted_values:
        return 0.0
    index = min(int(len(sorted_values) * fraction), len(sorted_values) - 1)
    return sorted_values[index]


class G2AAccumulator:
    def __init__(self) -> None:
        self.samples: list[float] = []

    def add(self, g2a_ms: float) -> None:
        self.samples.append(g2a_ms)

    def summarize(
        self, warmup_units: int, applicability_state: str, causes: list[str]
    ) -> G2ASummary:
        """`applicability_state`/`causes` los decide el runtime (topologia, relojes).

        La rama "no interpretable" (o cualquier estado distinto de "computed")
        se evalua ANTES que la de "sin muestras": en topologia two_node el
        acumulador queda vacio a proposito (no se acumula un g2a_ms sin
        sentido), pero eso no es lo mismo que "no hubo unidades" — se
        procesaron, solo que la metrica no es interpretable. Invertir el
        orden haria que el summary mienta con "no_units_processed" cuando en
        realidad hubo unidades (ADR-006).
        """
        if applicability_state != "computed":
            return G2ASummary(
                state=applicability_state,
                causes=list(causes),
                count=len(self.samples),
                warmup_units=warmup_units,
            )

        if not self.samples:
            return G2ASummary(
                state="applicable_not_computed",
                causes=["no_units_processed"],
                count=0,
                warmup_units=warmup_units,
            )

        measured = self.samples[warmup_units:] if warmup_units > 0 else list(self.samples)
        if not measured:
            return G2ASummary(
                state="applicable_not_computed",
                causes=["all_units_in_warmup"],
                count=0,
                warmup_units=warmup_units,
            )

        ordered = sorted(measured)
        p95 = _percentile(ordered, 0.95)
        return G2ASummary(
            state="computed",
            causes=[],
            count=len(measured),
            warmup_units=warmup_units,
            avg_ms=round(statistics.mean(measured), 3),
            p50_ms=round(statistics.median(measured), 3),
            p95_ms=round(p95, 3),
            p99_ms=round(_percentile(ordered, 0.99), 3),
            p95_within_budget=p95 <= BUDGET_MAX_MS,
        )
