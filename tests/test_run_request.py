import pytest
from pydantic import ValidationError

from eovrt_media.config.loader import resolve_model_ref
from eovrt_media.service.run_request import RunRequest, to_raw_run_config

SET_INLINE = {"id": "t", "classes": [{"id": "p", "phrasings": {"default": ["p"]}}]}


def _request(**overrides):
    body = {
        "ingest": {"plugin": "image_folder", "config": {"path": "/tmp/imgs"}},
        "prompts": {"set_inline": SET_INLINE, "active_ids": ["p"]},
        "run": {"stride": 2, "max_units": 10, "save_annotated_video": True},
    }
    body.update(overrides)
    return body


def test_request_valido():
    req = RunRequest(**_request())
    assert req.ingest.plugin == "image_folder"
    assert req.run.stride == 2


def test_seccion_model_rechazada():
    with pytest.raises(ValidationError):
        RunRequest(**_request(model={"ref": "yoloe/yoloe-26s"}))


def test_to_raw_run_config_mapea_contrato():
    raw = to_raw_run_config(RunRequest(**_request()), resolve_model_ref("mock"))
    assert raw["source"]["type"] == "image_folder"
    assert raw["source"]["path"] == "/tmp/imgs"
    assert raw["rate_control"]["stride"] == 2          # run.stride → rate_control.stride
    assert raw["run"]["max_units"] == 10
    assert raw["outputs"]["save_annotated_video"] is True
    assert raw["prompts"]["set_inline"]["id"] == "t"
    assert raw["model"]["adapter"] == "mock"           # modelo de la instancia, no del request


def test_ingest_config_dataset_ref():
    body = _request(ingest={"plugin": "image_folder", "config": {"dataset": "demo_v2"}})
    raw = to_raw_run_config(RunRequest(**body), resolve_model_ref("mock"))
    assert raw["source"] == {"ref": "demo_v2"}
