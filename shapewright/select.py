"""
shapewright.select - a small, forgiving selector language for edges / faces / vertices.

Agents are bad at build123d's ShapeList gymnastics (filter_by / group_by /
sort_by chains).  This turns edge & face picking into a string spec, e.g.

    "parallel:Z & at:zmax"          top edges running along Z
    "type:circle & radius>2"        all round edges bigger than 2 mm
    "normal:Z+ & at:zmin"           the bottom face
    "concave"                       every concave edge (the ones worth filleting)
    "near:(0,0,50)"                 the single edge/face/vertex closest to a point

Predicates are combined with ``&`` (AND) and ``|`` (OR).
"""

from __future__ import annotations

import re

from build123d import Axis, Convexity, GeomType, ShapeList, Vector

_NUM = re.compile(r"-?\d+\.?\d*(?:[eE][-+]?\d+)?")

_NAMED_DIR = {
    "X": (1, 0, 0), "Y": (0, 1, 0), "Z": (0, 0, 1),
    "+X": (1, 0, 0), "+Y": (0, 1, 0), "+Z": (0, 0, 1),
    "-X": (-1, 0, 0), "-Y": (0, -1, 0), "-Z": (0, 0, -1),
}

_GEOM = {
    "line": GeomType.LINE, "circle": GeomType.CIRCLE, "plane": GeomType.PLANE,
    "cylinder": GeomType.CYLINDER, "cone": GeomType.CONE, "sphere": GeomType.SPHERE,
    "torus": GeomType.TORUS, "bspline": GeomType.BSPLINE, "ellipse": GeomType.ELLIPSE,
    "bezier": GeomType.BEZIER, "other": GeomType.OTHER,
}


def _vec(token: str) -> Vector:
    t = token.strip().upper()
    if t in _NAMED_DIR:
        return Vector(*_NAMED_DIR[t])
    if len(t) == 2 and t[0] in "XYZ" and t[1] in "+-":
        v = list(_NAMED_DIR[t[0]])
        if t[1] == "-":
            v = [-c for c in v]
        return Vector(*v)
    nums = _NUM.findall(token)
    if len(nums) >= 3:
        return Vector(float(nums[0]), float(nums[1]), float(nums[2]))
    raise ValueError(f"cannot read vector from {token!r}")


def _parse_dir(token: str) -> tuple[Vector, bool]:
    """Return (direction, signed). 'Z' is unsigned; 'Z+' / '-Z' are signed."""
    t = token.strip().upper()
    if t in ("X", "Y", "Z"):
        return Vector(*_NAMED_DIR[t]), False
    if t in ("+X", "+Y", "+Z", "-X", "-Y", "-Z"):
        return Vector(*_NAMED_DIR[t]), True
    if len(t) == 2 and t[0] in "XYZ" and t[1] in "+-":
        v = list(_NAMED_DIR[t[0]])
        if t[1] == "-":
            v = [-c for c in v]
        return Vector(*v), True
    return _vec(token), False


def _num(token: str) -> float:
    nums = _NUM.findall(token)
    if not nums:
        raise ValueError(f"expected a number in {token!r}")
    return float(nums[0])


def _parallel(a: Vector, b: Vector, tol: float = 2e-2) -> bool:
    if a is None or b is None:
        return False
    la, lb = a.length, b.length
    if la < 1e-9 or lb < 1e-9:
        return False
    return a.cross(b).length <= tol * la * lb


def _edge_dir(e):
    try:
        return e % 0.5
    except Exception:
        return None


def _face_normal(f):
    try:
        return f.normal_at()
    except Exception:
        try:
            return f.normal_at(f.center())
        except Exception:
            return None


def _elements(shape, kind: str) -> ShapeList:
    kind = {"edge": "edges", "face": "faces", "vertex": "vertices"}.get(kind, kind)
    if kind not in ("edges", "faces", "vertices"):
        raise ValueError(f"kind must be edges/faces/vertices, got {kind!r}")
    return ShapeList(list(getattr(shape, kind)()))


def _apply(cur: ShapeList, kind: str, pred: str) -> ShapeList:
    p = pred.strip()
    low = p.lower()

    if low in ("all", "*", ""):
        return cur
    if low in ("convex", "concave", "smooth", "saddle"):
        return cur.filter_by(
            {"convex": Convexity.CONVEX, "concave": Convexity.CONCAVE,
             "smooth": Convexity.SMOOTH, "saddle": Convexity.SADDLE}[low]
        )
    if low.startswith(("dir:", "parallel:", "axis:", "normal:")):
        d, signed = _parse_dir(p.split(":", 1)[1])
        if kind == "faces":
            return ShapeList([x for x in cur if (n := _face_normal(x)) is not None
                              and _parallel(n, d) and (not signed or n.dot(d) > 0)])
        if kind == "edges":
            return ShapeList([x for x in cur if (t := _edge_dir(x)) is not None
                              and _parallel(t, d) and (not signed or t.dot(d) > 0)])
        return ShapeList([])
    if low.startswith("type:"):
        t = low.split(":", 1)[1].strip()
        if t not in _GEOM:
            raise ValueError(f"unknown geom type {t!r}; try {sorted(_GEOM)}")
        return ShapeList([x for x in cur if x.geom_type == _GEOM[t]])
    if low.startswith("at:"):
        body = low.split(":", 1)[1].strip()
        axis = {"x": Axis.X, "y": Axis.Y, "z": Axis.Z}.get(body[:1])
        if axis is None:
            raise ValueError(f"bad 'at:' spec {pred!r} (use xmin/xmax/ymin/ymax/zmin/zmax)")
        groups = cur.group_by(axis)
        return {  # type: ignore[return-value]
            "max": ShapeList(groups[-1]), "min": ShapeList(groups[0]),
        }.get(body[1:], ShapeList(groups[0]))
    if low.startswith("near:"):
        point = _vec(p.split(":", 1)[1])
        ranked = sorted(cur, key=lambda x: (x.center() - point).length)
        return ShapeList(ranked[:1])
    if low.startswith("where:"):
        raise ValueError("the 'where:' hook is not supported; use dir/type/at/near/metrics")

    m = re.match(r"(length|radius|area|diameter)\s*(>=|<=|>|<|=)\s*(.+)", low)
    if m:
        metric, op, val = m.group(1), m.group(2), _num(m.group(3))

        def value(x):
            if metric == "area":
                return x.area
            if metric == "length":
                return x.length
            try:
                r = x.radius
            except Exception:
                r = None
            if callable(r):
                try:
                    r = r()
                except Exception:
                    return -1.0
            if r is None:
                return -1.0
            return 2 * r if metric == "diameter" else float(r)

        cmp = {">": lambda v: v > val, "<": lambda v: v < val,
               ">=": lambda v: v >= val, "<=": lambda v: v <= val,
               "=": lambda v: abs(v - val) < 1e-6}[op]
        return ShapeList([x for x in cur if cmp(value(x))])

    if low in ("first", "last"):
        return ShapeList([cur[0]] if low == "first" else [cur[-1]])
    if low in ("longest", "shortest", "largest", "smallest"):
        key = (lambda x: x.length) if low in ("longest", "shortest") else (lambda x: x.area)
        ranked = sorted(cur, key=key, reverse=low in ("longest", "largest"))
        return ShapeList(ranked[:1])
    m = re.match(r"(?:index|i)\s*[:=]\s*(\d+)", low)
    if m:
        return ShapeList([cur[int(m.group(1))]])

    raise ValueError(
        f"unknown selector {pred!r}. Examples: 'parallel:Z', 'at:zmax', "
        f"'type:circle', 'radius>2', 'concave', 'near:(0,0,10)', 'normal:Z+'"
    )


def select(shape, kind: str = "edges", spec: str = "all") -> ShapeList:
    """Return the elements of ``shape`` matching the selector ``spec``."""
    items = _elements(shape, kind)
    if not spec or spec.strip().lower() in ("all", "*"):
        return items

    out: list = []
    for group in spec.split("|"):
        cur = items
        for pred in (g for g in group.split("&") if g.strip()):
            cur = _apply(cur, kind, pred)
        out.extend(list(cur))

    uniq: list = []
    for s in out:
        if not any(s.is_same(u) for u in uniq):
            uniq.append(s)
    return ShapeList(uniq)


def describe(shape, kind: str = "edges", spec: str = "all", limit: int = 40) -> list[dict]:
    """Human/agent-readable listing of selected elements."""
    rows = []
    for i, x in enumerate(select(shape, kind, spec)):
        c = x.center()
        row = {"i": i, "center": [round(c.X, 3), round(c.Y, 3), round(c.Z, 3)],
               "geom": str(getattr(x, "geom_type", "")).split(".")[-1].lower()}
        if kind == "edges":
            row["length"] = round(x.length, 3)
            try:
                r = x.radius
            except Exception:
                r = None
            if callable(r):
                try:
                    r = r()
                except Exception:
                    r = None
            if r is not None:
                try:
                    row["radius"] = round(float(r), 3)
                except Exception:
                    pass
        if kind == "faces":
            row["area"] = round(x.area, 3)
        rows.append(row)
        if len(rows) >= limit:
            break
    return rows
