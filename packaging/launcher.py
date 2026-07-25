from __future__ import annotations

import multiprocessing
import subprocess
import sys
from pathlib import Path

if not hasattr(sys, "_MEIPASS"):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def _probe_runtime(destination: Path) -> int:
    bundle_root = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
    model_root = bundle_root / "ocr-models"
    from shiny_counter.runtime_probe import (
        RuntimeProbeReport,
        probe_gpu_runtime,
        write_runtime_probe_report,
    )

    try:
        import easyocr
        import torch

        report = probe_gpu_runtime(
            model_root,
            torch_module=torch,
            easyocr_module=easyocr,
            probe_image_path=bundle_root / "ocr-probe" / "ocr-probe.png",
            driver_version=_nvidia_driver_version(),
        )
    except Exception as error:
        report = RuntimeProbeReport(
            ok=False,
            stage="dependency_import",
            message=str(error),
            details={"error_type": type(error).__name__},
        )
    return write_runtime_probe_report(destination, report)


def _nvidia_driver_version() -> str:
    try:
        process = subprocess.run(
            [
                "nvidia-smi.exe",
                "--query-gpu=driver_version",
                "--format=csv,noheader",
            ],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        if process.returncode == 0:
            return process.stdout.splitlines()[0].strip()
    except (OSError, subprocess.SubprocessError, IndexError):
        pass
    return ""


def _probe_package(destination: Path) -> int:
    bundle_root = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
    from shiny_counter.package_probe import probe_packaged_dependencies
    from shiny_counter.runtime_probe import write_runtime_probe_report

    report = probe_packaged_dependencies(bundle_root)
    return write_runtime_probe_report(destination, report)


def main() -> int:
    multiprocessing.freeze_support()
    if len(sys.argv) == 3 and sys.argv[1] == "--probe-package":
        return _probe_package(Path(sys.argv[2]))
    if len(sys.argv) == 3 and sys.argv[1] in {
        "--probe-runtime",
        "--write-runtime-info",
    }:
        return _probe_runtime(Path(sys.argv[2]))

    from shiny_counter.__main__ import main as application_main

    return application_main()


if __name__ == "__main__":
    raise SystemExit(main())
