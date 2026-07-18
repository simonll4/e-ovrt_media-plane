import pytest
from pydantic import ValidationError

from eovrt_media.service.preview_request import PreviewRequest, to_run_request

SET_INLINE = {"id": "t", "classes": [{"id": "p", "phrasings": {"default": ["p"]}}]}


def test_raw_sin_prompts_es_valido():
    req = PreviewRequest(mode="raw", ingest={"plugin": "image_folder", "config": {"path": "x"}})
    assert req.prompts is None
    assert req.params.score_threshold is None


def test_detect_sin_prompts_es_invalido():
    with pytest.raises(ValidationError):
        PreviewRequest(mode="detect", ingest={"plugin": "image_folder", "config": {"path": "x"}})


def test_campo_desconocido_rechazado():
    with pytest.raises(ValidationError):
        PreviewRequest(mode="raw", ingest={"plugin": "image_folder"}, run={"stride": 2})


def test_threshold_fuera_de_rango():
    with pytest.raises(ValidationError):
        PreviewRequest(
            mode="detect",
            ingest={"plugin": "image_folder"},
            prompts={"set_inline": SET_INLINE},
            params={"score_threshold": 1.5},
        )


def test_to_run_request_detect_conserva_prompts():
    req = PreviewRequest(
        mode="detect", ingest={"plugin": "image_folder", "config": {"path": "x"}},
        prompts={"set_inline": SET_INLINE},
    )
    rr = to_run_request(req)
    assert rr.prompts.set_inline == SET_INLINE
    assert rr.ingest.plugin == "image_folder"


def test_to_run_request_raw_usa_set_dummy():
    req = PreviewRequest(mode="raw", ingest={"plugin": "image_folder", "config": {"path": "x"}})
    rr = to_run_request(req)
    assert rr.prompts.set_inline["id"] == "preview_raw"
