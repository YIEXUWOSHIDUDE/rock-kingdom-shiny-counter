"""Deterministic conversion/buffering comparison, NOT desktop/GDI performance.

Both paths use the real Win32Capture conversion and real recognition buffer.
Only the screen backend and original geometry are simulated from one fixed image.
No screenshot is saved. Equal iteration counts; uncapped microbenchmark, not a
change to the app's default sampling frequency.
"""
import argparse
import json
from pathlib import Path

import numpy as np

from shiny_counter.capture import Win32Capture
from shiny_counter.performance import PerformanceStats
from shiny_counter.recognition import BannerRecognitionStream
from shiny_counter.storage import AppSettings


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    pixels = np.random.default_rng(0).integers(0, 256, (1600, 2560, 4), dtype=np.uint8)

    class Backend:
        def grab(self, region):
            x, y, w, h = (region[key] for key in ("left", "top", "width", "height"))
            return pixels[y:y+h, x:x+w]

    results = []
    for repeat in range(3):
        for mode in (("full", "banner") if repeat % 2 == 0 else ("banner", "full")):
            stats = PerformanceStats()
            capture = Win32Capture.__new__(Win32Capture)
            capture._mss = Backend()
            capture._geometry = lambda size: (42, 0, 0, 2560, 1600)
            capture.performance = stats
            stream = BannerRecognitionStream(AppSettings(), performance=stats)
            for _ in range(200):
                if mode == "full":
                    frame, _ = capture.capture_client((2560, 1600))
                    stream.offer(frame)
                else:
                    frame, _ = capture.capture_banner((2560, 1600), stream.profile)
                    stream.offer_banner(frame)
            results.append({"repeat": repeat + 1, "mode": mode, "iterations": 200, **stats.report()})
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps({"scope": "Simulated backend: conversion and buffering only; no real desktop capture or FPS claim", "results": results}, indent=2), encoding="utf-8")
    for result in results:
        print(json.dumps({key: result[key] for key in ("repeat", "mode", "wall_seconds", "process_cpu_seconds", "stages")}))


if __name__ == "__main__":
    main()
