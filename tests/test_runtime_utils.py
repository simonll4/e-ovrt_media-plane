import numpy as np

from eovrt_media.models.runtime_utils import (
    make_warmup_image,
    resolve_device,
    should_use_half,
)


def test_resolve_device_cuda_falls_back_to_cpu_without_gpu():
    assert resolve_device("cuda", cuda_available=False) == "cpu"
    assert resolve_device("cuda:0", cuda_available=False) == "cpu"


def test_resolve_device_keeps_cuda_when_available():
    assert resolve_device("cuda", cuda_available=True) == "cuda"


def test_resolve_device_keeps_cpu():
    assert resolve_device("cpu", cuda_available=False) == "cpu"
    assert resolve_device("cpu", cuda_available=True) == "cpu"


def test_should_use_half():
    assert should_use_half("cuda", True) is True
    assert should_use_half("cuda:0", True) is True
    assert should_use_half("cuda", False) is False
    assert should_use_half("cpu", True) is False


def test_make_warmup_image():
    img = make_warmup_image((800, 640))
    assert img.shape == (800, 640, 3)
    assert img.dtype == np.uint8
