"""OakDSource — cámara OAK-D Pro PoE vía DepthAI. Declarada, no implementada."""
from __future__ import annotations

from typing import Iterator

from eovrt_media.contracts import VisualUnit
from eovrt_media.sources.base import BaseSource


class OakDSource(BaseSource):
    """Fuente OAK-D Pro PoE vía DepthAI SDK — declarada, no implementada.

    Requires: pip install depthai
    Produces: frames RGB vía dai.Pipeline XLinkOut.
    Ver docs/contexto/oak-d-integration.md cuando se implemente.
    """

    def __init__(self, url: str | None = None, max_units: int | None = None) -> None:
        self.url = url
        self.max_units = max_units

    def __iter__(self) -> Iterator[VisualUnit]:
        raise NotImplementedError(
            "OakDSource (source.type=oak_d) requiere DepthAI instalado y configurado. "
            "Declarada para la cámara OAK-D Pro PoE; pendiente de implementación."
        )

    def __len__(self) -> int:
        # OakDSource is a live camera with no defined length.
        # Following BaseSource contract for live sources: raise TypeError.
        raise TypeError("OakDSource is a live camera with no defined length")
