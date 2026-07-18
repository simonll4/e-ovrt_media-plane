"""Debugging framework for media-plane diagnostic campaigns.

`DebugEventWriter` es el escritor de eventos de debug usado por el pipeline activo.
`analyzer`/`reporter` son utilidades de diagnóstico de runs (importables directo). La
campaña two-node-local (`session`/`debug_run`) se eliminó al quedar sin CLI (2026-07-18);
su reemplazo es el split dockerizado de `infra/twonode/`.
"""

from eovrt_media.debugging.events import DebugEvent, DebugEventWriter

__all__ = [
    "DebugEvent",
    "DebugEventWriter",
]
