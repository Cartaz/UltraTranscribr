# tests/test_core/test_buffer_manager.py
"""Test per il BufferManager dell'applicazione unificata."""

import numpy as np
import pytest

from core.buffer_manager import BufferManager


class TestBufferManager:
    """Test per il buffer audio thread-safe."""

    def test_put_and_get(self) -> None:
        """put + get deve restituire lo stesso chunk."""
        buf = BufferManager()
        chunk = np.ones(16000, dtype=np.float32)
        buf.put(chunk)
        result = buf.get_nowait()
        assert result is not None
        np.testing.assert_array_equal(result, chunk)

    def test_empty_state(self) -> None:
        """Un buffer nuovo deve essere vuoto."""
        buf = BufferManager()
        assert buf.is_empty
        assert buf.qsize == 0

    def test_buffer_level(self) -> None:
        """buffer_level deve essere 0 per un buffer vuoto."""
        buf = BufferManager()
        assert buf.buffer_level == 0

    def test_is_buffering_threshold(self) -> None:
        """is_buffering deve essere True oltre la soglia di warning."""
        buf = BufferManager(warn_threshold=3)
        for i in range(4):
            buf.put(np.ones(100, dtype=np.float32))
        assert buf.is_buffering

    def test_clear(self) -> None:
        """clear deve svuotare il buffer."""
        buf = BufferManager()
        for _ in range(5):
            buf.put(np.ones(100, dtype=np.float32))
        count = buf.clear()
        assert count == 5
        assert buf.is_empty

    def test_total_put_get_counters(self) -> None:
        """I contatori total_put e total_get devono tracciare le operazioni."""
        buf = BufferManager()
        chunk = np.ones(100, dtype=np.float32)
        buf.put(chunk)
        buf.put(chunk)
        assert buf.total_put == 2
        buf.get_nowait()
        assert buf.total_get == 1
