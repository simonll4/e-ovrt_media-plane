"""Guard: el Nodo A edge (sin torch) debe poder importar el pipeline two-node."""
from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys


PROJECT_ROOT = Path(__file__).parent.parent


def _run_without_torch(code: str) -> None:
    environment = os.environ | {
        "PYTHONPATH": str(PROJECT_ROOT / "src")
        + os.pathsep
        + os.environ.get("PYTHONPATH", ""),
    }
    result = subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True,
        text=True,
        env=environment,
        check=False,
    )
    assert result.returncode == 0, result.stderr


BLOCK_TORCH = """
import builtins

real_import = builtins.__import__

def blocked(name, *args, **kwargs):
    if name == "torch" or name.startswith("torch."):
        raise ImportError("torch bloqueado (simulando node-a edge slim)")
    return real_import(name, *args, **kwargs)

builtins.__import__ = blocked
"""


def test_two_node_importable_without_torch():
    _run_without_torch(BLOCK_TORCH + "\nfrom eovrt_media.runtime import two_node\n")


def test_create_adapter_yoloe_instantiable_without_torch():
    _run_without_torch(
        BLOCK_TORCH
        + """
from eovrt_media.config.schemas import ModelSection
from eovrt_media.models import create_adapter

model_cfg = ModelSection(adapter="yoloe", weights="yoloe-26s-seg.pt", device="cpu")
adapter = create_adapter(model_cfg)
assert adapter.input_spec.target_size == (640, 640)
"""
    )
