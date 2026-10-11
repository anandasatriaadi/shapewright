"""Tests for printability analysis and the software renderer."""

from __future__ import annotations

import unittest

from shapewright import printer, render as R
from shapewright.scene import Scene


class TestPrinter(unittest.TestCase):
    def test_analyze_no_bed_no_material(self):
        s = Scene()
        s.box("b", 20, 20, 20)
        rep = printer.analyze(s.get("b"), bed=None, material=None)
        self.assertIn("PLA", rep["estimated_grams"])
        self.assertIn("PETG", rep["estimated_grams"])
        self.assertNotIn("bed_mm", rep)

    def test_analyze_with_bed(self):
        s = Scene()
        s.box("b", 20, 20, 20)
        rep = printer.analyze(s.get("b"), bed=(220, 220, 250))
        self.assertTrue(rep["fits_bed_upright"])
        self.assertIn("fits_bed_diagonal", rep)

    def test_analyze_curved_solid(self):
        s = Scene()
        s.sphere("ball", 10)          # curved faces exercise the normal fallback
        rep = printer.analyze(s.get("ball"))
        self.assertEqual(rep["solids"], 1)
        self.assertGreater(rep["surface_cm2"], 0)

    def test_check_fit(self):
        s = Scene()
        s.box("a", 20, 20, 20)
        s.box("b", 10, 10, 10, at=(5, 0, 0))
        r = printer.check_fit(s.get("b"), s.get("a"), clearance=0.2)
        self.assertTrue(r["interferes"])


class TestRender(unittest.TestCase):
    def test_mesh_of(self):
        s = Scene()
        s.box("b", 20, 20, 20)
        m = R.mesh_of(s.get("b"))
        self.assertGreater(len(m), 0)
        self.assertEqual(m.shape[1:], (3, 3))

    def test_render_grid_and_outline(self):
        s = Scene()
        s.box("a", 20, 20, 20)
        s.cylinder("b", 5, 30, at=(0, 0, 15))
        img = R.render([("a", s.get("a")), ("b", s.get("b"))],
                       ["iso", "front", "right", "top"], size=200, outline=True)
        self.assertEqual(img.mode, "RGB")

    def test_png_bytes(self):
        s = Scene()
        s.box("a", 10, 10, 10)
        data = R.png_bytes(R.render([("a", s.get("a"))], ["iso"], size=120))
        self.assertTrue(data.startswith(b"\x89PNG"))

    def test_render_single_shape_and_empty(self):
        s = Scene()
        s.box("a", 10, 10, 10)
        img = R.render(s.get("a"), ["iso"], size=120)       # single shape, not a list
        self.assertEqual(img.mode, "RGB")
        empty = R.render([], ["iso"], size=120)             # no geometry at all
        self.assertEqual(empty.mode, "RGB")


if __name__ == "__main__":
    unittest.main()
