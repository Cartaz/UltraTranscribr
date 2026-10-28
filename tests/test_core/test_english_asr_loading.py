"""Arc loading compatibility must preserve allocation errors and restore hooks."""
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from core.english_asr import _xpu_loading_context


def test_integrated_arc_without_memory_query_skips_only_optional_warmup():
    warmup = Mock()
    utils = SimpleNamespace(caching_allocator_warmup=warmup)
    torch = SimpleNamespace(xpu=SimpleNamespace(mem_get_info=Mock(side_effect=RuntimeError(
        "The device doesn't support querying the available free memory."
    ))))
    with pytest.raises(ValueError, match="load failed"):
        with _xpu_loading_context(torch, utils):
            utils.caching_allocator_warmup(object(), {"weight": "xpu"}, None)
            warmup.assert_not_called()
            raise ValueError("load failed")
    assert utils.caching_allocator_warmup is warmup


def test_other_gpu_errors_are_not_suppressed():
    utils = SimpleNamespace(caching_allocator_warmup=Mock())
    torch = SimpleNamespace(xpu=SimpleNamespace(mem_get_info=Mock(side_effect=RuntimeError("device lost"))))
    with pytest.raises(RuntimeError, match="device lost"):
        with _xpu_loading_context(torch, utils):
            pytest.fail("An unavailable GPU cannot load a model")
