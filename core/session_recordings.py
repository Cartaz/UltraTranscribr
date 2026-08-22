"""Safe lookup and deletion for retained Live/Meeting microphone recordings."""
from __future__ import annotations

from pathlib import Path
from typing import Any, Optional

import soundfile as sf

from config.constants import AppMeta


def _safe_session_id(session_id: str) -> str:
    value = str(session_id or "")
    if not value or any(
        ch not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_"
        for ch in value
    ):
        raise ValueError("session id non valido")
    return value


def recording_path(session_id: str, root: Optional[Path] = None) -> Path:
    safe = _safe_session_id(session_id)
    return Path(root or AppMeta.RECORDINGS_DIR) / f"{safe}.flac"


def partial_recording_path(session_id: str, root: Optional[Path] = None) -> Path:
    safe = _safe_session_id(session_id)
    return Path(root or AppMeta.RECORDINGS_DIR) / f"{safe}.pcm.part"


def recording_info(session_id: str, root: Optional[Path] = None) -> dict[str, Any]:
    path = recording_path(session_id, root)
    if not path.is_file():
        return {"exists": False, "session_id": _safe_session_id(session_id)}
    stat = path.stat()
    info = sf.info(str(path))
    duration = float(info.frames) / float(info.samplerate) if info.samplerate else 0.0
    return {
        "exists": True,
        "session_id": _safe_session_id(session_id),
        "path": str(path),
        "size_bytes": stat.st_size,
        "duration_s": duration,
        "sample_rate": int(info.samplerate),
        "channels": int(info.channels),
        "format": "flac",
    }


def delete_recording(session_id: str, root: Optional[Path] = None) -> bool:
    deleted = False
    for path in (
        recording_path(session_id, root),
        partial_recording_path(session_id, root),
    ):
        try:
            path.unlink()
            deleted = True
        except FileNotFoundError:
            continue
    return deleted
