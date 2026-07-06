"""Entrypoint two-node: despacho por rol, carga de config y exit codes."""
from __future__ import annotations

from pathlib import Path

import pytest

from eovrt_media.tools import run_node


def _write_minimal_config(tmp_path: Path) -> Path:
    # Config mínima válida: mock + image_folder sobre un dir con una imagen falsa.
    images = tmp_path / "imgs"
    images.mkdir()
    (images / "f.jpg").write_bytes(b"\xff\xd8\xff\xd9")  # JPEG vacío: alcanza para el load
    config = tmp_path / "run.yaml"
    config.write_text(
        f"""
run:
  scenario: EBE
  name: run_node_test
source:
  type: image_folder
  path: {images}
model:
  ref: mock
prompts:
  set_inline:
    id: t
    classes:
      - id: person
        phrasings:
          default:
            - person
topology:
  mode: two_node
transport:
  backend: network
  endpoint: "tcp://127.0.0.1:5599"
  heartbeat_endpoint: "tcp://127.0.0.1:5600"
""",
        encoding="utf-8",
    )
    return config


def test_role_a_dispatches_to_run_node_a(tmp_path, monkeypatch):
    called = {}
    monkeypatch.setattr(run_node, "_RUNNERS", {"a": lambda c: called.setdefault("a", c),
                                               "b": lambda c: called.setdefault("b", c)})
    config = _write_minimal_config(tmp_path)

    run_node.main(["--role", "a", "--config", str(config)])

    assert "a" in called and "b" not in called
    assert called["a"].run.name == "run_node_test"


def test_role_b_dispatches_to_run_node_b(tmp_path, monkeypatch):
    called = {}
    monkeypatch.setattr(run_node, "_RUNNERS", {"a": lambda c: called.setdefault("a", c),
                                               "b": lambda c: called.setdefault("b", c)})
    config = _write_minimal_config(tmp_path)

    run_node.main(["--role", "b", "--config", str(config)])

    assert "b" in called and "a" not in called


def test_missing_config_exits_1(tmp_path, capsys):
    with pytest.raises(SystemExit) as excinfo:
        run_node.main(["--role", "a", "--config", str(tmp_path / "nope.yaml")])
    assert excinfo.value.code == 1
    assert "nope.yaml" in capsys.readouterr().err


def test_runtime_error_exits_1(tmp_path, monkeypatch, capsys):
    def boom(config):
        raise RuntimeError("zmq explotó")

    monkeypatch.setattr(run_node, "_RUNNERS", {"a": boom, "b": boom})
    config = _write_minimal_config(tmp_path)

    with pytest.raises(SystemExit) as excinfo:
        run_node.main(["--role", "b", "--config", str(config)])
    assert excinfo.value.code == 1
    assert "zmq explotó" in capsys.readouterr().err


def test_invalid_role_exits_2(tmp_path):
    with pytest.raises(SystemExit) as excinfo:
        run_node.main(["--role", "c", "--config", "x.yaml"])
    assert excinfo.value.code == 2  # argparse
