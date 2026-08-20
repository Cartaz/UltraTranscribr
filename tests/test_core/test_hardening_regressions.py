"""Regression tests for bugs found by the August 2026 audit."""
from __future__ import annotations
import numpy as np
from config.constants import ProcessDefaults, SYCLDefaults
from config.settings import Settings
from core.audio_resampler import StreamingLinearResampler
from core.buffer_manager import BufferManager
from core.text_dedup import deduplicate_text
from core.whisper_backend import WhisperBackend

def test_long_file_timeout_is_per_chunk_not_83_hours():
    assert SYCLDefaults.FILE_CHUNK_REQUEST_TIMEOUT_S == 600.0
    assert SYCLDefaults.LIVE_REQUEST_TIMEOUT_S == 180.0
    assert ProcessDefaults.FILE_SEGMENT_LENGTH_S == 30.0

def test_real_greetings_are_preserved():
    assert deduplicate_text("Buongiorno") == "Buongiorno"
    assert deduplicate_text("Thank you") == "Thank you"

def test_music_preserves_repetitions():
    text="we are here we are here we are here"
    assert deduplicate_text(text,preserve_repetitions=True)==text

def test_buffer_spill_is_fifo_and_stats_reset():
    b=BufferManager(warn_threshold=2,max_memory_chunks=2)
    chunks=[np.full(8,i,dtype=np.float32) for i in range(7)]
    for c in chunks:b.put(c)
    got=[b.get_nowait() for _ in chunks]
    for expected,actual in zip(chunks,got): np.testing.assert_array_equal(actual,expected)
    b.put(chunks[0]); b.clear()
    assert b.total_put==0 and b.total_get==0 and b.qsize==0
    b.close()

def test_streaming_resampler_has_no_large_accumulating_drift():
    r=StreamingLinearResampler(48000,16000)
    total=0; remaining=48000*60
    while remaining:
        n=min(1024,remaining); total+=len(r.process(np.zeros(n,dtype=np.float32))); remaining-=n
    total+=len(r.flush())
    assert abs(total-16000*60)<=2

def test_backend_vad_command_requires_model(tmp_path):
    settings=Settings(); b=WhisperBackend(settings,tmp_path)
    b._server_binary="/bin/true"; b._vad_model_path=tmp_path/"vad.bin"
    cmd=b._build_cmd(tmp_path/"model.bin",True)
    assert "--vad-model" in cmd
    assert "--vad-min-silence-duration-ms" in cmd
    assert str(settings.beam_size) in cmd

def test_endpoint_order_prefers_documented_inference():
    import core.whisper_backend as wb
    assert wb._ENDPOINTS[0]=="/inference"
