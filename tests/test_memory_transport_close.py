import threading

from eovrt_media.contracts.normalized_unit import END
from eovrt_media.transport.memory import MemoryTransportAdapter


class _Unit:  # stub mínimo, el transporte no inspecciona la unidad en deterministic
    pass


def test_close_idempotente_no_bloquea_con_cola_llena():
    t = MemoryTransportAdapter(policy="deterministic", max_queue_size=1)
    t.offer(_Unit())  # cola llena
    done = threading.Event()

    def _close_twice():
        t.close()
        t.close()
        done.set()

    threading.Thread(target=_close_twice, daemon=True).start()
    assert done.wait(timeout=2.0), "close() bloqueó con la cola llena"


def test_consumidor_recibe_end_tras_close_y_drain():
    t = MemoryTransportAdapter(policy="deterministic", max_queue_size=1)
    unit = _Unit()
    t.offer(unit)
    t.close()  # END no entra (cola llena)
    assert t.request() is unit
    assert t.request() is END


def test_offer_tras_close_descarta():
    t = MemoryTransportAdapter(policy="deterministic", max_queue_size=1)
    t.close()
    t.offer(_Unit())  # no debe bloquear
    assert t.units_dropped == 1
    assert t.request() is END
