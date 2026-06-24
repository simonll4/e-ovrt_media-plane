"""OakDSource está declarada pero no implementada."""
from __future__ import annotations

import pytest

from eovrt_media.sources.oak_d_source import OakDSource


def test_oak_d_iter_raises_not_implemented():
    source = OakDSource(url=None)
    with pytest.raises(NotImplementedError, match="OAK-D"):
        list(source)


def test_oak_d_len_is_indefinite():
    source = OakDSource(url=None)
    # OakDSource is a live camera with no defined length.
    # Following BaseSource contract for live sources: raise TypeError, not return -1.
    with pytest.raises(TypeError):
        len(source)
