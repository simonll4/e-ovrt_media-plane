import threading
import time
import numpy as np
import pytest

from eovrt_media.contracts.normalized_unit import (
    NormalizedUnit, ResizeTransform, PayloadFormat, END
)
from eovrt_media.transport.memory import MemoryTransportAdapter
from eovrt_media.transport.rate_gate import RateGate
from eovrt_media.transport.declared import IpcTransportAdapter, NetworkTransportAdapter


def _make_unit(uid: str) -> NormalizedUnit:
    return NormalizedUnit(
        unit_id=uid,
        orig_width=640, orig_height=480,
        payload=np.zeros((640, 640, 3), dtype=np.uint8),
        payload_format=PayloadFormat.UINT8_RGB,
        target_size=(640, 640),
        transform=ResizeTransform(scale_x=1.0, scale_y=1.0, pad_x=0.0, pad_y=0.0),
        timestamp_ms=float(int(uid.split("_")[-1])) * 10.0,
    )


class TestRateGate:
    def test_stride_1_passes_all(self):
        gate = RateGate(stride=1)
        assert all(gate.should_pass(i) for i in range(10))

    def test_stride_2_passes_even(self):
        gate = RateGate(stride=2)
        assert gate.should_pass(0) is True
        assert gate.should_pass(1) is False
        assert gate.should_pass(2) is True
        assert gate.should_pass(3) is False

    def test_stride_3(self):
        gate = RateGate(stride=3)
        passing = [i for i in range(9) if gate.should_pass(i)]
        assert passing == [0, 3, 6]


class TestMemoryTransportDeterministic:
    def test_offer_and_request_fifo(self):
        transport = MemoryTransportAdapter(policy="deterministic", max_queue_size=4)
        u1, u2 = _make_unit("u_1"), _make_unit("u_2")
        transport.offer(u1)
        transport.offer(u2)
        assert transport.request().unit_id == "u_1"
        assert transport.request().unit_id == "u_2"

    def test_close_emits_end(self):
        transport = MemoryTransportAdapter(policy="deterministic", max_queue_size=4)
        transport.close()
        sentinel = transport.request()
        assert sentinel is END

    def test_backpressure_blocks_producer(self):
        transport = MemoryTransportAdapter(policy="deterministic", max_queue_size=2)
        transport.offer(_make_unit("u_1"))
        transport.offer(_make_unit("u_2"))
        blocked = threading.Event()
        offered = threading.Event()

        def producer():
            blocked.set()
            transport.offer(_make_unit("u_3"))  # debe bloquearse
            offered.set()

        t = threading.Thread(target=producer, daemon=True)
        t.start()
        blocked.wait(timeout=1.0)
        time.sleep(0.05)
        assert not offered.is_set()  # productor sigue bloqueado
        transport.request()           # consumidor drena uno
        offered.wait(timeout=1.0)
        assert offered.is_set()       # productor desbloqueado


class TestMemoryTransportBoundedFreshness:
    def test_head_drop_on_full_buffer(self):
        transport = MemoryTransportAdapter(policy="bounded_freshness", buffer_size=2)
        transport.offer(_make_unit("u_1"))
        transport.offer(_make_unit("u_2"))
        transport.offer(_make_unit("u_3"))  # head-drop: u_1 sale
        assert transport.units_dropped == 1
        received = transport.request()
        assert received.unit_id == "u_2"   # u_1 fue descartado

    def test_staleness_drop(self):
        transport = MemoryTransportAdapter(
            policy="bounded_freshness", buffer_size=4, max_staleness_ms=5.0
        )
        u_old = _make_unit("u_1")
        u_old.timestamp_ms = 0.0
        transport.offer(u_old)
        transport.close()
        time.sleep(0.01)  # 10ms > 5ms staleness
        result = transport.request(current_time_ms=lambda: time.time() * 1000)
        assert result is END

    def test_close_emits_end(self):
        transport = MemoryTransportAdapter(policy="bounded_freshness", buffer_size=4)
        transport.close()
        assert transport.request() is END


class TestDeclaredStubs:
    def test_ipc_offer_raises(self):
        adapter = IpcTransportAdapter()
        with pytest.raises(NotImplementedError, match="ipc"):
            adapter.offer(_make_unit("u_1"))

    def test_network_request_raises(self):
        adapter = NetworkTransportAdapter(endpoint="tcp://localhost:5555")
        with pytest.raises(NotImplementedError, match="network"):
            adapter.request()


# Suite agnóstica de backend — ejecutar contra memory; misma suite valida futuros backends
class TestTransportContract:
    @pytest.fixture(params=["deterministic", "bounded_freshness"])
    def transport(self, request):
        if request.param == "deterministic":
            return MemoryTransportAdapter(policy="deterministic", max_queue_size=8)
        return MemoryTransportAdapter(policy="bounded_freshness", buffer_size=8)

    def test_offer_then_close_then_request_end(self, transport):
        transport.offer(_make_unit("u_1"))
        transport.close()
        transport.request()  # drena u_1
        assert transport.request() is END

    def test_empty_close_then_end_immediately(self, transport):
        transport.close()
        assert transport.request() is END
