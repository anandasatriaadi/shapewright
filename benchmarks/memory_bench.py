"""
Benchmark: in-memory scene vs disk-backed project.

Runs each scenario in its own subprocess so RSS is isolated, then reports
retained memory (after gc + malloc_trim), peak RSS, wall time, and disk use.

    python benchmarks/memory_bench.py                 # 200 parts
    python benchmarks/memory_bench.py --n 400 --cache 8
"""

from __future__ import annotations

import argparse
import ctypes
import gc
import json
import os
import resource
import subprocess
import sys
import tempfile
import time


def rss_kb() -> int:
    with open("/proc/self/status") as fh:
        for line in fh:
            if line.startswith("VmRSS"):
                return int(line.split()[1])
    return -1


def _trim() -> None:
    try:
        ctypes.CDLL("libc.so.6").malloc_trim(0)
    except Exception:  # noqa: BLE001
        pass


def retained_kb() -> int:
    gc.collect()
    _trim()
    return rss_kb()


def build(scene, n: int) -> None:
    for i in range(n):
        scene.box(f"p{i}", 30, 20, 10)
        scene.fillet(f"p{i}", 1.0, "parallel:Z")


def scenario(kind: str, n: int, cache: int) -> dict:
    from shapewright.scene import Scene

    baseline = retained_kb()
    root = None
    if kind == "mem":
        scene = Scene()
    else:
        root = tempfile.mkdtemp(prefix="swbench_")
        scene = Scene.open("bench", root=root, cache_size=cache)

    t0 = time.perf_counter()
    build(scene, n)
    build_s = time.perf_counter() - t0

    peak_mb = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024
    after = retained_kb()

    t0 = time.perf_counter()
    for _ in range(3):
        scene.list_objects()
    list_ms = (time.perf_counter() - t0) / 3 * 1000

    out = {
        "kind": kind, "n": n,
        "objects": len(scene.names()),
        "baseline_mb": round(baseline / 1024, 1),
        "retained_mb": round(after / 1024, 1),
        "growth_mb": round((after - baseline) / 1024, 1),
        "peak_mb": round(peak_mb, 1),
        "build_s": round(build_s, 3),
        "list_objects_ms": round(list_ms, 3),
    }
    if kind == "disk":
        stats = scene.cache_stats()
        out["cached_shapes"] = stats["cached"]
        out["disk_kb"] = round(stats["disk_bytes"] / 1024, 1)
        out["cache_misses"] = stats["cache_misses"]
        t0 = time.perf_counter()
        Scene.open("bench", root=root, cache_size=cache)
        out["reopen_s"] = round(time.perf_counter() - t0, 4)
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--child", choices=["mem", "disk"])
    ap.add_argument("--n", type=int, default=200)
    ap.add_argument("--cache", type=int, default=8)
    args = ap.parse_args()

    if args.child:
        print(json.dumps(scenario(args.child, args.n, args.cache)))
        return

    rows = []
    for kind in ("mem", "disk"):
        proc = subprocess.run(
            [sys.executable, os.path.abspath(__file__),
             "--child", kind, "--n", str(args.n), "--cache", str(args.cache)],
            capture_output=True, text=True,
        )
        payload = [ln for ln in proc.stdout.splitlines() if ln.strip().startswith("{")]
        rows.append(json.loads(payload[-1]) if payload else
                    {"kind": kind, "error": proc.stderr.strip()[-400:]})

    print(f"\n{args.n} parts (box + fillet each), disk cache_size={args.cache}\n")
    hdr = f"{'scenario':<10}{'retained MB':>12}{'growth MB':>11}{'peak MB':>9}{'build s':>9}{'list ms':>9}"
    print(hdr)
    print("-" * len(hdr))
    for r in rows:
        if "error" in r:
            print(f"{r['kind']:<10}  ERROR: {r['error']}")
            continue
        print(f"{r['kind']:<10}{r['retained_mb']:>12}{r['growth_mb']:>11}"
              f"{r['peak_mb']:>9}{r['build_s']:>9}{r['list_objects_ms']:>9}")
    for r in rows:
        if r.get("kind") == "disk":
            print(f"\ndisk: {r['disk_kb']} KB for {r['objects']} parts, "
                  f"{r['cached_shapes']} shapes cached, "
                  f"{r['cache_misses']} cache misses, reopen {r['reopen_s']*1000:.1f} ms")
    if len(rows) == 2 and "growth_mb" in rows[0] and "growth_mb" in rows[1]:
        saved = rows[0]["growth_mb"] - rows[1]["growth_mb"]
        pct = 100 * saved / rows[0]["growth_mb"] if rows[0]["growth_mb"] else 0
        print(f"memory saved by disk mode: {saved:.1f} MB ({pct:.0f}%)")


if __name__ == "__main__":
    main()
