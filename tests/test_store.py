"""Tests for disk-backed projects: persistence, lazy loading, LRU cache, gc."""

from __future__ import annotations

import os
import tempfile
import unittest

from shapewright.scene import Scene
from shapewright.store import ProjectStore, delete_project, list_projects, safe_name


def _design(s: Scene) -> None:
    s.box("plate", 60, 40, 10, corner=3)
    s.cylinder("bore", 6, 40)
    s.subtract("plate", ["bore"])
    s.cylinder("boss", 12, 16, at=(0, 0, 10))
    s.union("plate", ["plate", "boss"])
    s.fillet("plate", 2, "type:circle & at:zmax")


class TestProjectStore(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp(prefix="swstore_")

    def test_roundtrip_preserves_geometry(self):
        s = Scene.open("p", root=self.root, cache_size=0)
        s.box("b", 40, 40, 10)
        ref = s._ref["b"]
        self.assertTrue(os.path.exists(os.path.join(s.store.dir, ref)))
        s.store.clear_cache()
        back = s.get("b")
        self.assertAlmostEqual(back.volume, 16000.0, places=3)

    def test_lru_cache_is_bounded(self):
        store = ProjectStore("c", root=self.root, cache_size=2)
        for i in range(5):
            store.write(f"o{i}", __import__("build123d").Box(10, 10, 10))
        self.assertEqual(store.cached(), 2)
        store.read("o0.00001.brep")           # evicted -> must hit disk
        self.assertGreaterEqual(store.misses, 1)

    def test_gc_removes_unreferenced(self):
        store = ProjectStore("g", root=self.root, cache_size=4)
        a = store.write("a", __import__("build123d").Box(10, 10, 10))
        b = store.write("b", __import__("build123d").Box(10, 10, 10))
        removed = store.gc({a})
        self.assertEqual(removed, 1)
        self.assertFalse(os.path.exists(os.path.join(store.dir, b)))

    def test_manifest_and_seq_adoption(self):
        store = ProjectStore("m", root=self.root)
        store.write("a", __import__("build123d").Box(10, 10, 10))
        store.write("b", __import__("build123d").Box(10, 10, 10))
        store.save_manifest({"objects": {}, "code": []})
        again = ProjectStore("m", root=self.root)
        again.adopt(again.load_manifest())
        self.assertEqual(again._seq, store._seq)

    def test_safe_name(self):
        self.assertEqual(safe_name("my part/v2"), "my_part_v2")
        self.assertEqual(safe_name(""), "part")

    def test_list_and_delete_project(self):
        Scene.open("keepme", root=self.root).box("b", 10, 10, 10)
        names = [p["name"] for p in list_projects(self.root)]
        self.assertIn("keepme", names)
        self.assertTrue(delete_project("keepme", self.root))
        self.assertFalse(delete_project("keepme", self.root))


class TestPersistentScene(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp(prefix="swscene_")

    def test_listing_never_loads_geometry(self):
        s = Scene.open("lazy", root=self.root, cache_size=0)
        _design(s)
        s.store.misses = 0
        listing = s.list_objects()
        self.assertEqual(s.store.misses, 0)      # metadata only
        self.assertEqual(len(listing), 3)
        s.get("plate")
        self.assertEqual(s.store.misses, 1)      # geometry only when needed

    def test_shapes_are_evicted(self):
        s = Scene.open("evict", root=self.root, cache_size=1)
        _design(s)
        self.assertLessEqual(s.cache_stats()["cached"], 1)

    def test_reopen_restores_without_loading(self):
        s = Scene.open("reopen", root=self.root)
        _design(s)
        s.flush()
        expect = {n: s.info(n)["volume_cm3"] for n in s.names()}

        s2 = Scene.open("reopen", root=self.root)
        self.assertEqual(sorted(s2.names()), sorted(expect))
        self.assertEqual(s2.cache_stats()["cached"], 0)      # lazy on open
        self.assertTrue(s2.code)                             # op-log kept
        for name, vol in expect.items():
            self.assertAlmostEqual(s2.info(name)["volume_cm3"], vol, places=6)

    def test_undo_keeps_needed_versions(self):
        s = Scene.open("undo", root=self.root, cache_size=4)
        _design(s)
        before = s.info("plate")["volume_cm3"]
        s.cylinder("extra", 5, 30)
        s.subtract("plate", ["extra"])
        self.assertNotAlmostEqual(s.info("plate")["volume_cm3"], before)
        self.assertTrue(s.undo())
        self.assertAlmostEqual(s.info("plate")["volume_cm3"], before, places=6)

    def test_delete_then_gc(self):
        s = Scene.open("del", root=self.root)
        s.box("a", 10, 10, 10)
        s.box("b", 10, 10, 10)
        b_path = os.path.join(s.store.dir, s._ref["b"])
        s.delete("b")
        s._gc()
        # still on disk: undo can bring it back
        self.assertTrue(os.path.exists(b_path))
        self.assertTrue(s.undo())
        self.assertIn("b", s.names())
        # once no undo step references it, gc removes the file
        s.delete("b")
        s._undo.clear()
        s._gc()
        self.assertFalse(os.path.exists(b_path))

    def test_reset_clears(self):
        s = Scene.open("reset", root=self.root)
        _design(s)
        s.reset()
        self.assertEqual(s.names(), [])

    def test_duplicate_copies_to_disk(self):
        s = Scene.open("dup", root=self.root)
        s.box("a", 10, 10, 10)
        s.duplicate("a", "a2")
        self.assertIn("a2", s.names())
        self.assertAlmostEqual(s.info("a2")["volume_cm3"], s.info("a")["volume_cm3"], places=6)

    def test_parity_with_in_memory(self):
        mem = Scene()
        _design(mem)
        disk = Scene.open("parity", root=self.root)
        _design(disk)
        self.assertEqual(mem.names(), disk.names())
        for name in mem.names():
            self.assertEqual(mem.info(name)["bbox_mm"], disk.info(name)["bbox_mm"])
            self.assertAlmostEqual(mem.info(name)["volume_cm3"],
                                   disk.info(name)["volume_cm3"], places=6)


if __name__ == "__main__":
    unittest.main()
