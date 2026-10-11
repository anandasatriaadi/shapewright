"""Exhaustive tests for the edge/face selector language."""

from __future__ import annotations

import unittest

from shapewright.scene import Scene
from shapewright.select import describe, select


class TestSelectorPredicates(unittest.TestCase):
    def setUp(self):
        self.s = Scene()
        self.s.box("b", 60, 40, 10)          # 12 edges, 6 faces
        self.b = self.s.get("b")

    def n(self, kind, spec):
        return len(select(self.b, kind, spec))

    def test_all_and_star(self):
        self.assertEqual(self.n("edges", "all"), 12)
        self.assertEqual(self.n("edges", "*"), 12)
        self.assertEqual(self.n("faces", "all"), 6)

    def test_parallel_and_dir_and_axis(self):
        for spec in ("parallel:X", "dir:(1,0,0)", "axis:X"):
            self.assertEqual(self.n("edges", spec), 4, spec)
        self.assertEqual(self.n("edges", "parallel:Y"), 4)
        self.assertEqual(self.n("edges", "parallel:Z"), 4)

    def test_at_positions(self):
        for spec in ("at:zmax", "at:zmin"):
            self.assertEqual(self.n("edges", spec), 4, spec)
        self.assertEqual(self.n("edges", "at:xmax"), 4)
        self.assertEqual(self.n("edges", "at:ymin"), 4)

    def test_type(self):
        self.assertEqual(self.n("edges", "type:line"), 12)
        self.assertEqual(self.n("edges", "type:circle"), 0)
        self.assertEqual(self.n("faces", "type:plane"), 6)

    def test_normal_signed_vs_unsigned(self):
        self.assertEqual(self.n("faces", "normal:Z"), 2)     # both up and down
        self.assertEqual(self.n("faces", "normal:Z+"), 1)    # up only
        self.assertEqual(self.n("faces", "normal:Z-"), 1)    # down only
        self.assertEqual(self.n("faces", "normal:+Z"), 1)

    def test_metrics(self):
        self.assertEqual(self.n("edges", "length>30"), 8)    # 4 x 60 long, 4 x 40
        self.assertEqual(self.n("edges", "length<15"), 4)    # the 10 tall ones
        self.assertEqual(self.n("faces", "area>1000"), 2)    # two 60x40 faces

    def test_positional(self):
        for spec in ("first", "last", "index:0", "longest", "shortest"):
            self.assertEqual(self.n("edges", spec), 1, spec)
        self.assertEqual(self.n("faces", "largest"), 1)

    def test_and_or(self):
        self.assertEqual(self.n("edges", "parallel:X & at:zmax"), 2)
        self.assertEqual(self.n("edges", "parallel:X | parallel:Y"), 8)

    def test_near(self):
        self.assertEqual(self.n("faces", "near:(0,0,5)"), 1)
        self.assertEqual(self.n("edges", "near:(30,20,5)"), 1)

    def test_convex_concave_on_box(self):
        self.assertEqual(self.n("edges", "convex"), 12)
        self.assertEqual(self.n("edges", "concave"), 0)

    def test_concave_on_reentrant(self):
        s = Scene()
        s.box("l1", 40, 20, 10)
        s.box("l2", 20, 20, 10, at=(-10, 0, 10))
        s.union("L", ["l1", "l2"])
        concave = select(s.get("L"), "edges", "concave")
        self.assertEqual(len(concave), 1)          # the reentrant corner

    def test_radius_metric_ignores_non_circles(self):
        s = Scene()
        s.box("p", 40, 40, 6)
        s.cylinder("h", 5, 20)
        s.subtract("p", ["h"])
        got = select(s.get("p"), "edges", "radius>4 & radius<6")
        self.assertEqual(len(got), 2)              # the two hole rims
        self.assertEqual(len(select(s.get("p"), "edges", "type:circle")), 2)

    def test_errors(self):
        with self.assertRaises(ValueError):
            select(self.b, "edges", "frobnicate:Z")
        with self.assertRaises(ValueError):
            select(self.b, "edges", "at:qmax")
        with self.assertRaises(ValueError):
            select(self.b, "bananas", "all")

    def test_describe_rows(self):
        rows = describe(self.b, "edges", "parallel:Z")
        self.assertEqual(len(rows), 4)
        self.assertIn("center", rows[0])
        self.assertIn("length", rows[0])
        self.assertEqual(rows[0]["geom"], "line")


class TestSelectorKindsAndEdges(unittest.TestCase):
    def setUp(self):
        self.s = Scene()
        self.s.box("b", 60, 40, 10)
        self.b = self.s.get("b")

    def n(self, kind, spec):
        return len(select(self.b, kind, spec))

    def test_vertices_kind(self):
        self.assertEqual(self.n("vertices", "all"), 8)
        self.assertEqual(self.n("vertex", "at:zmax"), 4)

    def test_vector_and_unsigned_dir(self):
        self.assertEqual(self.n("edges", "dir:(1,1,0)"), 0)
        self.assertEqual(self.n("edges", "dir:(2,0,0)"), 4)
        self.assertEqual(self.n("faces", "normal:(0,0,1)"), 2)   # unsigned

    def test_metric_operators(self):
        self.assertEqual(self.n("edges", "length>=40"), 8)
        self.assertEqual(self.n("edges", "length<=10"), 4)
        self.assertEqual(self.n("edges", "length=60"), 4)

    def test_smooth_and_saddle_do_not_error(self):
        self.assertIsInstance(select(self.b, "edges", "smooth"), list)
        self.assertIsInstance(select(self.b, "edges", "saddle"), list)

    def test_curved_faces(self):
        s = Scene()
        s.cylinder("c", 10, 20)
        c = s.get("c")
        self.assertEqual(len(select(c, "faces", "type:cylinder")), 1)
        self.assertEqual(len(select(c, "faces", "type:plane")), 2)
        self.assertEqual(len(select(c, "edges", "type:circle")), 2)
        self.assertEqual(len(select(c, "edges", "diameter>15")), 2)

    def test_error_messages(self):
        with self.assertRaises(ValueError):
            select(self.b, "edges", "where:something")
        with self.assertRaises(ValueError):
            select(self.b, "edges", "type:banana")
        with self.assertRaises(ValueError):
            select(self.b, "edges", "parallel:notavector")
        with self.assertRaises(ValueError):
            select(self.b, "edges", "length>abc")

    def test_index_and_last(self):
        self.assertEqual(len(select(self.b, "edges", "index:2")), 1)
        self.assertEqual(len(select(self.b, "faces", "last")), 1)

    def test_degenerate_and_empty_selections(self):
        self.assertEqual(len(select(self.b, "edges", "parallel:(0,0,0)")), 0)   # zero vector
        self.assertEqual(len(select(self.b, "vertices", "parallel:Z")), 0)      # dir on vertices
        self.assertEqual(len(select(self.b, "edges", "all & all")), 12)         # empty pred path
        self.assertEqual(len(describe(self.b, "edges", "all", limit=2)), 2)     # limit break


class TestSelectorsOnSphere(unittest.TestCase):
    def test_curved_face_normal(self):
        s = Scene()
        s.sphere("s", 10)
        # a sphere face is curved; normal_at needs a point -> fallback path
        self.assertEqual(len(select(s.get("s"), "faces", "all")), 1)
        self.assertEqual(len(select(s.get("s"), "faces", "normal:Z+")), 0)


if __name__ == "__main__":
    unittest.main()
