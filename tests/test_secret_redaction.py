"""Tests para redacción de credenciales en URLs RTSP."""

from eovrt_media.config.schemas import RunConfig, redact_url_credentials

SET_INLINE = {"id": "t", "classes": [{"id": "p", "phrasings": {"default": ["p"]}}]}


def test_redact_userinfo():
    assert (
        redact_url_credentials("rtsp://admin:s3cret@10.0.0.5:554/stream")
        == "rtsp://***:***@10.0.0.5:554/stream"
    )


def test_redact_sin_credenciales_identidad():
    assert redact_url_credentials("rtsp://10.0.0.5/stream") == "rtsp://10.0.0.5/stream"


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
