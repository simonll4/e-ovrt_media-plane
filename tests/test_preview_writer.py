"""Tests para AsyncPreviewWriter: la preview sale del hilo consumidor sin frenarlo."""

import threading
import time

import numpy as np

from eovrt_media.sinks.preview_writer import AsyncPreviewWriter


def test_submit_no_espera_al_dibujo(tmp_path):
    release = threading.Event()
    drawn = []

    def slow_draw(payload, detections, path, **kwargs):
        release.wait(5)
        drawn.append(path.name)

    writer = AsyncPreviewWriter(draw=slow_draw, max_pending=3)
    started = time.perf_counter()
    accepted = [writer.submit(f"u{i}", None, [], tmp_path / f"u{i}.jpg") for i in range(3)]
    assert time.perf_counter() - started < 0.5  # el consumidor nunca espera al JPEG
    assert all(accepted)
    release.set()
    writer.close()
    assert drawn == ["u0.jpg", "u1.jpg", "u2.jpg"]


def test_cola_llena_descarta_sin_bloquear(tmp_path):
    release = threading.Event()

    def blocked_draw(payload, detections, path, **kwargs):
        release.wait(5)

    writer = AsyncPreviewWriter(draw=blocked_draw, max_pending=1)
    results = [writer.submit(f"u{i}", None, [], tmp_path / f"u{i}.jpg") for i in range(6)]
    assert not all(results)
    assert writer.dropped == results.count(False)
    release.set()
    writer.close()


def test_close_drena_lo_encolado_y_escribe_las_previews(tmp_path):
    writer = AsyncPreviewWriter()
    payload = np.zeros((32, 48, 3), dtype=np.uint8)
    for i in range(3):
        assert writer.submit(f"u{i}", payload, [], tmp_path / f"u{i}.preview.jpg")
    assert writer.close() == []
    assert sorted(p.name for p in tmp_path.glob("*.preview.jpg")) == [
        "u0.preview.jpg", "u1.preview.jpg", "u2.preview.jpg"
    ]
    assert not writer.submit("tarde", payload, [], tmp_path / "tarde.preview.jpg")


def test_errores_del_dibujo_se_devuelven_con_su_unidad(tmp_path):
    def failing_draw(payload, detections, path, **kwargs):
        raise OSError("disk full")

    writer = AsyncPreviewWriter(draw=failing_draw)
    writer.submit("u0", None, [], tmp_path / "u0.jpg")
    assert writer.close() == [("u0", "disk full")]
