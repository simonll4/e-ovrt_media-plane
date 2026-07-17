"""Lógica del gate EN-2 (spec §5): se ejecuta el script del nodo Script en host
con dobles de node.io/time/Buffer. Sin depthai ni hardware."""
from __future__ import annotations

import builtins
import json
from types import SimpleNamespace

import pytest

from eovrt_media.config.schemas import OakDPrefilterConfig
from eovrt_media.sources.oak_d_source import OakDSource


class _EndOfFrames(Exception):
    pass


class _FakeBuffer:
    def __init__(self, size: int) -> None:
        self._data = b""

    def setData(self, data) -> None:
        self._data = bytes(data)


class _FakeClock:
    def __init__(self) -> None:
        self.t = 0.0

    def monotonic(self) -> float:
        return self.t


def _run_gate(prefilter: OakDPrefilterConfig, ticks):
    """Ejecuta el script contra un plan de ticks.

    ticks: lista de (dt_s, detections | None) — cada tick avanza el reloj dt_s,
    entrega opcionalmente un ImgDetections falso y luego un frame. detections es
    una lista de (label, confidence). Devuelve (frames_enviados, stats_json).
    """
    source = OakDSource(url="192.168.1.50", prefilter=prefilter, _skip_blob_check=True)
    script = source._render_gate_script()
    clock = _FakeClock()
    plan = list(ticks)
    sent, stats = [], []
    pending_dets = []

    def frames_get():
        if not plan:
            raise _EndOfFrames()
        dt, dets = plan.pop(0)
        clock.t += dt
        if dets is not None:
            pending_dets.append(SimpleNamespace(
                detections=[SimpleNamespace(label=lbl, confidence=c) for lbl, c in dets]
            ))
        return f"frame@{clock.t}"

    node = SimpleNamespace(io={
        "frames": SimpleNamespace(get=frames_get),
        "detections": SimpleNamespace(
            tryGet=lambda: pending_dets.pop(0) if pending_dets else None
        ),
        "out": SimpleNamespace(send=sent.append),
        "stats": SimpleNamespace(send=lambda b: stats.append(json.loads(b._data))),
    })
    fake_time = SimpleNamespace(monotonic=clock.monotonic)

    def fake_import(name, *args, **kwargs):
        if name == "time":
            return fake_time
        return builtins.__import__(name, *args, **kwargs)

    glb = {
        "__builtins__": {**vars(builtins), "__import__": fake_import},
        "node": node,
        "Buffer": _FakeBuffer,
    }
    with pytest.raises(_EndOfFrames):
        exec(script, glb)  # noqa: S102 - ejecuta NUESTRO template, es el SUT
    return sent, stats


CFG = OakDPrefilterConfig(
    enabled=True, confidence=0.25,
    keepalive_window_ms=1500, heartbeat_interval_ms=2000, stall_failopen_ms=3000,
)
PERSON = [(1, 0.8)]     # label 1 = person en retail-0013
NOBODY = [(1, 0.1)]     # bajo el umbral


def test_warmup_forwards_everything_until_first_nn_result():
    sent, _ = _run_gate(CFG, [(0.1, None), (0.1, None), (0.1, None)])
    assert len(sent) == 3  # regla 4: sin resultados de NN aún -> pasa todo


def test_person_opens_gate_for_keepalive_window():
    # NN ve persona en t=0.1; frames dentro de la ventana de 1.5 s pasan.
    sent, _ = _run_gate(CFG, [(0.1, PERSON), (0.5, NOBODY), (0.5, NOBODY), (1.0, NOBODY)])
    # t=0.1 (person), t=0.6 (dentro ventana), t=1.1 (dentro), t=2.1 (fuera, sin heartbeat vencido)
    assert len(sent) == 3


def test_no_person_drops_until_heartbeat():
    # Sin personas: solo el warmup inicial y después 1 frame por heartbeat (2 s).
    ticks = [(0.5, NOBODY)] + [(0.5, NOBODY)] * 7
    sent, _ = _run_gate(CFG, ticks)
    # Timeline (tick-by-tick, dets consumidos al TOP del loop siguiente):
    # it1 t=0.5 nn_results==0 -> warmup, sent#1, last_sent_t=0.5
    # it2 t=1.0 drop (nn_results=1, dentro de heartbeat 2.0s desde last_sent_t=0.5)
    # it3 t=1.5 drop
    # it4 t=2.0 drop (now-last_sent_t=1.5 < 2.0)
    # it5 t=2.5 now-last_sent_t=2.0 >= HEARTBEAT_S -> heartbeat, sent#2, last_sent_t=2.5
    # it6 t=3.0 drop .. it8 t=4.0 drop (now-last_sent_t nunca vuelve a >=2.0 antes del fin)
    # plan se agota en la 9na iteración (frames.get) -> _EndOfFrames.
    assert len(sent) == 2


def test_nn_stall_fails_open():
    # NN responde una vez y se calla; pasado stall_failopen_ms (3 s) pasa todo.
    ticks = [(0.1, NOBODY), (1.0, None), (1.0, None), (1.5, None), (0.5, None), (0.5, None)]
    sent, _ = _run_gate(CFG, ticks)
    # Timeline: it1 t=0.1 warmup (sent#1, last_sent_t=0.1, last_nn_t=0.1).
    # it2 t=1.1 drop (now-last_sent_t=1.0<HEARTBEAT_S=2.0, now-last_nn_t=1.0<STALL_S=3.0).
    # it3 t=2.1 now-last_sent_t=2.0>=2.0 -> heartbeat (sent#2, last_sent_t=2.1).
    # it4 t=3.6 now-last_nn_t=3.6-0.1=3.5>=3.0 -> failopen (sent#3, last_sent_t=3.6).
    # it5 t=4.1 now-last_nn_t=4.0>=3.0 -> failopen (sent#4).
    # it6 t=4.6 now-last_nn_t=4.5>=3.0 -> failopen (sent#5).
    # plan se agota -> _EndOfFrames. Total exacto = 5.
    assert len(sent) == 5


def test_stats_report_counters_and_reasons():
    ticks = [(1.1, PERSON), (1.1, NOBODY), (1.1, NOBODY)]
    _, stats = _run_gate(CFG, ticks)
    assert stats, "debe emitir stats ~1/s"
    last = stats[-1]
    assert set(last) == {"seen", "forwarded", "dropped_no_person", "forwarded_by_reason", "nn_results"}
    assert last["seen"] == last["forwarded"] + last["dropped_no_person"]
    assert set(last["forwarded_by_reason"]) == {"person", "heartbeat", "failopen", "warmup"}
