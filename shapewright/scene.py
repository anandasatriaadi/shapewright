"""
shapewright.scene - a stateful, agent-friendly wrapper around build123d.

Everything an agent does goes through a :class:`Scene`: a dict of named
solids, plus a running log of equivalent build123d code so the whole design can
be exported as a real, editable script.

Conventions
-----------
* units are millimetres
* primitives are centred on the origin unless ``at`` says otherwise
* every op takes a target name and, by default, edits it in place
* ``at=(x, y, z)`` / ``rotation=(rx, ry, rz)`` place a result in world space
"""

from __future__ import annotations

import math
from collections import OrderedDict
from typing import Iterable, Sequence

from build123d import (
    Align,
    Axis,
    Box,
    Circle,
    Cone,
    Cylinder,
    GeomType,
    Helix,
    Keep,
    Line,
    Plane,
    Polyline,
    Polygon,
    Pos,
    Rectangle,
    RectangleRounded,
    RegularPolygon,
    Rot,
    Solid,
    Sphere,
    Spline,
    Torus,
    chamfer as _chamfer,
    extrude as _extrude,
    fillet as _fillet,
    loft as _loft,
    mirror as _mirror,
    offset as _offset,
    revolve as _revolve,
    scale as _scale,
    section as _section,
    split as _split,
    sweep as _sweep,
)

from . import printer
from .select import describe, select
from .store import ProjectStore

_PLANES = {"XY": Plane.XY, "XZ": Plane.XZ, "YZ": Plane.YZ,
           "yz": Plane.YZ, "xz": Plane.XZ, "xy": Plane.XY}
_KEEP = {"top": Keep.TOP, "bottom": Keep.BOTTOM, "both": Keep.BOTH}


def _place_code(at, rotation) -> str:
    parts = []
    if at and any(abs(x) > 1e-12 for x in at):
        parts.append(f"Pos({at[0]}, {at[1]}, {at[2]})")
    if rotation and any(abs(x) > 1e-12 for x in rotation):
        parts.append(f"Rot({rotation[0]}, {rotation[1]}, {rotation[2]})")
    return " * ".join(parts)


def _apply_place(shape, at, rotation):
    out = shape
    if at and any(abs(x) > 1e-12 for x in at):
        out = Pos(at[0], at[1], at[2]) * out
    if rotation and any(abs(x) > 1e-12 for x in rotation):
        out = Rot(rotation[0], rotation[1], rotation[2]) * out
    return out


class SceneError(Exception):
    pass


class Scene:
    """
    A set of named solids.

    In-memory by default. Pass ``store=ProjectStore(...)`` (or use
    :meth:`Scene.open`) to keep solids as BREP files on disk and hold only a
    bounded LRU cache in RAM. Measurements for ``info`` / ``list_objects`` are
    kept separately, so listing never loads geometry.
    """

    def __init__(self, store=None, cache_size: int = 24, undo_limit: int = 100,
                 persist_every: int = 16) -> None:
        self.store = store
        self.cache_size = int(cache_size)
        self.undo_limit = int(undo_limit)
        self.persist_every = max(1, int(persist_every))
        self.objs: "OrderedDict[str, object]" = OrderedDict()  # live solids
        self._ref: dict[str, str] = {}     # name -> brep filename  (persistent)
        self._meta: dict[str, dict] = {}   # name -> measurements   (persistent)
        self.code: list[str] = []
        self._undo: list[dict] = []
        self._dirty = 0

    # -- persistence -------------------------------------------------------
    @property
    def persistent(self) -> bool:
        return self.store is not None

    @classmethod
    def open(cls, name: str, root: str | None = None, cache_size: int = 24,
             undo_limit: int = 100, persist_every: int = 16) -> "Scene":
        """Open (or create) a disk-backed project."""
        store = ProjectStore(name, root=root, cache_size=cache_size)
        manifest = store.load_manifest()
        store.adopt(manifest)
        scene = cls(store=store, cache_size=cache_size, undo_limit=undo_limit,
                    persist_every=persist_every)
        for obj_name, info in manifest.get("objects", {}).items():
            scene._ref[obj_name] = info["file"]
            scene._meta[obj_name] = {k: v for k, v in info.items() if k != "file"}
        scene.code = list(manifest.get("code", []))
        return scene

    def _measure(self, name: str, shape) -> dict:
        bb = shape.bounding_box()
        c = shape.center()
        return {
            "name": name,
            "bbox_mm": [round(bb.size.X, 3), round(bb.size.Y, 3), round(bb.size.Z, 3)],
            "min_mm": [round(bb.min.X, 3), round(bb.min.Y, 3), round(bb.min.Z, 3)],
            "max_mm": [round(bb.max.X, 3), round(bb.max.Y, 3), round(bb.max.Z, 3)],
            "center_mm": [round(c.X, 3), round(c.Y, 3), round(c.Z, 3)],
            "volume_cm3": round(shape.volume / 1000.0, 3),
            "area_cm2": round(shape.area / 100.0, 3),
            "solids": len(shape.solids()),
            "faces": len(shape.faces()),
            "edges": len(shape.edges()),
        }

    def _persist(self) -> None:
        if not self.persistent:
            return
        self.store.save_manifest({
            "objects": {n: {"file": self._ref[n], **self._meta[n]} for n in self._ref},
            "code": self.code,
        })
        self._dirty = 0
        self._gc()          # safe here: the manifest on disk now matches _ref

    def _touch(self) -> None:
        """Persist the manifest.

        Small projects flush on every change (so they are always discoverable
        and reopenable); once a project is large the manifest is written every
        ``persist_every`` mutations to avoid O(n^2) JSON churn.
        """
        if not self.persistent:
            return
        self._dirty += 1
        every = self.persist_every if len(self._ref) > 24 else 1
        if self._dirty >= every:
            self._persist()

    def flush(self) -> None:
        """Force the manifest to disk and collect unreferenced BREP files."""
        self._persist()

    def _gc(self) -> int:
        if not self.persistent:
            return 0
        live = set(self._ref.values())
        for snap in self._undo:
            live.update(snap.get("ref", {}).values())
        return self.store.gc(live)

    def cache_stats(self) -> dict:
        if not self.persistent:
            return {"persistent": False, "objects": len(self.objs),
                    "cached": len(self.objs)}
        s = self.store.stats()
        s["persistent"] = True
        s["objects"] = len(self._ref)
        return s

    # -- plumbing ----------------------------------------------------------
    def _push_undo(self) -> None:
        if self.persistent:
            # snapshot only names + file refs; the shapes themselves stay on disk
            self._undo.append({"ref": dict(self._ref), "meta": dict(self._meta),
                               "code": list(self.code)})
        else:
            self._undo.append({"objs": OrderedDict(self.objs), "code": list(self.code)})
        if len(self._undo) > self.undo_limit:
            self._undo.pop(0)

    def undo(self) -> bool:
        if not self._undo:
            return False
        snap = self._undo.pop()
        self.code = snap["code"]
        if self.persistent:
            self._ref, self._meta = snap["ref"], snap["meta"]
            self.objs.clear()               # reload lazily from disk
            self.store.clear_cache()
        else:
            self.objs = snap["objs"]
        self._touch()
        return True

    def _evict(self) -> None:
        if not self.persistent:
            return
        while len(self.objs) > self.cache_size:
            self.objs.popitem(last=False)

    def _set(self, name: str, shape, code: str | None = None) -> str:
        self._push_undo()
        if self.persistent:
            self._ref[name] = self.store.write(name, shape)
            self._meta[name] = self._measure(name, shape)
        self.objs[name] = shape
        if self.persistent:
            self.objs.move_to_end(name)
            self._evict()
        if code:
            self.code.append(code)
        self._touch()
        return name

    def get(self, name: str):
        shape = self.objs.get(name)
        if shape is not None:
            if self.persistent:
                self.objs.move_to_end(name)
            return shape
        if self.persistent and name in self._ref:
            shape = self.store.read(self._ref[name])
            self.objs[name] = shape
            self._evict()
            return shape
        raise SceneError(f"no object named {name!r}. Have: {sorted(self.names())}")

    def names(self) -> list[str]:
        return list(self._ref) if self.persistent else list(self.objs)

    def delete(self, name: str) -> str:
        self._push_undo()
        if self.persistent:
            self._ref.pop(name, None)
            self._meta.pop(name, None)
        self.objs.pop(name, None)
        self.code.append(f"del {name}")
        self._touch()
        return name

    def duplicate(self, name: str, new_name: str) -> str:
        return self._set(new_name, self.get(name), f"{new_name} = {name}")

    def reset(self) -> None:
        self._push_undo()
        if self.persistent:
            self._ref.clear()
            self._meta.clear()
        self.objs.clear()
        self.code.clear()
        self.flush()

    # -- primitives --------------------------------------------------------
    def box(self, name, length, width, height, at=(0, 0, 0), rotation=(0, 0, 0),
            corner=None) -> str:
        expr = f"Box({length}, {width}, {height})"
        shape = Box(length, width, height)
        if corner:
            shape = _fillet(shape.edges().filter_by(Axis.Z), radius=corner)
            expr = f"fillet(({expr}).edges().filter_by(Axis.Z), radius={corner})"
        p = _place_code(at, rotation)
        if p:
            expr = f"{p} * ({expr})"
        return self._set(name, _apply_place(shape, at, rotation), f"{name} = {expr}")

    def cylinder(self, name, radius, height, at=(0, 0, 0), rotation=(0, 0, 0),
                 corner=None) -> str:
        expr = f"Cylinder({radius}, {height})"
        shape = Cylinder(radius, height)
        if corner:
            # cylindrical solids have no vertical edges - round the rims instead
            rims = shape.edges().filter_by(GeomType.CIRCLE)
            shape = _fillet(rims, radius=corner)
            expr = f"fillet(({expr}).edges().filter_by(GeomType.CIRCLE), radius={corner})"
        p = _place_code(at, rotation)
        if p:
            expr = f"{p} * ({expr})"
        return self._set(name, _apply_place(shape, at, rotation), f"{name} = {expr}")

    def cone(self, name, bottom_radius, top_radius, height, at=(0, 0, 0),
             rotation=(0, 0, 0)) -> str:
        expr = f"Cone({bottom_radius}, {top_radius}, {height})"
        p = _place_code(at, rotation)
        if p:
            expr = f"{p} * ({expr})"
        return self._set(name, _apply_place(Cone(bottom_radius, top_radius, height), at, rotation),
                         f"{name} = {expr}")

    def sphere(self, name, radius, at=(0, 0, 0)) -> str:
        expr = f"Sphere({radius})"
        p = _place_code(at, (0, 0, 0))
        if p:
            expr = f"{p} * ({expr})"
        return self._set(name, _apply_place(Sphere(radius), at, (0, 0, 0)), f"{name} = {expr}")

    def torus(self, name, major_radius, minor_radius, at=(0, 0, 0),
              rotation=(0, 0, 0)) -> str:
        expr = f"Torus({major_radius}, {minor_radius})"
        p = _place_code(at, rotation)
        if p:
            expr = f"{p} * ({expr})"
        return self._set(name, _apply_place(Torus(major_radius, minor_radius), at, rotation),
                         f"{name} = {expr}")

    def prism(self, name, sides, radius, height, at=(0, 0, 0), rotation=(0, 0, 0),
              twist=0.0, fillet=0.0) -> str:
        """Regular N-gon prism. ``twist`` (deg) turns the section along Z."""
        if abs(twist) > 1e-9:
            shape = _loft([RegularPolygon(radius, sides),
                           Plane.XY.offset(height) * Rot(0, 0, twist) * RegularPolygon(radius, sides)])
            expr = (f"loft([RegularPolygon({radius}, {sides}), Plane.XY.offset({height}) * "
                    f"Rot(0, 0, {twist}) * RegularPolygon({radius}, {sides})])")
        else:
            shape = _extrude(RegularPolygon(radius, sides), amount=height)
            expr = f"extrude(RegularPolygon({radius}, {sides}), amount={height})"
        if fillet:
            z_edges = shape.edges().filter_by(Axis.Z)
            if not len(z_edges):
                raise SceneError("prism: `fillet` only rounds the vertical edges, "
                                 "so it can't be combined with `twist`")
            shape = _fillet(z_edges, radius=fillet)
            expr = f"fillet(({expr}).edges().filter_by(Axis.Z), radius={fillet})"
        p = _place_code(at, rotation)
        if p:
            expr = f"{p} * ({expr})"
        return self._set(name, _apply_place(shape, at, rotation), f"{name} = {expr}")

    # -- 2D profiles -------------------------------------------------------
    def _locate_sketch(self, sketch, plane, at):
        base = _PLANES.get(plane, Plane.XY)
        located = base * sketch
        return _apply_place(located, at, (0, 0, 0))

    def profile_rect(self, name, width, height, corner=0.0, plane="XY", at=(0, 0, 0)) -> str:
        sk = RectangleRounded(width, height, corner) if corner else Rectangle(width, height)
        ctor = (f"RectangleRounded({width}, {height}, {corner})" if corner
                else f"Rectangle({width}, {height})")
        code = f"{name} = {_PLANES.get(plane, Plane.XY)} * {ctor}"
        if any(at):
            code = f"{name} = Pos({at[0]}, {at[1]}, {at[2]}) * {name}"
        return self._set(name, self._locate_sketch(sk, plane, at), code)

    def profile_circle(self, name, radius, plane="XY", at=(0, 0, 0)) -> str:
        code = f"{name} = {_PLANES.get(plane, Plane.XY)} * Circle({radius})"
        if any(at):
            code = f"{name} = Pos({at[0]}, {at[1]}, {at[2]}) * {name}"
        return self._set(name, self._locate_sketch(Circle(radius), plane, at), code)

    def profile_polygon(self, name, points, plane="XY", at=(0, 0, 0)) -> str:
        sk = Polygon(*[tuple(p) for p in points], align=None)
        code = f"{name} = {_PLANES.get(plane, Plane.XY)} * Polygon({points}, align=None)"
        if any(at):
            code = f"{name} = Pos({at[0]}, {at[1]}, {at[2]}) * {name}"
        return self._set(name, self._locate_sketch(sk, plane, at), code)

    def curve_polyline(self, name, points, plane="XY", at=(0, 0, 0)) -> str:
        ln = Polyline(*[tuple(p) for p in points])
        code = f"{name} = {_PLANES.get(plane, Plane.XY)} * Polyline({points})"
        return self._set(name, self._locate_sketch(ln, plane, at), code)

    def curve_helix(self, name, radius, pitch, height, at=(0, 0, 0)) -> str:
        h = Helix(radius, pitch, height)
        code = f"{name} = Helix({radius}, {pitch}, {height})"
        return self._set(name, _apply_place(h, at, (0, 0, 0)), code)

    # -- profile -> solid --------------------------------------------------
    def extrude(self, name, profile, amount, both=False, taper=0.0) -> str:
        sk = self.get(profile)
        kwargs = {"amount": amount, "both": both}
        if taper:
            kwargs["taper"] = taper
        shape = _extrude(sk, **kwargs)
        return self._set(name, shape, f"{name} = extrude({profile}, amount={amount}, both={both})")

    def revolve(self, name, profile, axis="Z", angle=360.0) -> str:
        ax = {"X": Axis.X, "Y": Axis.Y, "Z": Axis.Z}.get(str(axis).upper(), Axis.Z)
        shape = _revolve(self.get(profile), axis=ax, revolution_arc=angle)
        return self._set(name, shape, f"{name} = revolve({profile}, axis=Axis.{str(axis).upper()}, revolution_arc={angle})")

    def loft(self, name, profiles: Sequence[str], ruled=True) -> str:
        secs = [self.get(p) for p in profiles]
        shape = _loft(secs, ruled=ruled)
        return self._set(name, shape, f"{name} = loft([{', '.join(profiles)}], ruled={ruled})")

    def sweep(self, name, profile, path, is_frenet=False) -> str:
        shape = _sweep(self.get(profile), path=self.get(path), is_frenet=is_frenet)
        return self._set(name, shape, f"{name} = sweep({profile}, path={path})")

    # -- booleans ----------------------------------------------------------
    def union(self, name, parts: Sequence[str]) -> str:
        shape = self.get(parts[0])
        for p in parts[1:]:
            shape = shape + self.get(p)
        return self._set(name, shape, f"{name} = {' + '.join(parts)}")

    def subtract(self, name, tools) -> str:
        tools = [tools] if isinstance(tools, str) else list(tools)
        shape = self.get(name)
        for t in tools:
            shape = shape - self.get(t)
        return self._set(name, shape, f"{name} = {name} - ({' + '.join(tools)})")

    def intersect(self, name, a, b) -> str:
        return self._set(name, self.get(a) & self.get(b), f"{name} = {a} & {b}")

    # -- modify ------------------------------------------------------------
    def fillet(self, name, radius, select_spec="all") -> str:
        shape = self.get(name)
        edges = select(shape, "edges", select_spec)
        if not len(edges):
            raise SceneError(f"fillet: no edges matched {select_spec!r} on {name!r}")
        return self._set(name, _fillet(edges, radius=radius),
                         f"{name} = fillet(select({name}, 'edges', {select_spec!r}), radius={radius})")

    def chamfer(self, name, length, select_spec="all") -> str:
        shape = self.get(name)
        edges = select(shape, "edges", select_spec)
        if not len(edges):
            raise SceneError(f"chamfer: no edges matched {select_spec!r} on {name!r}")
        return self._set(name, _chamfer(edges, length=length),
                         f"{name} = chamfer(select({name}, 'edges', {select_spec!r}), length={length})")

    def shell(self, name, thickness, open_faces="none") -> str:
        shape = self.get(name)
        openings = None
        if open_faces not in (None, "none", ""):
            openings = select(shape, "faces", open_faces)
        new = _offset(shape, amount=-abs(thickness), openings=openings)
        return self._set(name, new, f"{name} = offset({name}, amount=-{abs(thickness)}, openings=select({name}, 'faces', {open_faces!r}))")

    def transform(self, name, translate=(0, 0, 0), rotate=(0, 0, 0), scale=None) -> str:
        shape = self.get(name)
        if scale is not None:
            shape = _scale(shape, by=scale)
        if any(rotate):
            shape = Rot(rotate[0], rotate[1], rotate[2]) * shape
        if any(translate):
            shape = Pos(translate[0], translate[1], translate[2]) * shape
        code = (f"{name} = Pos({translate[0]}, {translate[1]}, {translate[2]}) * "
                f"Rot({rotate[0]}, {rotate[1]}, {rotate[2]}) * {name}")
        return self._set(name, shape, code)

    def mirror(self, name, about="YZ", keep=True) -> str:
        plane = {"XY": Plane.XY, "XZ": Plane.XZ, "YZ": Plane.YZ}.get(str(about).upper(), Plane.YZ)
        m = _mirror(self.get(name), about=plane)
        out = (self.get(name) + m) if keep else m
        return self._set(name, out, f"{name} = {name} + mirror({name}, plane=Plane.{str(about).upper()})")

    def split(self, name, plane="XY", offset=0.0, keep="top") -> str:
        pl = {"XY": Plane.XY, "XZ": Plane.XZ, "YZ": Plane.YZ}.get(str(plane).upper(), Plane.XY)
        new = _split(self.get(name), bisect_by=pl.offset(offset), keep=_KEEP.get(keep, Keep.TOP))
        return self._set(name, new, f"{name} = split({name}, bisect_by=Plane.{str(plane).upper()}.offset({offset}), keep=Keep.{keep.upper()})")

    def pattern_linear(self, name, count, spacing, direction="X", result=None) -> str:
        result = result or name
        d = {"X": (1, 0, 0), "Y": (0, 1, 0), "Z": (0, 0, 1)}.get(str(direction).upper(), (1, 0, 0))
        base = self.get(name)
        out = base
        for i in range(1, int(count)):
            out = out + Pos(d[0] * spacing * i, d[1] * spacing * i, d[2] * spacing * i) * base
        code = (f"{result} = {name} + [Pos({d[0]}*{spacing}*i, {d[1]}*{spacing}*i, "
                f"{d[2]}*{spacing}*i) * {name} for i in range(1, {int(count)})]")
        return self._set(result, out, code)

    def pattern_polar(self, name, count, radius=0.0, axis="Z", total_angle=360.0, result=None) -> str:
        result = result or name
        base = self.get(name)
        out = base
        step = total_angle / count
        for i in range(1, int(count)):
            a = math.radians(step * i)
            if str(axis).upper() == "Z":
                x, y = radius * math.cos(a), radius * math.sin(a)
                out = out + Pos(x, y, 0) * Rot(0, 0, math.degrees(a)) * base
            else:
                out = out + Rot(0, 0, math.degrees(a)) * base
        return self._set(result, out, f"{result} = polar_pattern({name}, count={count}, radius={radius})")

    def place_on_bed(self, name) -> str:
        bb = self.get(name).bounding_box()
        return self.transform(name, translate=(0, 0, -bb.min.Z))

    def align_to(self, name, reference, face="top", gap=0.0) -> str:
        """Move ``name`` so it sits on/under a face of ``reference``."""
        ra = self.get(reference)
        me = self.get(name).bounding_box()
        rb = ra.bounding_box()
        dz = {"top": rb.max.Z + gap - me.min.Z,
              "bottom": rb.min.Z - gap - me.max.Z}.get(face, 0.0)
        return self.transform(name, translate=(0, 0, dz))

    # -- queries -----------------------------------------------------------
    def info(self, name) -> dict:
        if self.persistent and name in self._meta:
            d = dict(self._meta[name])
            d["cached"] = name in self.objs
            return d
        return self._measure(name, self.get(name))

    def list_objects(self) -> list[dict]:
        return [self.info(n) for n in self.names()]

    def edges(self, name, spec="all") -> list[dict]:
        return describe(self.get(name), "edges", spec)

    def faces(self, name, spec="all") -> list[dict]:
        return describe(self.get(name), "faces", spec)

    def distance(self, a, b) -> dict:
        d = (self.get(a).center() - self.get(b).center()).length
        try:
            d = self.get(a).distance_to(self.get(b))
            how = "surface"
        except Exception:
            how = "centre-to-centre"
        return {"distance_mm": round(d, 3), "measured": how}

    def interference(self, a, b) -> dict:
        ov = self.get(a) & self.get(b)
        v = getattr(ov, "volume", 0.0) if ov is not None else 0.0
        return {"interference_cm3": round(v / 1000.0, 4), "interferes": v > 1e-6}

    def printability(self, name, max_overhang=45.0, bed=None, material="PLA") -> dict:
        return printer.analyze(self.get(name), max_overhang, bed, material)
