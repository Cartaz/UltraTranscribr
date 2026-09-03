from __future__ import annotations

from types import SimpleNamespace

import pytest

import core.torch_xpu as tx
from core.exceptions import GPUNotAvailableError


class _Tensor:
    def __matmul__(self, other):
        del other
        return self

    def sum(self):
        return self

    def item(self):
        return 64.0


class _Xpu:
    def __init__(self, available: bool = True) -> None:
        self.available = available
        self.synchronized = False

    def is_available(self) -> bool:
        return self.available

    def device_count(self) -> int:
        return 1 if self.available else 0

    def synchronize(self) -> None:
        self.synchronized = True

    def get_device_name(self, index: int) -> str:
        assert index == 0
        return "Intel Test XPU"


def _fake_torch(available: bool = True):
    xpu = _Xpu(available)
    torch = SimpleNamespace(
        xpu=xpu,
        float32=object(),
        device=lambda name: name,
        ones=lambda shape, dtype, device: _Tensor(),
    )
    return torch, xpu


def test_runtime_requires_real_xpu_probe(monkeypatch) -> None:
    torch, xpu = _fake_torch(True)
    monkeypatch.setattr(tx, "_import_torch", lambda: torch)
    runtime = tx.TorchXpuRuntime()

    assert runtime.require_device() == "xpu:0"
    assert runtime.device_name == "Intel Test XPU"
    assert xpu.synchronized is True


def test_runtime_refuses_unavailable_xpu(monkeypatch) -> None:
    torch, _ = _fake_torch(False)
    monkeypatch.setattr(tx, "_import_torch", lambda: torch)

    with pytest.raises(GPUNotAvailableError, match="XPU non disponibile"):
        tx.TorchXpuRuntime().require_device()
