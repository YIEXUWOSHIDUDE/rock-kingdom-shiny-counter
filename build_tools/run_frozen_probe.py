from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path


def resolve_probe_paths(executable: Path, report: Path) -> tuple[Path, Path]:
    return executable.resolve(), report.resolve()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("executable", type=Path)
    parser.add_argument("mode", choices=("package", "runtime"))
    parser.add_argument("report", type=Path)
    parser.add_argument("--timeout", type=int, default=300)
    args = parser.parse_args()
    args.executable, args.report = resolve_probe_paths(
        args.executable,
        args.report,
    )
    args.report.unlink(missing_ok=True)
    try:
        process = subprocess.run(
            [
                str(args.executable),
                "--probe-" + args.mode,
                str(args.report),
            ],
            cwd=args.executable.parent,
            capture_output=True,
            text=True,
            timeout=args.timeout,
            check=False,
        )
    except Exception as error:
        print(f"无法运行冻结包探针：{error}", file=sys.stderr)
        return 5
    if not args.report.is_file():
        print(
            "冻结包没有生成探针报告。\n"
            + process.stdout
            + "\n"
            + process.stderr,
            file=sys.stderr,
        )
        return 5
    payload = json.loads(args.report.read_text(encoding="utf-8"))
    print(json.dumps(payload, ensure_ascii=False))
    return 0 if process.returncode == 0 and payload.get("ok") else 5


if __name__ == "__main__":
    raise SystemExit(main())
