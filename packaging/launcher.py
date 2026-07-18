from __future__ import annotations

import hashlib
import json
import multiprocessing
import sys
from pathlib import Path


def _write_runtime_info(destination: Path) -> int:
    import torch

    bundle_root = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
    model_root = bundle_root / "ocr-models"
    model_hashes: dict[str, str | None] = {}
    for name in ("craft_mlt_25k.pth", "zh_sim_g2.pth"):
        model = model_root / name
        model_hashes[name] = (
            hashlib.sha256(model.read_bytes()).hexdigest() if model.is_file() else None
        )

    payload = {
        "torch": torch.__version__,
        "cuda_build": torch.version.cuda,
        "cuda_available": torch.cuda.is_available(),
        "architectures": torch.cuda.get_arch_list(),
        "models": model_hashes,
    }
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return 0


def main() -> int:
    multiprocessing.freeze_support()
    if len(sys.argv) == 3 and sys.argv[1] == "--write-runtime-info":
        return _write_runtime_info(Path(sys.argv[2]))

    from shiny_counter.__main__ import main as application_main

    return application_main()


if __name__ == "__main__":
    raise SystemExit(main())
