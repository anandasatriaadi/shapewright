"""
Server-level tests.

The important one is ``test_every_tool_is_covered``: it introspects the real
MCP tool list and fails if any registered tool is missing from the smoke
sequence below - so the suite can never silently drift behind the server.
"""

from __future__ import annotations

import os
import tempfile
import unittest

_TEST_DIR = tempfile.mkdtemp(prefix="shapewright_test_")
_PROJ_ROOT = os.path.join(_TEST_DIR, "projects")
os.environ.setdefault("SHAPEWRIGHT_OUT", _TEST_DIR)
os.environ.setdefault("SHAPEWRIGHT_HOME", _PROJ_ROOT)

from shapewright.server import OUT, mcp  # noqa: E402

# (tool_name, arguments) - must exercise EVERY registered tool, in a valid order
SMOKE: list[tuple[str, dict]] = [
    ("reset", {}),
    ("help", {}),
    ("create_box", {"name": "base", "length": 60, "width": 40, "height": 10, "corner": 4}),
    ("create_cylinder", {"name": "pin", "radius": 5, "height": 30, "at": [20, 0, 5]}),
    ("create_cone", {"name": "cone", "bottom_radius": 8, "top_radius": 2, "height": 15, "at": [0, 0, 5]}),
    ("create_sphere", {"name": "ball", "radius": 6, "at": [0, 15, 0]}),
    ("create_torus", {"name": "ring", "major_radius": 8, "minor_radius": 2, "at": [0, -18, 0]}),
    ("create_prism", {"name": "hex", "sides": 6, "radius": 8, "height": 20, "twist": 30, "at": [0, 0, 25]}),
    ("profile_rect", {"name": "rev_prof", "width": 6, "height": 20, "plane": "XZ", "at": [20, 0, 0]}),
    ("profile_circle", {"name": "sec", "radius": 2, "plane": "XZ"}),
    ("profile_polygon", {"name": "tri", "points": [[0, 0], [20, 0], [10, 15]], "plane": "XY", "at": [0, 0, -40]}),
    ("curve_polyline", {"name": "pathY", "points": [[0, 0], [0, 60]], "plane": "XY"}),
    ("curve_helix", {"name": "coil", "radius": 8, "pitch": 8, "height": 24}),
    ("extrude", {"name": "plate3d", "profile": "tri", "amount": 6}),
    ("revolve", {"name": "tube", "profile": "rev_prof", "axis": "Z", "angle": 360}),
    ("sweep", {"name": "rod", "profile": "sec", "path": "pathY"}),
    ("profile_rect", {"name": "loft_a", "width": 20, "height": 20, "plane": "XY"}),
    ("profile_circle", {"name": "loft_b", "radius": 10, "plane": "XY", "at": [0, 0, 30]}),
    ("loft", {"name": "lofted", "profiles": ["loft_a", "loft_b"], "ruled": True}),
    ("union", {"name": "merged", "parts": ["base", "pin"]}),
    ("subtract", {"name": "base", "tools": ["cone"]}),
    ("intersect", {"name": "isect", "a": "base", "b": "ball"}),
    ("create_box", {"name": "filletme", "length": 30, "width": 30, "height": 20}),
    ("fillet_edges", {"name": "filletme", "radius": 3, "select": "parallel:Z"}),
    ("chamfer_edges", {"name": "filletme", "length": 1.0, "select": "at:zmax"}),
    ("shell", {"name": "hex", "thickness": 1.5, "open_faces": "normal:Z+"}),
    ("transform", {"name": "plate3d", "translate": [0, 0, 5]}),
    ("mirror_object", {"name": "cone", "about": "YZ", "keep_original": True}),
    ("split_object", {"name": "lofted", "plane": "XY", "offset": 15, "keep": "top"}),
    ("pattern_linear", {"name": "ball", "count": 3, "spacing": 20, "direction": "X", "result": "balls"}),
    ("pattern_polar", {"name": "ring", "count": 4, "radius": 0, "axis": "Z", "result": "rings"}),
    ("place_on_bed", {"name": "plate3d"}),
    ("align_to", {"name": "ring", "reference": "base", "face": "top", "gap": 0}),
    ("get_edges", {"name": "base", "select": "all"}),
    ("get_faces", {"name": "base", "select": "normal:Z+"}),
    ("distance", {"a": "ball", "b": "cone"}),
    ("interference", {"a": "base", "b": "pin"}),
    ("printability", {"name": "base", "bed": [220, 220, 250]}),
    ("render_views", {"names": ["base", "hex", "tube"], "views": ["iso", "top"]}),
    ("export_part", {"name": "base", "format": "stl"}),
    ("export_all", {"format": "step"}),
    ("export_script", {}),
    ("object_info", {"name": "hex"}),
    ("list_objects", {}),
    ("duplicate_object", {"name": "hex", "new_name": "hex2"}),
    ("delete_object", {"name": "hex2"}),
    ("project_open", {"name": "smoke_project", "root": _PROJ_ROOT, "cache_size": 4}),
    ("create_box", {"name": "persisted", "length": 10, "width": 10, "height": 10}),
    ("object_info", {"name": "persisted"}),
    ("project_info", {}),
    ("project_save", {}),
    ("project_list", {"root": _PROJ_ROOT}),
    ("undo", {}),
    ("project_close", {}),
    ("project_delete", {"name": "smoke_project", "root": _PROJ_ROOT}),
    ("reset", {}),
]


async def _call(name, args):
    return await mcp.call_tool(name, args)


def _text(res) -> str:
    out = []
    for item in getattr(res, "content", []):
        if getattr(item, "type", None) == "text":
            out.append(item.text)
    return "\n".join(out)


class TestToolCoverage(unittest.IsolatedAsyncioTestCase):
    async def test_every_tool_is_covered(self):
        tools = await mcp.list_tools()
        registered = {t.name for t in tools}
        covered = {name for name, _ in SMOKE}
        missing = registered - covered
        self.assertFalse(missing, f"tools with no smoke test: {sorted(missing)}")
        stale = covered - registered
        self.assertFalse(stale, f"smoke test refers to unknown tools: {sorted(stale)}")

    async def test_smoke_sequence_all_succeed(self):
        for name, args in SMOKE:
            res = await _call(name, args)
            self.assertFalse(getattr(res, "is_error", False),
                             f"{name}({args}) errored:\n{_text(res)}")


class TestServerBehaviour(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        await _call("reset", {})
        await _call("create_box", {"name": "b", "length": 20, "width": 20, "height": 20})

    async def test_render_returns_image(self):
        res = await _call("render_views", {"names": ["b"], "views": ["iso"]})
        kinds = [getattr(i, "type", None) for i in res.content]
        self.assertIn("image", kinds)

    async def test_export_part_writes_file(self):
        res = await _call("export_part", {"name": "b", "format": "stl"})
        path = _text(res)
        self.assertTrue(os.path.exists(path), path)

    async def test_export_all_skips_profiles(self):
        await _call("profile_circle", {"name": "prof", "radius": 5})
        res = await _call("export_all", {"format": "stl"})
        text = _text(res)
        self.assertNotIn("prof.stl", text)
        self.assertIn("b.stl", text)

    async def _expect_error(self, name, args) -> str:
        try:
            res = await _call(name, args)
        except Exception:  # raised straight through the in-process call
            return ""
        self.assertTrue(getattr(res, "is_error", False), f"{name} was expected to fail")
        return _text(res)

    async def test_bad_selector_is_error(self):
        msg = await self._expect_error("fillet_edges",
                                       {"name": "b", "radius": 1, "select": "wat"})
        if msg:
            self.assertTrue("selector" in msg.lower() or "unknown" in msg.lower(), msg)

    async def test_export_part_rejects_profile(self):
        await _call("profile_circle", {"name": "prof", "radius": 5})
        msg = await self._expect_error("export_part", {"name": "prof", "format": "stl"})
        if msg:
            self.assertIn("2D profile", msg)

    async def test_export_script_writes_runnable_file(self):
        res = await _call("export_script", {})
        path = _text(res)
        self.assertTrue(os.path.exists(path))
        src = open(path).read()
        self.assertIn("from build123d import", src)
        import runpy

        runpy.run_path(path)  # must actually run

    async def test_object_info_shape(self):
        res = await _call("object_info", {"name": "b"})
        self.assertIn("bbox_mm", _text(res))

    async def test_help_mentions_key_tools(self):
        text = _text(await _call("help", {}))
        for token in ("create_box", "fillet_edges", "render_views", "SELECTORS"):
            self.assertIn(token, text)

    async def test_undo_restores(self):
        await _call("create_box", {"name": "temp", "length": 5, "width": 5, "height": 5})
        await _call("undo", {})
        text = _text(await _call("list_objects", {}))
        self.assertNotIn('"temp"', text)

    async def test_project_persists_across_sessions(self):
        root = tempfile.mkdtemp(prefix="sw_persist_")
        await _call("project_open", {"name": "p1", "root": root})
        await _call("create_box", {"name": "kept", "length": 10, "width": 10, "height": 10})
        await _call("project_close", {})
        # a *new* session against the same directory must see the object
        await _call("project_open", {"name": "p1", "root": root})
        text = _text(await _call("object_info", {"name": "kept"}))
        self.assertIn("10.0", text)
        listing = _text(await _call("project_list", {"root": root}))
        self.assertIn("p1", listing)

    async def test_main_entrypoint_calls_run(self):
        import shapewright.server as srv

        called = {}
        original = srv.mcp.run
        srv.mcp.run = lambda *a, **k: called.setdefault("ran", True)
        try:
            srv.main()
            import shapewright.__main__  # noqa: F401  (guarded; must not run the server)
        finally:
            srv.mcp.run = original
        self.assertTrue(called.get("ran"))


if __name__ == "__main__":
    unittest.main()
