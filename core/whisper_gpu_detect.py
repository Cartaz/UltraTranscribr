"""Intel SYCL backend detection."""
from __future__ import annotations
import ctypes.util, logging, os, shutil, subprocess
from pathlib import Path
from typing import Optional
from config.constants import WhisperServerDefaults
logger=logging.getLogger(__name__)

def find_whisper_server(project_root: Optional[Path]=None) -> Optional[str]:
    root=project_root or Path(__file__).resolve().parent.parent
    for p in (root/".venv/bin"/WhisperServerDefaults.SERVER_BINARY_NAME,
              root/WhisperServerDefaults.SERVER_BINARY_NAME,
              root/"libexec"/WhisperServerDefaults.SERVER_BINARY_NAME):
        if p.is_file() and os.access(p, os.X_OK): return str(p)
    return shutil.which(WhisperServerDefaults.SERVER_BINARY_NAME)

def _check_level_zero_loader() -> bool:
    if ctypes.util.find_library("ze_loader"): return True
    return any(any(Path(p).glob("libze_loader.so*")) for p in ("/usr/lib","/usr/lib64","/usr/local/lib"))

def _check_intel_gpu() -> bool:
    try:
        out=subprocess.run(["lspci","-nn"],capture_output=True,text=True,timeout=5).stdout.lower()
        return "intel" in out and any(x in out for x in ("vga","display","3d controller"))
    except (OSError, subprocess.TimeoutExpired):
        return bool(shutil.which("sycl-ls") or shutil.which("clinfo"))

def _check_compute_runtime() -> bool:
    if shutil.which("sycl-ls") or shutil.which("clinfo"): return True
    return Path("/usr/lib/libze_intel_gpu.so").exists() or any(Path("/usr/lib").glob("libze_intel_gpu.so*"))

def is_sycl_available(project_root: Optional[Path]=None) -> bool:
    checks=(_check_level_zero_loader(), _check_compute_runtime(), _check_intel_gpu())
    logger.info("SYCL checks: LevelZero=%s runtime=%s IntelGPU=%s", *checks)
    return all(checks)

def detect_gpu_backend(project_root: Optional[Path]=None) -> str:
    return "sycl" if is_sycl_available(project_root) else "unavailable"

def _env(root: Optional[Path]) -> dict[str,str]:
    root=root or Path(__file__).resolve().parent.parent
    env=os.environ.copy(); paths=[]
    for p in (root/".venv/lib", root/"lib"):
        if p.is_dir(): paths.append(str(p))
    cur=env.get("LD_LIBRARY_PATH","")
    if paths: env["LD_LIBRARY_PATH"]=":".join(paths+([cur] if cur else []))
    return env

def verify_sycl_binary(binary_path: str, project_root: Optional[Path]=None) -> bool:
    env=_env(project_root)
    try:
        out=subprocess.run(["ldd",binary_path],capture_output=True,text=True,timeout=10,env=env)
        text=(out.stdout+out.stderr).lower()
        if any(k in text for k in ("libggml-sycl","libsycl","libze_loader")): return True
    except (OSError, subprocess.TimeoutExpired): pass
    try:
        out=subprocess.run([binary_path,"--version"],capture_output=True,text=True,timeout=10,env=env)
        text=(out.stdout+out.stderr).lower()
        return any(k in text for k in ("intelllvm","sycl","icx"))
    except (OSError, subprocess.TimeoutExpired): return False
