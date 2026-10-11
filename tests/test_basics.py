"""Smoke tests for the shapewright MCP engine.  Run: python -m unittest discover tests"""

from __future__ import annotations

import os
import tempfile
import unittest

from shapewright import render as R
from shapewright.scene import Scene, SceneError
from shapewright.script import to_python
from shapewright.select import select


class TestPrimitives(unittest.TestCase):
    def setUp(self):
        self.s = Scene()

    def test_box_info(self):
        self.s.box("b", 60, 40, 10)
        info = self.s.info("b")
        self.assertEqual(info["bbox_mm"], [60.0, 40.0, 10.0])
        self.assertAlmostEqual(info["volume_cm3"], 24.0, places=2)
        self.assertEqual(info["solids"], 1)

    def test_placement(self):
        self.s.box("b", 10, 10, 10, at=(0, 0, 50))
        self.assertEqual(self.s.info("b")["min_mm"][2], 45.0)

    def test_corner_rounding(self):
        self.s.box("b", 40, 40, 10, corner=5)
        self.assertEqual(self.s.info("b")["bbox_mm"], [40.0, 40.0, 10.0])
        # rounding removes material
        self.assertLess(self.s.info("b")["volume_cm3"], 16.0)

    def test_prism_twist(self):
        self.s.prism("p", 6, 10, 30, twist=30)
        self.assertEqual(self.s.info("p")["bbox_mm"][2], 30.0)


class TestBooleans(unittest.TestCase):
    def setUp(self):
        self.s = Scene()

    def test_subtract_makes_hole(self):
        self.s.box("b", 40, 40, 10)
        self.s.cylinder("c", 5, 40)
        before = self.s.info("b")["volume_cm3"]
        self.s.subtract("b", ["c"])
        after = self.s.info("b")["volume_cm3"]
        self.assertLess(after, before)
        # a through hole => 2 circular edges
        circles = self.s.edges("b", "type:circle")
        self.assertEqual(len(circles), 2)

    def test_union_single_solid(self):
        self.s.box("a", 20, 20, 10)
        self.s.box("b", 20, 20, 10, at=(0, 0, 10))
        self.s.union("u", ["a", "b"])
        self.assertEqual(self.s.info("u")["solids"], 1)

    def test_interference(self):
        self.s.box("a", 20, 20, 20)
        self.s.box("b", 20, 20, 20, at=(10, 0, 0))
        r = self.s.interference("a", "b")
        self.assertTrue(r["interferes"])


class TestSelectors(unittest.TestCase):
    def setUp(self):
        self.s = Scene()
        self.s.box("b", 60, 40, 10)

    def test_parallel_z(self):
        self.assertEqual(len(select(self.s.get("b"), "edges", "parallel:Z")), 4)

    def test_at_zmax(self):
        self.assertEqual(len(select(self.s.get("b"), "edges", "at:zmax")), 4)

    def test_faces_by_normal(self):
        self.assertEqual(len(select(self.s.get("b"), "faces", "normal:Z+")), 1)
        self.assertEqual(len(select(self.s.get("b"), "faces", "normal:Z-")), 1)

    def test_or_and_and(self):
        n = len(select(self.s.get("b"), "edges", "parallel:X & at:zmax"))
        self.assertEqual(n, 2)

    def test_near(self):
        got = select(self.s.get("b"), "faces", "near:(0,0,5)")
        self.assertEqual(len(got), 1)

    def test_bad_selector_raises(self):
        with self.assertRaises(ValueError):
            select(self.s.get("b"), "edges", "frobnicate:Z")


class TestModify(unittest.TestCase):
    def setUp(self):
        self.s = Scene()

    def test_fillet_and_chamfer(self):
        self.s.box("b", 40, 40, 20)
        self.s.fillet("b", 3, "parallel:Z")
        self.s.chamfer("b", 1, "at:zmax & parallel:X")
        self.assertTrue(self.s.info("b")["solids"] == 1)

    def test_fillet_no_match_errors(self):
        self.s.box("b", 10, 10, 10)
        with self.assertRaises(SceneError):
            self.s.fillet("b", 1, "type:circle")

    def test_shell_open_top(self):
        self.s.box("b", 30, 30, 30)
        self.s.shell("b", 2, "normal:Z+")
        self.assertLess(self.s.info("b")["volume_cm3"], 27.0)

    def test_pattern_linear(self):
        self.s.box("b", 5, 5, 5)
        self.s.pattern_linear("b", 4, 10, "X", result="row")
        self.assertAlmostEqual(self.s.info("row")["bbox_mm"][0], 35.0, places=1)

    def test_place_on_bed(self):
        self.s.box("b", 10, 10, 10, at=(0, 0, 100))
        self.s.place_on_bed("b")
        self.assertAlmostEqual(self.s.info("b")["min_mm"][2], 0.0, places=4)


class TestPrintability(unittest.TestCase):
    def setUp(self):
        self.s = Scene()

    def test_flat_part_no_support(self):
        self.s.box("b", 60, 40, 10, corner=4)
        r = self.s.printability("b", bed=(220, 220, 250))
        self.assertEqual(r["overhang_area_cm2"], 0.0)
        self.assertFalse(r["needs_support"])
        self.assertTrue(r["fits_bed_upright"])

    def test_overhang_detected(self):
        self.s.box("base", 40, 10, 10)
        self.s.box("arm", 40, 10, 10, at=(0, 0, 20))
        self.s.union("t", ["base", "arm"])
        r = self.s.printability("t")
        self.assertGreater(r["overhang_area_cm2"], 0.0)
        self.assertTrue(r["needs_support"])

    def test_bed_too_small(self):
        self.s.box("b", 300, 20, 20)
        r = self.s.printability("b", bed=(220, 220, 250))
        self.assertFalse(r["fits_bed_upright"])


class TestScript(unittest.TestCase):
    def test_generated_script_runs(self):
        s = Scene()
        s.box("plate", 60, 40, 10, corner=4)
        s.cylinder("bore", 6, 40)
        s.subtract("plate", ["bore"])
        s.fillet("plate", 2, "type:circle & at:zmax")
        code = to_python(s)
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "design.py")
            with open(path, "w") as fh:
                fh.write(code)
            import runpy

            runpy.run_path(path)


class TestRender(unittest.TestCase):
    def test_render_returns_image(self):
        s = Scene()
        s.box("b", 20, 20, 20)
        img = R.render([("b", s.get("b"))], ["iso", "top"], size=200)
        self.assertEqual(img.size, (418, 212))


if __name__ == "__main__":
    unittest.main()
