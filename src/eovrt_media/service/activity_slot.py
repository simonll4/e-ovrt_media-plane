"""Slot único de actividad del media-plane: un run O una preview, nunca ambos."""

from __future__ import annotations

import threading


class SlotBusyError(RuntimeError):
    def __init__(self, owner_kind: str, owner_id: str | None) -> None:
        detalle = f" ({owner_id})" if owner_id else ""
        super().__init__(f"Slot de actividad ocupado por {owner_kind}{detalle}")
        self.owner_kind = owner_kind
        self.owner_id = owner_id


class ActivitySlot:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._owner: tuple[str, str | None] | None = None

    def acquire(self, kind: str, owner_id: str | None = None) -> None:
        with self._lock:
            if self._owner is not None:
                raise SlotBusyError(*self._owner)
            self._owner = (kind, owner_id)

    def release(self, kind: str) -> None:
        with self._lock:
            if self._owner is not None and self._owner[0] == kind:
                self._owner = None

    @property
    def owner(self) -> tuple[str, str | None] | None:
        with self._lock:
            return self._owner
