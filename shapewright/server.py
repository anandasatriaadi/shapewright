"""
shapewright.server - the MCP tool surface.

Run with:  python -m shapewright        (stdio transport)

Design philosophy: the agent should never have to remember build123d's API.
Every tool is high level, takes millimetres, edits named objects in a live
scene, and returns a small JSON summary.  Selection of edges/faces uses a tiny
string language (see shapewright.select).
"""

from __future__ import annotations

import functools
import os
from typing import Optional

from mcp.server.mcpserver import MCPServer, Image
from mcp.server.mcpserver.exceptions import ToolError

from . import render as R
from . import script as script_mod
from .scene import Scene, SceneError

OUT = os.environ.get("SHAPEWRIGHT_OUT", os.path.abspath("shapewright_out"))
scene = Scene()

mcp = MCPServer(
    name="shapewright",
    instructions=(
        "shapewright is a parametric 3D-modelling server (build123d under the hood) "
        "for designing parts to 3D print.\n\n"
        "Workflow:\n"
        "1. create primitives / profiles (units are mm, centred on the origin)\n"
        "2. combine them with union / subtract / intersect\n"
        "3. refine with fillet_edges, chamfer_edges, shell, patterns\n"
        "4. call render_views to LOOK at what you made (returned as an image)\n"
        "5. call printability to check overhangs / bed fit, then export_part\n\n"
        "Edge/face selectors are strings, e.g. 'parallel:Z & at:zmax', "
        "'type:circle & radius>2', 'concave', 'normal:Z+', 'near:(0,0,10)'. "
        "Combine with & (and) and | (or). Call help for the full cheat-sheet.\n\n"
        "Use get_edges / get_faces to inspect before selecting."
    ),
)


def _at(v) -> tuple:
    return tuple(float(x) for x in v) if v else (0.0, 0.0, 0.0)


def _tool(fn=None):
    """Register a tool, turning any failure into a readable ToolError.

    That way an agent gets 'fillet: no edges matched ...' rather than a bare
    'Error executing tool fillet_edges'.
    """

    def deco(f):
        @functools.wraps(f)
        def wrapper(*args, **kwargs):
            try:
                return f(*args, **kwargs)
            except ToolError:
                raise
            except Exception as exc:  # noqa: BLE001
                raise ToolError(f"{type(exc).__name__}: {exc}") from exc

        return mcp.tool()(wrapper)

    return deco if fn is None else deco(fn)


def _done(name: str, note: str = "") -> dict:
    d = scene.info(name)
    if note:
        d["note"] = note
    return d


# --------------------------------------------------------------------------
# meta
# --------------------------------------------------------------------------
@_tool
def help() -> str:
    """Cheat-sheet: available tools, selector syntax and conventions."""
    return HELP_TEXT


@_tool
def reset() -> str:
    """Forget everything and start a new empty design."""
    scene.reset()
    return "scene cleared"


@_tool
def undo() -> str:
    """Undo the last operation (handy if a boolean or fillet did the wrong thing)."""
    return "undone" if scene.undo() else "nothing to undo"


@_tool
def list_objects() -> list[dict]:
    """List every object in the scene with its size, volume and position."""
    return scene.list_objects()


@_tool
def object_info(name: str) -> dict:
    """Detailed measurements for one object (bbox, volume, faces, edges)."""
    return scene.info(name)


@_tool
def delete_object(name: str) -> str:
    """Remove an object from the scene."""
    scene.delete(name)
    return f"deleted {name}"


@_tool
def duplicate_object(name: str, new_name: str) -> dict:
    """Copy an object under a new name."""
    scene.duplicate(name, new_name)
    return _done(new_name)


# --------------------------------------------------------------------------
# primitives
# --------------------------------------------------------------------------
@_tool
def create_box(name: str, length: float, width: float, height: float,
               at: Optional[list[float]] = None, rotation: Optional[list[float]] = None,
               corner: Optional[float] = None) -> dict:
    """A rectangular box (centred on the origin). `corner` rounds the vertical edges."""
    scene.box(name, length, width, height, _at(at), _at(rotation), corner)
    return _done(name)


@_tool
def create_cylinder(name: str, radius: float, height: float,
                    at: Optional[list[float]] = None, rotation: Optional[list[float]] = None,
                    corner: Optional[float] = None) -> dict:
    """A cylinder, axis along +Z."""
    scene.cylinder(name, radius, height, _at(at), _at(rotation), corner)
    return _done(name)


@_tool
def create_cone(name: str, bottom_radius: float, top_radius: float, height: float,
                at: Optional[list[float]] = None, rotation: Optional[list[float]] = None) -> dict:
    """A cone / truncated cone, axis along +Z."""
    scene.cone(name, bottom_radius, top_radius, height, _at(at), _at(rotation))
    return _done(name)


@_tool
def create_sphere(name: str, radius: float, at: Optional[list[float]] = None) -> dict:
    """A sphere."""
    scene.sphere(name, radius, _at(at))
    return _done(name)


@_tool
def create_torus(name: str, major_radius: float, minor_radius: float,
                 at: Optional[list[float]] = None, rotation: Optional[list[float]] = None) -> dict:
    """A torus (ring), axis along +Z."""
    scene.torus(name, major_radius, minor_radius, _at(at), _at(rotation))
    return _done(name)


@_tool
def create_prism(name: str, sides: int, radius: float, height: float,
                 twist: float = 0.0, fillet: float = 0.0,
                 at: Optional[list[float]] = None, rotation: Optional[list[float]] = None) -> dict:
    """A regular N-sided prism (e.g. hex handle). `twist` (deg) turns the top section for a twisted look."""
    scene.prism(name, sides, radius, height, _at(at), _at(rotation), twist, fillet)
    return _done(name)


# --------------------------------------------------------------------------
# profiles & solids of revolution / along a path
# --------------------------------------------------------------------------
@_tool
def profile_rect(name: str, width: float, height: float, corner: float = 0.0,
                 plane: str = "XY", at: Optional[list[float]] = None) -> dict:
    """A 2D rectangle (or rounded rectangle) on a plane, ready to extrude/revolve/loft."""
    scene.profile_rect(name, width, height, corner, plane, _at(at))
    return _done(name)


@_tool
def profile_circle(name: str, radius: float, plane: str = "XY",
                   at: Optional[list[float]] = None) -> dict:
    """A 2D circle on a plane."""
    scene.profile_circle(name, radius, plane, _at(at))
    return _done(name)


@_tool
def profile_polygon(name: str, points: list[list[float]], plane: str = "XY",
                    at: Optional[list[float]] = None) -> dict:
    """A closed 2D polygon through `points` [[x,y], ...] on a plane."""
    scene.profile_polygon(name, points, plane, _at(at))
    return _done(name)


@_tool
def curve_polyline(name: str, points: list[list[float]], plane: str = "XY",
                   at: Optional[list[float]] = None) -> dict:
    """An open 2D polyline (use as a sweep path)."""
    scene.curve_polyline(name, points, plane, _at(at))
    return _done(name)


@_tool
def curve_helix(name: str, radius: float, pitch: float, height: float,
                at: Optional[list[float]] = None) -> dict:
    """A helix curve (use as a sweep path for threads/coils)."""
    scene.curve_helix(name, radius, pitch, height, _at(at))
    return _done(name)


@_tool
def extrude(name: str, profile: str, amount: float, both: bool = False,
            taper: float = 0.0) -> dict:
    """Extrude a profile into a solid. `taper` in degrees."""
    scene.extrude(name, profile, amount, both, taper)
    return _done(name)


@_tool
def revolve(name: str, profile: str, axis: str = "Z", angle: float = 360.0) -> dict:
    """Revolve a profile around a global axis (X/Y/Z). Keep the profile on one side of the axis."""
    scene.revolve(name, profile, axis, angle)
    return _done(name)


@_tool
def loft(name: str, profiles: list[str], ruled: bool = True) -> dict:
    """Loft through a list of profiles (2 or more), e.g. square -> circle."""
    scene.loft(name, profiles, ruled)
    return _done(name)


@_tool
def sweep(name: str, profile: str, path: str) -> dict:
    """Sweep a profile along a path curve."""
    scene.sweep(name, profile, path)
    return _done(name)


# --------------------------------------------------------------------------
# booleans
# --------------------------------------------------------------------------
@_tool
def union(name: str, parts: list[str]) -> dict:
    """Combine two or more objects into one."""
    scene.union(name, parts)
    return _done(name)


@_tool
def subtract(name: str, tools: list[str]) -> dict:
    """Cut the `tools` out of `name` (in place)."""
    scene.subtract(name, tools)
    return _done(name)


@_tool
def intersect(name: str, a: str, b: str) -> dict:
    """Keep only where two objects overlap."""
    scene.intersect(name, a, b)
    return _done(name)


# --------------------------------------------------------------------------
# modify
# --------------------------------------------------------------------------
@_tool
def fillet_edges(name: str, radius: float, select: str = "all") -> dict:
    """Round selected edges. `select` is a selector string, or 'all'."""
    scene.fillet(name, radius, select)
    return _done(name)


@_tool
def chamfer_edges(name: str, length: float, select: str = "all") -> dict:
    """Bevel selected edges."""
    scene.chamfer(name, length, select)
    return _done(name)


@_tool
def shell(name: str, thickness: float, open_faces: str = "none") -> dict:
    """Hollow a solid to a wall of `thickness`. `open_faces` selects faces to remove (e.g. 'normal:Z+')."""
    scene.shell(name, thickness, open_faces)
    return _done(name)


@_tool
def transform(name: str, translate: Optional[list[float]] = None,
              rotate: Optional[list[float]] = None, scale: Optional[float] = None) -> dict:
    """Move / rotate / scale an object in place."""
    scene.transform(name, _at(translate), _at(rotate), scale)
    return _done(name)


@_tool
def mirror_object(name: str, about: str = "YZ", keep_original: bool = True) -> dict:
    """Mirror about a plane ('XY'|'XZ'|'YZ')."""
    scene.mirror(name, about, keep_original)
    return _done(name)


@_tool
def split_object(name: str, plane: str = "XY", offset: float = 0.0, keep: str = "top") -> dict:
    """Cut an object with a plane and keep 'top' or 'bottom'."""
    scene.split(name, plane, offset, keep)
    return _done(name)


@_tool
def pattern_linear(name: str, count: int, spacing: float, direction: str = "X",
                   result: Optional[str] = None) -> dict:
    """Repeat a copy `count` times, step `spacing` along X/Y/Z."""
    scene.pattern_linear(name, count, spacing, direction, result)
    return _done(result or name)


@_tool
def pattern_polar(name: str, count: int, radius: float = 0.0, axis: str = "Z",
                  total_angle: float = 360.0, result: Optional[str] = None) -> dict:
    """Repeat around an axis (optionally on a `radius` circle)."""
    scene.pattern_polar(name, count, radius, axis, total_angle, result)
    return _done(result or name)


@_tool
def place_on_bed(name: str) -> dict:
    """Drop an object so its lowest point sits at z=0 (ready to print)."""
    scene.place_on_bed(name)
    return _done(name)


@_tool
def align_to(name: str, reference: str, face: str = "top", gap: float = 0.0) -> dict:
    """Move `name` so it sits on top of (or under) another object."""
    scene.align_to(name, reference, face, gap)
    return _done(name)


# --------------------------------------------------------------------------
# inspect
# --------------------------------------------------------------------------
@_tool
def get_edges(name: str, select: str = "all", limit: int = 40) -> list[dict]:
    """List edges (centre, length, radius) matching a selector - use before fillet/chamfer."""
    return scene.edges(name, select)[:limit]


@_tool
def get_faces(name: str, select: str = "all", limit: int = 40) -> list[dict]:
    """List planar/curved faces (centre, area) matching a selector."""
    return scene.faces(name, select)[:limit]


@_tool
def distance(a: str, b: str) -> dict:
    """Minimum distance between two objects (mm)."""
    return scene.distance(a, b)


@_tool
def interference(a: str, b: str) -> dict:
    """Do two objects overlap, and by how much?"""
    return scene.interference(a, b)


@_tool
def printability(name: str, max_overhang: float = 45.0,
                 bed: Optional[list[float]] = None, material: str = "PLA") -> dict:
    """Print check: overhang area, support need, bed fit, filament estimate."""
    return scene.printability(name, max_overhang, tuple(bed) if bed else None, material)


# --------------------------------------------------------------------------
# render / export
# --------------------------------------------------------------------------
@_tool
def render_views(names: Optional[list[str]] = None,
                 views: Optional[list[str]] = None, size: int = 520,
                 outline: bool = False) -> list:
    """Render the scene (or chosen objects) to PNG and return the image for you to inspect.

    views: any of iso, iso2, front, back, left, right, top, bottom.
    """
    names = names or scene.names()
    if not names:
        return ["nothing to render - the scene is empty"]
    parts = [(n, scene.get(n)) for n in names]
    views = views or ["iso", "front", "right", "top"]
    os.makedirs(OUT, exist_ok=True)
    path = os.path.join(OUT, "render.png")
    sheet = R.render(parts, views, size=size, outline=outline, path=path)
    return [Image(path=path), f"rendered {names} at {path} ({sheet.width}x{sheet.height})"]


@_tool
def export_part(name: str, format: str = "stl", path: Optional[str] = None) -> str:
    """Write an object to STL (print) or STEP (edit in CAD). Returns the file path."""
    from build123d import export_step, export_stl

    shape = scene.get(name)
    if not len(shape.solids()):
        raise SceneError(f"{name!r} has no solids - it is a 2D profile, not a part")
    os.makedirs(OUT, exist_ok=True)
    ext = format.lower()
    path = path or os.path.join(OUT, f"{name}.{ext}")
    if ext in ("step", "stp"):
        export_step(shape, path)
    elif ext in ("stl", "3mf"):
        export_stl(shape, path, tolerance=0.05, angular_tolerance=0.2)
    else:
        raise SceneError("format must be stl or step")
    return path


@_tool
def export_all(format: str = "stl") -> list[str]:
    """Export every solid object in the scene (2D profiles are skipped)."""
    return [export_part(n, format) for n in scene.names()
            if len(scene.get(n).solids())]


@_tool
def export_script(path: Optional[str] = None) -> str:
    """Save the whole design as a runnable build123d Python script. Returns the path."""
    os.makedirs(OUT, exist_ok=True)
    path = path or os.path.join(OUT, "design.py")
    with open(path, "w") as fh:
        fh.write(script_mod.to_python(scene, export_dir=OUT))
    return path


HELP_TEXT = """\
shapewright - 3D design tools (all sizes in mm)

SCENE
  reset, list_objects, object_info(name), duplicate_object, delete_object

PRIMITIVES            (centred on the origin; use `at`/`rotation` to place)
  create_box(name,length,width,height,at,rotation,corner)
  create_cylinder(name,radius,height,at,rotation,corner)
  create_cone(name,bottom_radius,top_radius,height)
  create_sphere(name,radius)  create_torus(name,major_radius,minor_radius)
  create_prism(name,sides,radius,height,twist,fillet)   # hex handle, twisted polygon

PROFILES -> SOLIDS
  profile_rect/profile_circle/profile_polygon(name,...,plane='XY'|'XZ'|'YZ')
  curve_polyline, curve_helix
  extrude(name,profile,amount,both,taper)  revolve(name,profile,axis,angle)
  loft(name,[profiles...])  sweep(name,profile,path)

BOOLEANS
  union(name,parts)   subtract(name,[tools])   intersect(name,a,b)

MODIFY
  fillet_edges(name,radius,select)   chamfer_edges(name,length,select)
  shell(name,thickness,open_faces)   transform(name,translate,rotate,scale)
  mirror_object, split_object, pattern_linear, pattern_polar
  place_on_bed(name)  align_to(name,reference,face,gap)

INSPECT
  get_edges(name,select)  get_faces(name,select)
  distance(a,b)  interference(a,b)  printability(name,max_overhang,bed,material)

OUTPUT
  render_views(names,views,size)   export_part(name,'stl'|'step')   export_all
  export_script()                  # a real build123d .py you can keep editing

SELECTORS (for edges/faces)
  all | parallel:Z | normal:Z+ | at:zmax|zmin|xmax|... | type:circle|line|plane
  near:(x,y,z) | concave | convex | length>10 | radius>2 | area<50 | first|last
  combine with & (AND) and | (OR):   'parallel:Z & at:zmax'
"""


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()
