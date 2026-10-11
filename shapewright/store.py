"""
shapewright.store - disk-backed project storage.

A *project* is a directory containing:

    project.json          manifest: object list, measurements, op-log, seq
    <name>.<seq>.brep     one OpenCASCADE BREP file per solid version

BREP is the OCC-native format, so it is both compact and fast: a 40 mm box
round-trips in ~3 ms and occupies ~2.7 KB (STEP is ~10x slower and ~6x bigger).
Solids therefore live on disk and only a small LRU cache is held in RAM.

Versioned filenames (``<name>.<seq>.brep``) let undo keep pointing at older
versions, and :meth:`ProjectStore.gc` deletes anything no longer referenced.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import time
from collections import OrderedDict

from build123d import export_brep, import_brep

DEFAULT_ROOT = os.environ.get(
    "SHAPEWRIGHT_HOME",
    os.path.join(os.path.expanduser("~"), ".local", "share", "shapewright"),
)

_UNSAFE = re.compile(r"[^A-Za-z0-9_.-]+")


def safe_name(name: str) -> str:
    return _UNSAFE.sub("_", str(name)).strip("._-") or "part"


class ProjectStore:
    """One on-disk project directory."""

    def __init__(self, name: str, root: str | None = None, cache_size: int = 24):
        self.name = name
        self.root = os.path.abspath(root or DEFAULT_ROOT)
        self.dir = os.path.join(self.root, safe_name(name))
        os.makedirs(self.dir, exist_ok=True)
        self.cache_size = max(0, int(cache_size))
        self.manifest_path = os.path.join(self.dir, "project.json")

        self._cache: "OrderedDict[str, object]" = OrderedDict()
        self._seq = 0
        self.hits = 0
        self.misses = 0
        self.writes = 0

    # -- solids on disk ----------------------------------------------------
    def write(self, name: str, shape) -> str:
        """Persist a solid as a new version; returns its filename."""
        self._seq += 1
        rel = f"{safe_name(name)}.{self._seq:05d}.brep"
        export_brep(shape, os.path.join(self.dir, rel))
        self.writes += 1
        self._remember(rel, shape)
        return rel

    def read(self, rel: str):
        shape = self._cache.get(rel)
        if shape is not None:
            self.hits += 1
            self._cache.move_to_end(rel)
            return shape
        self.misses += 1
        shape = import_brep(os.path.join(self.dir, rel))
        self._remember(rel, shape)
        return shape

    def _remember(self, rel: str, shape) -> None:
        self._cache[rel] = shape
        self._cache.move_to_end(rel)
        while len(self._cache) > self.cache_size:
            self._cache.popitem(last=False)

    def forget(self, rel: str) -> None:
        self._cache.pop(rel, None)

    def remove_file(self, rel: str) -> None:
        self._cache.pop(rel, None)
        try:
            os.remove(os.path.join(self.dir, rel))
        except FileNotFoundError:
            pass

    def gc(self, live) -> int:
        """Delete BREP files not in ``live`` (a set of filenames)."""
        live = set(live)
        removed = 0
        for fn in os.listdir(self.dir):
            if fn.endswith(".brep") and fn not in live:
                self.remove_file(fn)
                removed += 1
        return removed

    def clear_cache(self) -> None:
        self._cache.clear()

    def cached(self) -> int:
        return len(self._cache)

    # -- manifest ----------------------------------------------------------
    def save_manifest(self, data: dict) -> None:
        data = {**data, "name": self.name, "seq": self._seq, "updated": time.time()}
        tmp = self.manifest_path + ".tmp"
        with open(tmp, "w") as fh:
            json.dump(data, fh, indent=2)
        os.replace(tmp, self.manifest_path)

    def load_manifest(self) -> dict:
        try:
            with open(self.manifest_path) as fh:
                return json.load(fh)
        except FileNotFoundError:
            return {}

    def adopt(self, manifest: dict) -> None:
        """Continue the version counter where a previous session left off."""
        self._seq = int(manifest.get("seq", 0) or 0)

    # -- info --------------------------------------------------------------
    def disk_usage(self) -> int:
        total = 0
        for fn in os.listdir(self.dir):
            p = os.path.join(self.dir, fn)
            if os.path.isfile(p):
                total += os.path.getsize(p)
        return total

    def stats(self) -> dict:
        return {
            "project": self.name,
            "path": self.dir,
            "cache_size": self.cache_size,
            "cached": self.cached(),
            "cache_hits": self.hits,
            "cache_misses": self.misses,
            "brep_writes": self.writes,
            "disk_bytes": self.disk_usage(),
        }


def list_projects(root: str | None = None) -> list[dict]:
    root = os.path.abspath(root or DEFAULT_ROOT)
    if not os.path.isdir(root):
        return []
    out = []
    for entry in sorted(os.listdir(root)):
        d = os.path.join(root, entry)
        if not os.path.isdir(d):
            continue
        man = os.path.join(d, "project.json")
        if not os.path.exists(man):
            continue
        try:
            with open(man) as fh:
                m = json.load(fh)
        except Exception:  # noqa: BLE001
            m = {}
        out.append({
            "name": m.get("name", entry),
            "path": d,
            "objects": len(m.get("objects", {})),
            "updated": m.get("updated"),
        })
    return out


def delete_project(name: str, root: str | None = None) -> bool:
    root = os.path.abspath(root or DEFAULT_ROOT)
    d = os.path.join(root, safe_name(name))
    if not os.path.isdir(d):
        return False
    shutil.rmtree(d)
    return True
