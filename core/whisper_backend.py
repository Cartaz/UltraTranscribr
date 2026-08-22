"""whisper.cpp server lifecycle and optional multi-instance REST scheduler."""
from __future__ import annotations

import json
import logging
import os
import queue
import struct
import subprocess
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Callable, Optional

from config.constants import SYCLDefaults
from config.settings import Settings
from core.whisper_gpu_detect import find_whisper_server, verify_sycl_binary

logger = logging.getLogger(__name__)
_ENDPOINTS = ["/inference", "/v1/audio/transcriptions"]


def _alternate_endpoint(current: str) -> str:
    return next((ep for ep in _ENDPOINTS if ep != current), current)


class WhisperBackend:
    """Own one or more whisper-server processes behind one stable API.

    ``backend_instances=1`` deliberately keeps the historical single-server
    path unchanged. With more instances, requests are assigned FIFO to the
    first available server while each individual server still serializes its
    own HTTP requests. Ports are consecutive starting from ``server_port``.
    """

    def __init__(
        self,
        settings: Settings,
        project_root: Optional[Path] = None,
        *,
        instance_label: str = "",
    ) -> None:
        self._settings = settings
        self._project_root = project_root or Path(__file__).resolve().parent.parent
        self._instance_label = str(instance_label or "")
        self._process: Optional[subprocess.Popen[bytes]] = None
        self._server_binary: Optional[str] = None
        self._model_path: Optional[Path] = None
        self._vad_model_path: Optional[Path] = None
        self._log_file_handle: Optional[Any] = None
        self._api_endpoint = _ENDPOINTS[0]
        self._server_vad_enabled = False
        self._io_lock = threading.RLock()
        self._lifecycle_lock = threading.RLock()
        self._aux_backends: list[WhisperBackend] = []
        self._pool_queue: Optional[queue.Queue[int]] = None
        self._pool_stopping = False

    @property
    def server_url(self) -> str:
        return self._settings.server_url

    @property
    def is_running(self) -> bool:
        if self._pool_stopping:
            return False
        p = self._process
        primary = p is not None and p.poll() is None
        if not primary:
            return False
        return all(backend.is_running for backend in self._aux_backends)

    @property
    def api_endpoint(self) -> str:
        return self._api_endpoint

    @property
    def server_vad_enabled(self) -> bool:
        return self._server_vad_enabled

    @property
    def instance_count(self) -> int:
        return 1 + len(self._aux_backends) if self._process is not None else 0

    def start(self, model_path: Path, vad_model_path: Optional[Path] = None) -> None:
        with self._lifecycle_lock:
            self._pool_stopping = True
            self._cleanup_aux_backends()
            self._model_path = Path(model_path)
            self._vad_model_path = Path(vad_model_path) if vad_model_path else None
            self._server_binary = find_whisper_server(self._project_root)
            if not self._server_binary:
                self._pool_stopping = False
                raise RuntimeError("whisper-server non trovato. Eseguire install.sh.")
            if not verify_sycl_binary(self._server_binary, self._project_root):
                self._pool_stopping = False
                raise RuntimeError(f"whisper-server non compilato con SYCL: {self._server_binary}")
            use_vad = bool(self._settings.vad_filter and self._vad_model_path)
            try:
                self._spawn(use_vad)
                self._detect_api_endpoint()
                self._start_aux_backends(use_vad)
                self._reset_pool_queue()
            except Exception:
                self._cleanup_aux_backends()
                self._cleanup_process()
                self._pool_stopping = False
                raise
            self._pool_stopping = False

    def ensure_vad_mode(self, enabled: bool, vad_model_path: Optional[Path] = None) -> None:
        with self._lifecycle_lock:
            if vad_model_path is not None:
                self._vad_model_path = Path(vad_model_path)
            wanted = bool(enabled and self._vad_model_path)
            all_same = self._server_vad_enabled == wanted and all(
                backend.server_vad_enabled == wanted for backend in self._aux_backends
            )
            if self.is_running and all_same:
                return
            if self._model_path is None:
                raise RuntimeError("Backend non inizializzato")
            self._pool_stopping = True
            try:
                self._cleanup_aux_backends()
                self._cleanup_process()
                self._spawn(wanted)
                self._detect_api_endpoint()
                self._start_aux_backends(wanted)
                self._reset_pool_queue()
            except Exception:
                self._cleanup_aux_backends()
                self._cleanup_process()
                raise
            finally:
                self._pool_stopping = False

    def stop(self) -> None:
        with self._lifecycle_lock:
            self._pool_stopping = True
            self._cleanup_process()
            self._cleanup_aux_backends()

    def abort_active_request(self) -> None:
        with self._lifecycle_lock:
            self._pool_stopping = True
            self._cleanup_process()
            self._cleanup_aux_backends()

    def transcribe_audio(
        self,
        audio_data: bytes,
        language: Optional[str] = None,
        prompt: Optional[str] = None,
        verbose: bool = False,
        *,
        timeout: Optional[float] = None,
        vad: Optional[bool] = None,
        on_queue_wait: Optional[Callable[[float], None]] = None,
    ) -> str | dict:
        del vad
        if not self._aux_backends:
            return self._transcribe_single(
                audio_data,
                language=language,
                prompt=prompt,
                verbose=verbose,
                timeout=timeout,
                on_queue_wait=on_queue_wait,
            )

        if not self.is_running:
            raise RuntimeError("whisper-server non in esecuzione")
        pool = self._pool_queue
        if pool is None:
            raise RuntimeError("pool whisper-server non inizializzato")

        queued_at = time.monotonic()
        index: Optional[int] = None
        while index is None:
            if not self.is_running:
                raise RuntimeError("whisper-server non in esecuzione")
            try:
                index = pool.get(timeout=0.2)
            except queue.Empty:
                continue

        wait_ms = max(0.0, (time.monotonic() - queued_at) * 1000.0)
        if on_queue_wait is not None:
            try:
                on_queue_wait(wait_ms)
            except Exception:
                logger.exception("Callback metrica coda inferenza fallita")

        try:
            if not self.is_running:
                raise RuntimeError("whisper-server non in esecuzione")
            backend = self if index == 0 else self._aux_backends[index - 1]
            return backend._transcribe_single(
                audio_data,
                language=language,
                prompt=prompt,
                verbose=verbose,
                timeout=timeout,
                on_queue_wait=None,
            )
        finally:
            pool.put(index)

    def _transcribe_single(
        self,
        audio_data: bytes,
        *,
        language: Optional[str],
        prompt: Optional[str],
        verbose: bool,
        timeout: Optional[float],
        on_queue_wait: Optional[Callable[[float], None]],
    ) -> str | dict:
        if self._pool_stopping or not self._process_running():
            raise RuntimeError("whisper-server non in esecuzione")
        timeout_s = float(timeout or SYCLDefaults.LIVE_REQUEST_TIMEOUT_S)
        queued_at = time.monotonic()
        with self._io_lock:
            wait_ms = max(0.0, (time.monotonic() - queued_at) * 1000.0)
            if on_queue_wait is not None:
                try:
                    on_queue_wait(wait_ms)
                except Exception:
                    logger.exception("Callback metrica coda inferenza fallita")
            if self._pool_stopping or not self._process_running():
                raise RuntimeError("whisper-server non in esecuzione")
            last_error: Exception | None = None
            for _ in range(len(_ENDPOINTS)):
                endpoint = self._api_endpoint
                boundary = "----UltraTranscribrBoundary"
                body = self._build_multipart(
                    audio_data,
                    language,
                    boundary,
                    openai_compat=endpoint != "/inference",
                    prompt=prompt,
                    verbose=verbose,
                )
                req = urllib.request.Request(
                    f"{self.server_url}{endpoint}",
                    data=body,
                    headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
                    method="POST",
                )
                try:
                    with urllib.request.urlopen(req, timeout=timeout_s) as resp:
                        result = json.loads(resp.read().decode("utf-8"))
                    return result if verbose else result.get("text", "")
                except urllib.error.HTTPError as exc:
                    detail = self._error_body(exc)
                    if exc.code == 404:
                        self._api_endpoint = _alternate_endpoint(endpoint)
                        last_error = exc
                        continue
                    raise RuntimeError(
                        f"Trascrizione fallita: HTTP {exc.code} su {endpoint}: {detail}"
                    ) from exc
                except (urllib.error.URLError, TimeoutError, OSError) as exc:
                    raise RuntimeError(f"Trascrizione fallita su {endpoint}: {exc}") from exc
            raise RuntimeError("Nessun endpoint di trascrizione disponibile") from last_error

    def _process_running(self) -> bool:
        p = self._process
        return p is not None and p.poll() is None

    def _start_aux_backends(self, use_vad: bool) -> None:
        if self._instance_label:
            return
        count = int(self._settings.backend_instances)
        if count <= 1:
            return
        if self._model_path is None:
            raise RuntimeError("Backend non configurato")
        for index in range(1, count):
            cfg = self._settings.with_(
                server_port=self._settings.server_port + index,
                backend_instances=1,
                preload_model=False,
                vad_filter=use_vad,
            )
            backend = WhisperBackend(
                cfg,
                self._project_root,
                instance_label=f"-{index + 1}",
            )
            try:
                backend.start(self._model_path, self._vad_model_path)
            except Exception:
                backend.stop()
                raise
            self._aux_backends.append(backend)
        logger.info(
            "Pool whisper-server attivo: %d istanze sulle porte %d-%d",
            count,
            self._settings.server_port,
            self._settings.server_port + count - 1,
        )

    def _cleanup_aux_backends(self) -> None:
        backends = self._aux_backends
        self._aux_backends = []
        self._pool_queue = None
        for backend in backends:
            try:
                backend.stop()
            except Exception:
                logger.exception("Arresto istanza whisper-server ausiliaria fallito")

    def _reset_pool_queue(self) -> None:
        if not self._aux_backends:
            self._pool_queue = None
            return
        pool: queue.Queue[int] = queue.Queue(maxsize=1 + len(self._aux_backends))
        for index in range(1 + len(self._aux_backends)):
            pool.put_nowait(index)
        self._pool_queue = pool

    def _spawn(self, use_vad: bool) -> None:
        if self._model_path is None or self._server_binary is None:
            raise RuntimeError("Backend non configurato")
        self._cleanup_process()
        log_path = self._server_log_path()
        self._log_file_handle = open(log_path, "w", encoding="utf-8")
        cmd = self._build_cmd(self._model_path, use_vad)
        logger.info("Avvio whisper-server%s: %s", self._instance_label, " ".join(cmd))
        self._process = subprocess.Popen(
            cmd,
            env=self._build_env(),
            stdout=self._log_file_handle,
            stderr=subprocess.STDOUT,
        )
        try:
            self._wait_for_health()
        except Exception:
            self._cleanup_process()
            raise
        self._server_vad_enabled = use_vad

    def _cleanup_process(self) -> None:
        p = self._process
        self._process = None
        if p is not None and p.poll() is None:
            try:
                p.terminate()
                p.wait(timeout=3.0)
            except subprocess.TimeoutExpired:
                p.kill()
                try:
                    p.wait(timeout=2.0)
                except subprocess.TimeoutExpired:
                    pass
            except OSError:
                pass
        if self._log_file_handle and not self._log_file_handle.closed:
            try:
                self._log_file_handle.close()
            except OSError:
                pass
        self._log_file_handle = None
        self._server_vad_enabled = False

    def _build_cmd(self, model_path: Path, vad: bool) -> list[str]:
        assert self._server_binary
        cmd = [
            self._server_binary,
            "-m",
            str(model_path),
            "--port",
            str(self._settings.server_port),
            "--host",
            SYCLDefaults.HOST,
            "--split-on-word",
            "--no-fallback",
            "--beam-size",
            str(self._settings.beam_size),
        ]
        if vad:
            if not self._vad_model_path:
                raise RuntimeError("VAD richiesto ma modello VAD non disponibile")
            cmd += [
                "--vad",
                "--vad-model",
                str(self._vad_model_path),
                "--vad-threshold",
                str(SYCLDefaults.VAD_THRESHOLD),
                "--vad-min-silence-duration-ms",
                str(self._settings.vad_min_silence_ms),
            ]
        return cmd

    def _build_env(self) -> dict[str, str]:
        env = os.environ.copy()
        env["GGML_SYCL"] = "1"
        env["ONEAPI_DEVICE_SELECTOR"] = SYCLDefaults.ONEAPI_DEVICE_SELECTOR
        env["ZES_ENABLE_SYSMAN"] = "1"
        ld_paths = []
        for candidate in (
            self._project_root / ".venv" / "lib",
            self._project_root / "lib",
        ):
            if candidate.is_dir():
                ld_paths.append(str(candidate))
        oneapi = Path("/opt/intel/oneapi")
        if oneapi.is_dir():
            for lib_dir in oneapi.glob("*/*/lib"):
                if lib_dir.is_dir():
                    ld_paths.append(str(lib_dir))
            for lib_dir in oneapi.glob("tbb/*/lib/intel64/gcc4.8"):
                if lib_dir.is_dir():
                    ld_paths.append(str(lib_dir))
        if ld_paths:
            current = env.get("LD_LIBRARY_PATH", "")
            env["LD_LIBRARY_PATH"] = ":".join(ld_paths + ([current] if current else []))
        return env

    def _wait_for_health(self) -> None:
        deadline = time.monotonic() + SYCLDefaults.HEALTH_TIMEOUT_S
        url = f"{self.server_url}/health"
        while time.monotonic() < deadline:
            p = self._process
            if p is None or p.poll() is not None:
                raise RuntimeError(f"whisper-server terminato. Log: {self._read_log_tail()}")
            try:
                with urllib.request.urlopen(url, timeout=2.0) as resp:
                    if resp.status == 200:
                        return
            except (urllib.error.URLError, OSError):
                pass
            time.sleep(SYCLDefaults.HEALTH_POLL_INTERVAL_S)
        raise RuntimeError("whisper-server non ha risposto al health check")

    def _detect_api_endpoint(self) -> None:
        silent = self._make_silent_wav()
        for endpoint in _ENDPOINTS:
            boundary = "----UltraTranscribrProbe"
            body = self._build_multipart(
                silent,
                None,
                boundary,
                openai_compat=endpoint != "/inference",
            )
            req = urllib.request.Request(
                f"{self.server_url}{endpoint}",
                data=body,
                headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
                method="POST",
            )
            try:
                with urllib.request.urlopen(
                    req,
                    timeout=SYCLDefaults.ENDPOINT_PROBE_TIMEOUT_S,
                ) as resp:
                    if 200 <= resp.status < 300:
                        self._api_endpoint = endpoint
                        return
            except urllib.error.HTTPError as exc:
                if exc.code in (400, 405, 415, 422):
                    self._api_endpoint = endpoint
                    return
                if exc.code == 404 or exc.code >= 500:
                    continue
            except (urllib.error.URLError, OSError):
                continue
        self._api_endpoint = "/inference"

    def _server_log_path(self) -> Path:
        name = f"whisper-server{self._instance_label}.log"
        path = self._project_root / ".venv" / name
        if not path.parent.exists():
            path = self._project_root / name
        return path

    def _read_log_tail(self, chars: int = 2500) -> str:
        path = self._server_log_path()
        try:
            return path.read_text(encoding="utf-8", errors="replace")[-chars:]
        except OSError:
            return "(log non disponibile)"

    @staticmethod
    def _error_body(exc: urllib.error.HTTPError) -> str:
        try:
            return exc.read().decode("utf-8", errors="replace")[:500]
        except Exception:
            return ""

    @staticmethod
    def _make_silent_wav() -> bytes:
        return struct.pack(
            "<4sI4s4sIHHIIHH4sI",
            b"RIFF",
            36,
            b"WAVE",
            b"fmt ",
            16,
            1,
            1,
            16000,
            32000,
            2,
            16,
            b"data",
            0,
        )

    def _build_multipart(
        self,
        audio_data: bytes,
        language: Optional[str],
        boundary: str,
        openai_compat: bool = True,
        prompt: Optional[str] = None,
        verbose: bool = False,
    ) -> bytes:
        fields: list[tuple[str, str]] = []
        if language:
            fields.append(("language", language))
        if prompt and prompt.strip():
            fields.append(("prompt", prompt.strip()))
        fields += [
            ("temperature", "0.0"),
            ("temperature_inc", "0.0"),
            ("response_format", "verbose_json" if verbose else "json"),
            ("beam_size", str(self._settings.beam_size)),
        ]
        if openai_compat:
            fields.append(("model", "whisper-1"))
        parts: list[bytes] = [
            f"--{boundary}\r\n".encode(),
            b'Content-Disposition: form-data; name="file"; filename="audio.wav"\r\n',
            b"Content-Type: audio/wav\r\n\r\n",
            audio_data,
            b"\r\n",
        ]
        for name, value in fields:
            parts += [
                f"--{boundary}\r\n".encode(),
                f'Content-Disposition: form-data; name="{name}"\r\n\r\n'.encode(),
                f"{value}\r\n".encode(),
            ]
        parts.append(f"--{boundary}--\r\n".encode())
        return b"".join(parts)
