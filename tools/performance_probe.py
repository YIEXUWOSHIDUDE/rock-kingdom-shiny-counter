"""Isolated diagnostics: no DataStore, UI, real counts, images or OCR text saved.

Run from the source root with the release Python: -m tools.performance_probe --help.
Video mode replaces ONLY the capture adapter; decoding CPU is included and
explicitly labelled. It cannot validate desktop capture performance.
"""
from __future__ import annotations

import argparse
from contextlib import ExitStack
import json
import os
from pathlib import Path
import platform
import threading
import time
from unittest.mock import patch


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--video", type=Path)
    source.add_argument("--hwnd", type=int, help="Explicit user-selected game HWND only")
    parser.add_argument("--mode", choices=("paused", "capture", "full"), required=True)
    parser.add_argument("--seconds", type=float, default=30)
    parser.add_argument("--start", type=float, default=0)
    parser.add_argument("--clip-seconds", type=float, default=33.55)
    parser.add_argument("--repeats", type=int, default=1)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--cv-threads", type=int, choices=(1, 2))
    parser.add_argument("--torch-threads", type=int, choices=(1, 2))
    parser.add_argument("--batch-size", type=int, choices=(1, 4, 8))
    parser.add_argument("--capture-path", choices=("banner", "full"), default="banner",
                        help="Full is the old capture-and-crop baseline, diagnostic only")
    parser.add_argument("--trace-decisions", action="store_true", help="Bounded boolean/confidence timing trace; no text or pixels")
    parser.add_argument("--expected-count", type=int)
    args = parser.parse_args()
    if args.seconds <= 0 or args.clip_seconds <= 0 or args.repeats < 1:
        parser.error("durations and repeats must be positive")

    import cv2
    # Process-local experiments, once, before any worker/model starts. Omission
    # leaves library defaults untouched; no saved setting or runtime toggle.
    if args.cv_threads is not None:
        cv2.setNumThreads(args.cv_threads)
    if args.torch_threads is not None:
        import torch
        torch.set_num_threads(args.torch_threads)
    from PySide6.QtCore import Qt
    from shiny_counter.capture import WindowBinding, enable_dpi_awareness, list_windows
    from shiny_counter.ocr import EasyOCREngine, crop_notification_banner
    from shiny_counter.performance import PerformanceStats
    from shiny_counter.recognition import BannerRecognitionStream
    from shiny_counter.storage import AppSettings
    from shiny_counter.worker import CAPTURE_INTERVAL_SECONDS, RecognitionWorker

    enable_dpi_awareness()
    stats = PerformanceStats()
    settings = AppSettings()
    first_frame = None
    if args.video:
        video = cv2.VideoCapture(str(args.video))
        video.set(cv2.CAP_PROP_POS_MSEC, args.start * 1000)
        ok, first_frame = video.read()
        video.release()
        if not ok:
            raise RuntimeError("Cannot decode the supplied video")
        height, width = first_frame.shape[:2]
        binding = WindowBinding(hwnd=1, title="isolated video diagnostic", width=width, height=height)
    else:
        selected = next((w for w in list_windows() if w.hwnd == args.hwnd), None)
        if selected is None:
            raise RuntimeError("Selected game window is not available")
        binding = WindowBinding.from_window(selected)
    settings.set_window_binding(binding)
    metadata = {
        "source_version": Path("VERSION").read_text().strip(),
        "platform": platform.platform(), "logical_cpus": os.cpu_count(),
        "resolution": [binding.width, binding.height],
        "system_dpi": __import__("ctypes").windll.user32.GetDpiForSystem(),
        "window_dpi": None if args.video else __import__("ctypes").windll.user32.GetDpiForWindow(args.hwnd),
        "capture_interval_ms": CAPTURE_INTERVAL_SECONDS * 1000,
        "ocr_interval_ms": settings.ocr_interval_ms,
        "opencv_threads": cv2.getNumThreads(), "mode": args.mode,
        "source": "video_decode_not_desktop_capture" if args.video else "selected_game_window",
        "clip_start_seconds": args.start, "clip_seconds": args.clip_seconds,
        "repeats": args.repeats,
        "experiment": {"cv_threads": args.cv_threads, "torch_threads": args.torch_threads,
                       "batch_size": args.batch_size},
        "capture_path": args.capture_path,
    }
    if os.name == "nt":
        import winreg
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"HARDWARE\DESCRIPTION\System\CentralProcessor\0") as key:
            metadata["cpu"] = winreg.QueryValueEx(key, "ProcessorNameString")[0].strip()

    # Models are existing read-only inputs: no downloading or copying from installation.
    engine = None
    if args.mode == "full":
        started, cpu_started = time.perf_counter(), time.process_time()
        engine = EasyOCREngine(Path(os.environ["APPDATA"]) / "RockKingdomShinyCounter" / "ocr-models",
                               model_sources={}, experimental_batch_size=args.batch_size)
        import torch
        metadata.update(gpu=engine.device_label, torch_threads=torch.get_num_threads(),
                        torch_version=torch.__version__, cuda_version=torch.version.cuda)
        metadata["initialization"] = {"wall_seconds": time.perf_counter() - started,
                                      "cpu_seconds": time.process_time() - cpu_started}
        if first_frame is None:
            from shiny_counter.capture import Win32Capture
            capture = Win32Capture(binding)
            try:
                first_frame, _ = capture.capture_client((binding.width, binding.height))
            finally:
                capture.close()
        started, cpu_started = time.perf_counter(), time.process_time()
        engine.read(crop_notification_banner(first_frame, settings.recognition_profile()))
        torch.cuda.synchronize()
        metadata["warmup"] = {"wall_seconds": time.perf_counter() - started,
                              "cpu_seconds": time.process_time() - cpu_started}
        torch.cuda.reset_peak_memory_stats()

    class VideoCaptureAdapter:
        def __init__(self, binding):
            self.binding = binding
            self.video = cv2.VideoCapture(str(args.video))
            self.started = time.monotonic()
            self.phase = -1
            self.last = first_frame

        def capture_client(self, expected_size):
            started = time.perf_counter()
            elapsed = time.monotonic() - self.started
            if elapsed < args.clip_seconds * args.repeats:
                phase = int(elapsed / args.clip_seconds)
                target = args.start + elapsed % args.clip_seconds
                if self.phase != phase:
                    self.video.set(cv2.CAP_PROP_POS_MSEC, args.start * 1000)
                    self.phase = phase
                while self.video.grab():
                    if self.video.get(cv2.CAP_PROP_POS_MSEC) / 1000 >= target:
                        ok, frame = self.video.retrieve()
                        if ok:
                            self.last = frame
                        break
            stats.timing("video_decode", time.perf_counter() - started)
            return self.last, expected_size

        def close(self):
            self.video.release()

        def capture_banner(self, expected_size, profile):
            frame, size = self.capture_client(expected_size)
            return crop_notification_banner(frame, profile).copy(), size

    args.output.parent.mkdir(parents=True, exist_ok=True)
    worker = RecognitionWorker(settings, args.output.parent / "diagnostic-only", performance=stats)
    errors = []
    counts = []
    worker.stopped_with_error.connect(errors.append, Qt.ConnectionType.DirectConnection)
    worker.detected.connect(lambda _: counts.append(time.monotonic()), Qt.ConnectionType.DirectConnection)
    reports = []
    stop, ready = threading.Event(), threading.Event()
    init_errors = []
    stream = BannerRecognitionStream(settings, performance=stats)
    decision_trace = []
    original_observe = BannerRecognitionStream.observe

    def traced_observe(stream, sample, texts):
        result = original_observe(stream, sample, texts)
        if len(decision_trace) < 4096:
            decision_trace.append({
                "captured_seconds": sample.captured_at - started,
                "completed_seconds": time.monotonic() - started,
                "accepted": result.accepted, "matched": result.match is not None,
                "uncertain": result.uncertain,
                "confidence": result.match.confidence if result.match is not None else None,
                "counted": result.counted,
            })
        return result

    def full_frame_baseline(worker, capture, expected_size, frames):
        before = time.perf_counter()
        frame, _ = capture.capture_client(expected_size)
        captured_at = time.monotonic()
        stats.timing("capture_total", time.perf_counter() - before)
        stats.event("captures")
        before = time.perf_counter()
        frames.offer(frame, captured_at=captured_at)
        stats.timing("buffer_offer", time.perf_counter() - before)

    with ExitStack() as stack:
        if args.trace_decisions:
            stack.enter_context(patch.object(BannerRecognitionStream, "observe", traced_observe))
        if args.capture_path == "full":
            stack.enter_context(patch.object(RecognitionWorker, "_capture_offer", full_frame_baseline))
        if args.video:
            stack.enter_context(patch("shiny_counter.worker.Win32Capture", VideoCaptureAdapter))
        if engine:
            stack.enter_context(patch("shiny_counter.worker.EasyOCREngine", lambda _: engine))
        if args.mode == "full":
            runner = worker
        else:
            worker.set_paused(args.mode == "paused")
            stream.set_paused(args.mode == "paused")
            runner = threading.Thread(target=worker._capture_loop,
                                      args=(binding, stream, stop, ready, init_errors), daemon=True)
        stats.report()  # Discard initialization, model warmup, decoding setup.
        started = time.monotonic()
        runner.start()
        try:
            while time.monotonic() - started < args.seconds:
                remaining = args.seconds - (time.monotonic() - started)
                if remaining <= 0:
                    break
                stop.wait(min(5, remaining))
                report = stats.report()
                reports.append(report)
                print(json.dumps(report), flush=True)
                if errors or init_errors:
                    break
        finally:
            stop.set()
            worker.requestInterruption()
            stream.close()
            if args.mode == "full":
                if not worker.wait(15000):
                    raise RuntimeError("GPU worker did not stop within 15 seconds")
            else:
                runner.join(3)
                if runner.is_alive():
                    raise RuntimeError("Capture worker did not stop")
    if engine:
        metadata["gpu_peak_allocated_bytes"] = torch.cuda.max_memory_allocated()
        metadata["gpu_peak_reserved_bytes"] = torch.cuda.max_memory_reserved()
    result = {"metadata": metadata, "reports": reports, "count": len(counts),
              "errors": errors + [str(e) for e in init_errors],
              "limitations": "No UI or persistence. Video decode CPU is included in replay; not a live-game CPU baseline. No game smoothness acceptance."}
    if args.trace_decisions:
        result["decision_trace"] = decision_trace
    result["expected_count"] = args.expected_count
    if args.expected_count is not None and len(counts) != args.expected_count:
        result["errors"].append(f"Count mismatch: expected {args.expected_count}, observed {len(counts)}")
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"output": str(args.output), "count": len(counts), "errors": result["errors"]}), flush=True)
    if result["errors"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
