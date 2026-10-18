"""Finite, local webcam recipe; no API client, recording, or alert dispatch."""
import argparse
from collections import Counter
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import time

import numpy as np

from .pose import PoseModelUnavailable, assess_pose
from .tracking import GeometricTracker
from .yolo_pose import MODEL_ID, MODEL_SHA256, YoloPoseEstimator


def peak_memory_mb():
    if os.name != "nt":
        import resource
        return resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024
    import ctypes
    from ctypes import wintypes

    class Counters(ctypes.Structure):
        _fields_ = [("cb", wintypes.DWORD), ("PageFaultCount", wintypes.DWORD)] + [
            (name, ctypes.c_size_t) for name in (
                "PeakWorkingSetSize", "WorkingSetSize", "QuotaPeakPagedPoolUsage",
                "QuotaPagedPoolUsage", "QuotaPeakNonPagedPoolUsage",
                "QuotaNonPagedPoolUsage", "PagefileUsage", "PeakPagefileUsage",
            )
        ]

    counters = Counters()
    counters.cb = ctypes.sizeof(counters)
    get_process = ctypes.windll.kernel32.GetCurrentProcess
    get_process.restype = wintypes.HANDLE
    get_memory = ctypes.windll.psapi.GetProcessMemoryInfo
    get_memory.argtypes = [wintypes.HANDLE, ctypes.POINTER(Counters), wintypes.DWORD]
    if not get_memory(get_process(), ctypes.byref(counters), counters.cb):
        raise OSError("Mesure memoire Windows indisponible.")
    return counters.PeakWorkingSetSize / (1024 * 1024)


def run_recipe(reader, estimator, *, seconds=20, interval=0.5):
    tracker = GeometricTracker()
    counts, reasons = Counter(), Counter()
    latencies = []
    frames, frames_with_person, max_people = 0, 0, 0
    reader.open()
    try:
        time.sleep(1)
        started, cpu_started = time.perf_counter(), time.process_time()
        deadline = started + seconds
        while time.perf_counter() < deadline:
            frame = reader.read()
            height, width = frame.shape[:2]
            now = time.perf_counter()
            detections = estimator.detect(frame)
            latencies.append((time.perf_counter() - now) * 1000)
            tracked = tracker.update([
                {"label": "person", "confidence": item.confidence,
                 "bbox": [item.bbox[0] / width, item.bbox[1] / height,
                          (item.bbox[2] - item.bbox[0]) / width,
                          (item.bbox[3] - item.bbox[1]) / height],
                 "keypoints": item.keypoints}
                for item in detections
            ], time.monotonic())
            frames += 1
            frames_with_person += bool(tracked)
            max_people = max(max_people, len(tracked))
            for item in tracked:
                result = assess_pose(item["track_id"], item["keypoints"])
                counts[result.state.value] += 1
                reasons[result.reason] += 1
            # Release the only raw frame reference before pacing the next sample.
            del frame
            remaining = deadline - time.perf_counter()
            if remaining > 0:
                time.sleep(min(max(0.0, interval - (time.perf_counter() - now)), remaining))
        wall, cpu = time.perf_counter() - started, time.process_time() - cpu_started
    finally:
        reader.close()
    if not latencies:
        raise PoseModelUnavailable("Aucune mesure de posture dans la duree demandee.")
    return {
        "model_id": MODEL_ID, "model_sha256": MODEL_SHA256,
        "observed_at": datetime.now(timezone.utc).isoformat(),
        "frames": frames, "frames_with_person": frames_with_person,
        "max_people": max_people, "states": dict(counts), "reasons": dict(reasons),
        "duration_seconds": round(wall, 3), "cpu_seconds": round(cpu, 3),
        "cpu_percent_one_core": round(100 * cpu / wall, 2),
        "inference_ms_p50": round(float(np.percentile(latencies, 50)), 2),
        "inference_ms_p95": round(float(np.percentile(latencies, 95)), 2),
        "peak_process_memory_mb": round(peak_memory_mb(), 2),
        "images_saved": 0, "events_sent": 0,
        "scope": "isolated academic geometry; not a fall or intent detector",
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model-root", type=Path, required=True)
    parser.add_argument("--academic-use-acknowledged", action="store_true", required=True)
    parser.add_argument("--index", type=int, default=0)
    parser.add_argument("--seconds", type=float, default=20)
    parser.add_argument("--output", type=Path, required=True, help="Agregats JSON uniquement")
    args = parser.parse_args(argv)
    if not 2 <= args.seconds <= 120:
        parser.error("La duree doit etre comprise entre 2 et 120 secondes.")
    # Import the reader only for a real capture; no credentials are read.
    from .webcam import WebcamError, WebcamReader

    try:
        estimator = YoloPoseEstimator.from_registry(
            args.model_root, academic_use=args.academic_use_acknowledged,
        )
        result = run_recipe(WebcamReader(args.index), estimator, seconds=args.seconds)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(result, indent=2), encoding="utf-8")
        print(json.dumps(result))
        return 0 if result["frames_with_person"] else 2
    except (PoseModelUnavailable, WebcamError, OSError) as exc:
        print(json.dumps({"error": str(exc), "images_saved": 0, "events_sent": 0}))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
