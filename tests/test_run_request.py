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


def test_experiment_id_aceptado_y_mapeado():
    # extra="forbid" exigiria que experiment_id este declarado explicitamente
    # en RunRequest; si faltara, este body daria 422 en RunRequest(**...).
    req = RunRequest(**_request(experiment_id="exp-42"))
    assert req.experiment_id == "exp-42"
    raw = to_raw_run_config(req, resolve_model_ref("mock"))
    assert raw["experiment"]["id"] == "exp-42"


def test_experiment_id_ausente_no_agrega_seccion():
    req = RunRequest(**_request())
    assert req.experiment_id is None
    raw = to_raw_run_config(req, resolve_model_ref("mock"))
    assert "experiment" not in raw


def test_experiment_id_clave_desconocida_sigue_dando_422():
    # extra="forbid" debe seguir vigente para claves realmente desconocidas.
    with pytest.raises(ValidationError):
        RunRequest(**_request(clave_bogus="algo"))


def test_experiment_id_llega_a_run_config_cargada(tmp_path):
    # Cobertura del camino de carga (sin levantar el servicio completo): un raw
    # config con 'experiment.id' debe llegar a RunConfig.experiment.id, que es
    # justo lo que run_artifact_writer.py:212 lee para poblar el summary.
    from eovrt_media.config.loader import find_plane_catalog_root, load_run_config_data

    body = _request(experiment_id="exp-e2e")
    raw = to_raw_run_config(RunRequest(**body), resolve_model_ref("mock"))
    raw.setdefault("outputs", {})["run_dir"] = str(tmp_path)
    cfg = load_run_config_data(raw, plane_root=find_plane_catalog_root(None, None))
    assert cfg.experiment.id == "exp-e2e"


def test_rtsp_request_produce_run_config_valido(tmp_path):
    """La consola manda solo `url`; el request debe validar sin `path` en disco."""
    from eovrt_media.config.loader import find_plane_catalog_root, load_run_config_data

    body = _request(
        ingest={"plugin": "rtsp", "config": {"url": "rtsp://cam:554/live"}},
        run={"max_units": 3},
    )
    raw = to_raw_run_config(RunRequest(**body), resolve_model_ref("mock"))
    assert raw["source"]["type"] == "rtsp"
    assert raw["source"]["url"] == "rtsp://cam:554/live"

    raw.setdefault("outputs", {})["run_dir"] = str(tmp_path)
    cfg = load_run_config_data(raw, plane_root=find_plane_catalog_root(None, None))
    assert cfg.source.kind == "live"
    assert cfg.source.path is None
    assert cfg.rate_control.policy == "bounded_freshness"
