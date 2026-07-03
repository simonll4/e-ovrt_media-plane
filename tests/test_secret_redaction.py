"""Tests para redacción de credenciales en URLs RTSP."""

from eovrt_media.config.schemas import RunConfig, redact_url_credentials

SET_INLINE = {"id": "t", "classes": [{"id": "p", "phrasings": {"default": ["p"]}}]}


def test_redact_userinfo():
    assert (
        redact_url_credentials("rtsp://admin:s3cret@10.0.0.5:554/stream")
        == "rtsp://***:***@10.0.0.5:554/stream"
    )


def test_redact_password_con_arroba_embebida():
    """Password con '@' sin escapar: no debe sobrevivir ningún fragmento."""
    result = redact_url_credentials("rtsp://user:p@ss@host/path")
    assert result == "rtsp://***:***@host/path"
    assert "p@ss" not in result


def test_redact_password_con_arroba_embebida_pegada_al_host():
    """Caso límite: el '@' embebido queda justo antes del último '@' real."""
    result = redact_url_credentials("rtsp://admin:s3cr@t@10.0.0.5:554/stream")
    assert result == "rtsp://***:***@10.0.0.5:554/stream"
    assert "s3cr@t" not in result
    assert "s3cr" not in result


def test_redact_solo_username_sin_password():
    """Username sin password: no debe fabricar ni filtrar el username original."""
    result = redact_url_credentials("rtsp://user@host/path")
    assert result == "rtsp://***:***@host/path"
    assert "user" not in result


def test_redact_password_con_dos_puntos_embebidos():
    result = redact_url_credentials("rtsp://a:b:c@host/path")
    assert result == "rtsp://***:***@host/path"
    assert "b:c" not in result


def test_redact_sin_credenciales_identidad():
    assert redact_url_credentials("rtsp://10.0.0.5/stream") == "rtsp://10.0.0.5/stream"


def test_redact_host_con_puerto_sin_credenciales_identidad():
    assert redact_url_credentials("rtsp://host:554/path") == "rtsp://host:554/path"


def test_redact_arroba_en_query_no_es_userinfo():
    """El '@' vive en la query, no en la authority: no hay userinfo que redactar."""
    assert (
        redact_url_credentials("rtsp://host/path?foo=a@b")
        == "rtsp://host/path?foo=a@b"
    )


def test_redact_path_local_sin_esquema_identidad():
    assert redact_url_credentials("/data/video.mp4") == "/data/video.mp4"


def test_effective_dict_redacta_source_url():
    config = RunConfig(
        run={},
        source={
            "type": "rtsp", "kind": "live",
            "path": "rtsp://u:p@cam/live", "url": "rtsp://u:p@cam/live",
        },
        model={"adapter": "mock"},
        prompts={"set_inline": SET_INLINE},
        rate_control={"policy": "bounded_freshness"},
    )
    data = config.to_effective_dict()
    assert "s3cret" not in str(data) and "u:p@" not in str(data)
    assert data["source"]["url"] == "rtsp://***:***@cam/live"
    assert data["source"]["path"] == "rtsp://***:***@cam/live"
