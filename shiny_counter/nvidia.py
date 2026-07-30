from __future__ import annotations

import subprocess
from collections.abc import Callable

from .gpu_policy import NvidiaGPUInfo


def query_nvidia_gpu(
    *,
    run: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
) -> NvidiaGPUInfo | None:
    """Return the first NVIDIA GPU and driver reported by nvidia-smi."""
    try:
        process = run(
            [
                "nvidia-smi.exe",
                "--query-gpu=name,driver_version",
                "--format=csv,noheader",
            ],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if process.returncode != 0:
        return None
    for line in process.stdout.splitlines():
        if not line.strip() or "," not in line:
            continue
        name, driver_version = line.rsplit(",", 1)
        name = name.strip()
        driver_version = driver_version.strip()
        if name:
            return NvidiaGPUInfo(name=name, driver_version=driver_version)
    return None
