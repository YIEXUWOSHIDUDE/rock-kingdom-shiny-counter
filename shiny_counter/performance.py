"""Opt-in, bounded aggregate telemetry. Never stores pixels or recognized text."""
from __future__ import annotations

from collections import Counter, defaultdict, deque
import math
import os
import threading
import time


def process_rss_bytes() -> int | None:
    if os.name != "nt":
        return None
    import ctypes
    from ctypes import wintypes

    class MemoryCounters(ctypes.Structure):
        _fields_ = [("cb", wintypes.DWORD), ("PageFaultCount", wintypes.DWORD)] + [
            (name, ctypes.c_size_t) for name in (
                "PeakWorkingSetSize", "WorkingSetSize", "QuotaPeakPagedPoolUsage",
                "QuotaPagedPoolUsage", "QuotaPeakNonPagedPoolUsage",
                "QuotaNonPagedPoolUsage", "PagefileUsage", "PeakPagefileUsage",
            )
        ]

    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.GetCurrentProcess.restype = wintypes.HANDLE
    psapi = ctypes.WinDLL("psapi", use_last_error=True)
    psapi.GetProcessMemoryInfo.argtypes = [wintypes.HANDLE, ctypes.c_void_p, wintypes.DWORD]
    counters = MemoryCounters()
    counters.cb = ctypes.sizeof(counters)
    if not psapi.GetProcessMemoryInfo(kernel.GetCurrentProcess(), ctypes.byref(counters), counters.cb):
        return None
    return counters.WorkingSetSize


class PerformanceStats:
    """Mean covers each report interval; P95 uses its last 4096 observations.

    Reports are explicitly pulled by the diagnostic runner, not written per frame.
    Process CPU includes all native threads; stage elapsed is NOT CPU time.
    """

    def __init__(self, *, clock=time.perf_counter, cpu_clock=time.process_time):
        self._clock, self._cpu_clock = clock, cpu_clock
        self._lock = threading.Lock()
        self._started, self._cpu_started = clock(), cpu_clock()
        self._values = defaultdict(lambda: deque(maxlen=4096))
        self._totals = Counter()
        self._samples = Counter()
        self._events = Counter()
        self._gauges = {}

    def timing(self, name: str, seconds: float) -> None:
        with self._lock:
            self._values[name].append(seconds)
            self._totals[name] += seconds
            self._samples[name] += 1

    def event(self, name: str, count: int = 1) -> None:
        with self._lock:
            self._events[name] += count

    def gauge(self, name: str, value: float) -> None:
        with self._lock:
            self._gauges[name] = value
            maximum = name + "_max"
            self._gauges[maximum] = max(value, self._gauges.get(maximum, value))

    def report(self) -> dict:
        with self._lock:
            now, cpu = self._clock(), self._cpu_clock()
            elapsed, used = now - self._started, cpu - self._cpu_started
            stages = {}
            for name, values in self._values.items():
                ordered = sorted(values)
                stages[name] = {
                    "samples": self._samples[name],
                    "mean_ms": 1000 * self._totals[name] / self._samples[name],
                    "p95_ms": 1000 * ordered[math.ceil(.95 * len(ordered)) - 1],
                    "p95_samples": len(ordered),
                }
            result = {
                "wall_seconds": elapsed, "process_cpu_seconds": used,
                "cpu_one_core_percent": used / elapsed * 100 if elapsed else 0,
                "cpu_machine_percent": used / elapsed * 100 / (os.cpu_count() or 1) if elapsed else 0,
                "rss_bytes": process_rss_bytes(), "stages": stages,
                "events": dict(self._events), "gauges": dict(self._gauges),
                "captures_per_second": self._events["captures"] / elapsed if elapsed else 0,
                "ocr_per_second": self._events["ocr_calls"] / elapsed if elapsed else 0,
            }
            self._values.clear()
            self._totals.clear()
            self._samples.clear()
            self._events.clear()
            self._gauges.clear()
            self._started, self._cpu_started = now, cpu
            return result
