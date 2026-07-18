import pytest

from eovrt_media.service.activity_slot import ActivitySlot, SlotBusyError


def test_acquire_release():
    slot = ActivitySlot()
    slot.acquire("run", "run_1")
    assert slot.owner == ("run", "run_1")
    slot.release("run")
    assert slot.owner is None


def test_acquire_ocupado_lanza_busy():
    slot = ActivitySlot()
    slot.acquire("preview", "pv_1")
    with pytest.raises(SlotBusyError) as exc:
        slot.acquire("run", "run_1")
    assert exc.value.owner_kind == "preview"
    assert exc.value.owner_id == "pv_1"


def test_release_de_otro_kind_es_noop():
    slot = ActivitySlot()
    slot.acquire("run", "run_1")
    slot.release("preview")
    assert slot.owner == ("run", "run_1")
