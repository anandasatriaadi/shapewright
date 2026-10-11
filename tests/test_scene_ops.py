"""Exhaustive per-operation tests for shapewright.scene.Scene."""

from __future__ import annotations

import math
import unittest

from shapewright.scene import Scene, SceneError


class TestPrimitives(unittest.TestCase):
    def setUp(self):
        self.s = Scene()

    def test_box(self):
        self.s.box("b", 60, 40, 10)
        i = self.s.info("b")
        self.assertEqual(i["bbox_mm"], [60.0, 40.0, 10.0])
        self.assertAlmostEqual(i["volume_cm3"], 24.0, places=2)
        self.assertEqual(i["solids"], 1)

    def test_box_corner_reduces_volume(self):
        self.s.box("b", 40, 40, 10, corner=5)
        self.assertLess(self.s.info("b")["volume_cm3"], 16.0)
        self.assertEqual(self.s.info("b")["bbox_mm"], [40.0, 40.0, 10.0])

    def test_cylinder(self):
        self.s.cylinder("c", 10, 20)
        self.assertAlmostEqual(self.s.info("c")["volume_cm3"], math.pi * 100 * 20 / 1000, places=1)

    def test_cone(self):
        self.s.cone("c", 10, 0, 20)
        self.assertAlmostEqual(self.s.info("c")["volume_cm3"], math.pi * 100 * 20 / 3000, places=1)

    def test_sphere(self):
        self.s.sphere("s", 10)
        self.assertAlmostEqual(self.s.info("s")["volume_cm3"], 4 / 3 * math.pi * 1000 / 1000, places=1)

    def test_torus(self):
        self.s.torus("t", 10, 2)
        self.assertAlmostEqual(self.s.info("t")["volume_cm3"], 2 * math.pi**2 * 10 * 4 / 1000, places=1)
        self.assertEqual(self.s.info("t")["bbox_mm"][0], 24.0)

    def test_prism(self):
        self.s.prism("p", 6, 10, 20)
        self.assertAlmostEqual(self.s.info("p")["volume_cm3"],
                               (3 * math.sqrt(3) / 2 * 100) * 20 / 1000, places=1)

    def test_prism_twist(self):
        self.s.prism("p", 6, 10, 40, twist=60)
        self.assertEqual(self.s.info("p")["bbox_mm"][2], 40.0)

    def test_prism_fillet(self):
        self.s.prism("p", 6, 10, 20, fillet=1)
        self.assertEqual(self.s.info("p")["solids"], 1)

    def test_prism_twist_and_fillet_is_rejected(self):
        with self.assertRaises(SceneError):
            self.s.prism("p", 6, 10, 20, twist=30, fillet=1)

    def test_cylinder_corner(self):
        self.s.cylinder("c", 10, 20, corner=2)
        self.assertEqual(self.s.info("c")["solids"], 1)
        self.assertLess(self.s.info("c")["volume_cm3"], math.pi * 100 * 20 / 1000)

    def test_chamfer_no_match_raises(self):
        self.s.box("b", 10, 10, 10)
        with self.assertRaises(SceneError):
            self.s.chamfer("b", 1, "type:circle")

    def test_placement_and_rotation(self):
        self.s.box("b", 10, 10, 10, at=(5, 0, 50))
        self.assertEqual(self.s.info("b")["center_mm"][2], 50.0)
        self.s.box("r", 20, 10, 10, rotation=(0, 0, 90))
        self.assertEqual(self.s.info("r")["bbox_mm"][0], 10.0)


class TestProfilesAndSolids(unittest.TestCase):
    def setUp(self):
        self.s = Scene()

    def test_profile_rect_and_extrude(self):
        self.s.profile_rect("r", 10, 5)
        self.s.extrude("e", "r", 20)
        self.assertAlmostEqual(self.s.info("e")["volume_cm3"], 50 * 20 / 1000, places=3)

    def test_profile_rect_rounded(self):
        self.s.profile_rect("r", 20, 20, corner=5)
        self.s.extrude("e", "r", 10)
        self.assertLess(self.s.info("e")["volume_cm3"], 4.0)

    def test_profile_circle(self):
        self.s.profile_circle("c", 10, plane="XY")
        self.s.extrude("e", "c", 5)
        self.assertAlmostEqual(self.s.info("e")["volume_cm3"], math.pi * 100 * 5 / 1000, places=2)

    def test_profile_polygon(self):
        self.s.profile_polygon("tri", [[0, 0], [20, 0], [10, 15]])
        self.s.extrude("e", "tri", 6)
        self.assertAlmostEqual(self.s.info("e")["volume_cm3"], 150 * 6 / 1000, places=2)

    def test_extrude_both_and_taper(self):
        self.s.profile_circle("c", 10)
        self.s.extrude("e", "c", 10, both=True)
        self.assertEqual(self.s.info("e")["bbox_mm"][2], 20.0)
        self.s.extrude("t", "c", 10, taper=20)
        self.assertEqual(self.s.info("t")["solids"], 1)

    def test_revolve(self):
        self.s.profile_rect("rev", 6, 20, plane="XZ", at=(20, 0, 0))
        self.s.revolve("tube", "rev", axis="Z")
        # annulus 17..23, height 20
        self.assertAlmostEqual(self.s.info("tube")["volume_cm3"],
                               math.pi * (23**2 - 17**2) * 20 / 1000, places=1)

    def test_loft(self):
        self.s.profile_rect("a", 20, 20, at=(0, 0, 0))
        self.s.profile_circle("b", 10, at=(0, 0, 30))
        self.s.loft("l", ["a", "b"], ruled=True)
        v = self.s.info("l")["volume_cm3"]
        self.assertTrue(9.0 < v < 13.0, v)     # between circle and square prism

    def test_sweep(self):
        self.s.profile_circle("sec", 2, plane="XZ")
        self.s.curve_polyline("path", [[0, 0], [0, 60]], plane="XY")
        self.s.sweep("rod", "sec", "path")
        self.assertAlmostEqual(self.s.info("rod")["volume_cm3"], math.pi * 4 * 60 / 1000, places=2)

    def test_helix_sweep(self):
        self.s.curve_helix("coil", 8, 8, 24)
        self.s.profile_circle("w", 1.2, plane="XZ", at=(8, 0, 0))
        self.s.sweep("spring", "w", "coil")
        self.assertGreater(self.s.info("spring")["volume_cm3"], 0.0)


class TestBooleans(unittest.TestCase):
    def setUp(self):
        self.s = Scene()

    def test_union(self):
        self.s.box("a", 20, 20, 10)
        self.s.box("b", 20, 20, 10, at=(0, 0, 10))
        self.s.union("u", ["a", "b"])
        self.assertEqual(self.s.info("u")["solids"], 1)
        self.assertAlmostEqual(self.s.info("u")["volume_cm3"], 8.0, places=1)

    def test_union_disjoint_is_compound(self):
        self.s.box("a", 10, 10, 10)
        self.s.box("b", 10, 10, 10, at=(50, 0, 0))
        self.s.union("u", ["a", "b"])
        self.assertEqual(self.s.info("u")["solids"], 2)

    def test_subtract(self):
        self.s.box("b", 40, 40, 10)
        self.s.cylinder("c", 5, 40)
        before = self.s.info("b")["volume_cm3"]
        self.s.subtract("b", ["c"])
        self.assertLess(self.s.info("b")["volume_cm3"], before)
        self.assertEqual(len(self.s.edges("b", "type:circle")), 2)

    def test_intersect(self):
        self.s.box("a", 20, 20, 20)
        self.s.box("b", 20, 20, 20, at=(10, 0, 0))
        self.s.intersect("i", "a", "b")
        self.assertAlmostEqual(self.s.info("i")["bbox_mm"][0], 10.0, places=1)


class TestModify(unittest.TestCase):
    def setUp(self):
        self.s = Scene()

    def test_fillet_reduces_volume(self):
        self.s.box("b", 40, 40, 20)
        before = self.s.info("b")["volume_cm3"]
        self.s.fillet("b", 3, "parallel:Z")
        self.assertLess(self.s.info("b")["volume_cm3"], before)
        self.assertEqual(self.s.info("b")["solids"], 1)

    def test_chamfer(self):
        self.s.box("b", 40, 40, 20)
        self.s.chamfer("b", 2, "at:zmax")
        self.assertEqual(self.s.info("b")["solids"], 1)

    def test_fillet_no_match_raises(self):
        self.s.box("b", 10, 10, 10)
        with self.assertRaises(SceneError):
            self.s.fillet("b", 1, "type:circle")

    def test_shell_open_top(self):
        self.s.box("b", 30, 30, 30)
        self.s.shell("b", 2, "normal:Z+")
        v = self.s.info("b")["volume_cm3"]
        self.assertTrue(5.0 < v < 27.0, v)
        self.assertEqual(self.s.info("b")["bbox_mm"], [30.0, 30.0, 30.0])

    def test_transform_translate_rotate_scale(self):
        self.s.box("b", 10, 10, 10)
        self.s.transform("b", translate=(0, 0, 20))
        self.assertEqual(self.s.info("b")["center_mm"][2], 20.0)
        self.s.transform("b", rotate=(0, 0, 45))
        self.assertEqual(self.s.info("b")["solids"], 1)
        self.s.transform("b", scale=2.0)
        self.assertAlmostEqual(self.s.info("b")["bbox_mm"][0], 28.28, places=1)

    def test_mirror(self):
        self.s.box("b", 10, 10, 10, at=(20, 0, 0))
        self.s.mirror("b", about="YZ", keep=True)
        self.assertEqual(self.s.info("b")["bbox_mm"][0], 50.0)
        self.assertEqual(self.s.info("b")["solids"], 2)

    def test_split(self):
        self.s.box("b", 20, 20, 20)
        self.s.split("b", plane="XY", offset=0.0, keep="top")
        self.assertAlmostEqual(self.s.info("b")["volume_cm3"], 4.0, places=1)
        self.assertAlmostEqual(self.s.info("b")["min_mm"][2], 0.0, places=3)

    def test_pattern_linear(self):
        self.s.box("b", 5, 5, 5)
        self.s.pattern_linear("b", 3, 10, "X", result="row")
        self.assertEqual(self.s.info("row")["bbox_mm"][0], 25.0)
        self.assertEqual(self.s.info("row")["solids"], 3)

    def test_pattern_polar(self):
        self.s.box("b", 5, 5, 5, at=(20, 0, 0))
        self.s.pattern_polar("b", 4, radius=0, axis="Z", result="ring")
        self.assertEqual(self.s.info("ring")["solids"], 4)

    def test_place_on_bed(self):
        self.s.box("b", 10, 10, 10, at=(0, 0, 100))
        self.s.place_on_bed("b")
        self.assertAlmostEqual(self.s.info("b")["min_mm"][2], 0.0, places=4)

    def test_align_to(self):
        self.s.box("base", 20, 20, 10)
        self.s.box("cap", 10, 10, 5, at=(0, 0, 40))
        self.s.align_to("cap", "base", face="top", gap=1.0)
        self.assertAlmostEqual(self.s.info("cap")["min_mm"][2], 6.0, places=3)


class TestQueries(unittest.TestCase):
    def setUp(self):
        self.s = Scene()

    def test_info_and_list(self):
        self.s.box("a", 10, 10, 10)
        self.s.box("b", 10, 10, 10, at=(50, 0, 0))
        self.assertEqual(len(self.s.list_objects()), 2)
        self.assertEqual(self.s.info("a")["faces"], 6)

    def test_edges_faces(self):
        self.s.box("b", 60, 40, 10)
        self.assertEqual(len(self.s.edges("b", "parallel:Z")), 4)
        self.assertEqual(len(self.s.faces("b", "normal:Z+")), 1)

    def test_distance_and_interference(self):
        self.s.box("a", 10, 10, 10)
        self.s.box("b", 10, 10, 10, at=(30, 0, 0))
        self.assertAlmostEqual(self.s.distance("a", "b")["distance_mm"], 20.0, places=1)
        self.s.box("c", 10, 10, 10, at=(5, 0, 0))
        self.assertTrue(self.s.interference("a", "c")["interferes"])
        self.assertFalse(self.s.interference("a", "b")["interferes"])

    def test_missing_name_raises(self):
        with self.assertRaises(SceneError):
            self.s.info("nope")

    def test_undo(self):
        self.s.box("a", 10, 10, 10)
        self.s.box("b", 10, 10, 10)
        self.assertTrue(self.s.undo())
        self.assertNotIn("b", self.s.names())
        self.assertIn("a", self.s.names())

    def test_duplicate_delete_reset(self):
        self.s.box("a", 10, 10, 10)
        self.s.duplicate("a", "a2")
        self.assertIn("a2", self.s.names())
        self.s.delete("a2")
        self.assertNotIn("a2", self.s.names())
        self.s.reset()
        self.assertEqual(self.s.names(), [])


class TestMoreBranches(unittest.TestCase):
    def setUp(self):
        self.s = Scene()

    def test_revolve_partial_angle(self):
        self.s.profile_rect("rev", 6, 20, plane="XZ", at=(20, 0, 0))
        self.s.revolve("half", "rev", axis="Z", angle=180)
        self.assertGreater(self.s.info("half")["volume_cm3"], 0.0)

    def test_split_keep_bottom(self):
        self.s.box("b", 20, 20, 20)
        self.s.split("b", plane="XY", offset=0.0, keep="bottom")
        self.assertAlmostEqual(self.s.info("b")["max_mm"][2], 0.0, places=3)

    def test_mirror_discards_original(self):
        self.s.box("b", 10, 10, 10, at=(20, 0, 0))
        self.s.mirror("b", about="YZ", keep=False)
        self.assertAlmostEqual(self.s.info("b")["center_mm"][0], -20.0, places=3)

    def test_shell_no_openings(self):
        self.s.box("b", 30, 30, 30)
        self.s.shell("b", 2, "none")
        v = self.s.info("b")["volume_cm3"]
        self.assertTrue(0.0 < v < 27.0, v)

    def test_align_to_bottom(self):
        self.s.box("base", 20, 20, 10)
        self.s.box("cap", 10, 10, 5, at=(0, 0, 40))
        self.s.align_to("cap", "base", face="bottom", gap=2.0)
        self.assertAlmostEqual(self.s.info("cap")["max_mm"][2], -7.0, places=3)

    def test_pattern_polar_about_x(self):
        self.s.box("b", 5, 5, 5, at=(0, 20, 0))
        self.s.pattern_polar("b", 3, radius=0, axis="X", result="spin")
        self.assertGreaterEqual(self.s.info("spin")["solids"], 2)

    def test_undo_on_empty_returns_false(self):
        self.assertFalse(self.s.undo())

    def test_transform_scale_only(self):
        self.s.box("b", 10, 10, 10)
        self.s.transform("b", scale=3.0)
        self.assertAlmostEqual(self.s.info("b")["bbox_mm"][0], 30.0, places=3)

    def test_union_three(self):
        self.s.box("a", 10, 10, 10)
        self.s.box("b", 10, 10, 10, at=(0, 0, 10))
        self.s.box("c", 10, 10, 10, at=(0, 0, 20))
        self.s.union("stack", ["a", "b", "c"])
        self.assertEqual(self.s.info("stack")["solids"], 1)
        self.assertAlmostEqual(self.s.info("stack")["volume_cm3"], 3.0, places=1)


if __name__ == "__main__":
    unittest.main()
