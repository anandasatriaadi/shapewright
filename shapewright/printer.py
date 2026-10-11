"""
shapewright.printer - printability report for a build123d solid.

Gives an agent the things it usually gets wrong: does it fit the bed, how much
of it overhangs (needs support), is it a single watertight solid, roughly how
much filament.
"""

from __future__ import annotations

import math

DENSITY = {"PLA": 1.24, "PETG": 1.27, "ABS": 1.04, "ASA": 1.07,
           "TPU": 1.21, "NYLON": 1.14, "RESIN": 1.10}


def _face_normal(face):
    try:
        return face.normal_at()
    except Exception:
        try:
            return face.normal_at(face.center())
        except Exception:
            return None


def analyze(shape, max_overhang: float = 45.0, bed: tuple | None = None,
            material: str = "PLA", layer: float = 0.2) -> dict:
    """Return a printability dict."""
    bb = shape.bounding_box()
    size = [round(bb.size.X, 2), round(bb.size.Y, 2), round(bb.size.Z, 2)]
    zmin = bb.min.Z

    sin_t = math.sin(math.radians(max_overhang))
    overhang_area = 0.0
    flat_ceiling_area = 0.0
    total_area = 0.0
    bed_tol = zmin + max(0.5 * layer, 1e-6)
    for f in shape.faces():
        area = f.area
        total_area += area
        n = _face_normal(f)
        if n is None:
            continue
        if n.Z < -sin_t and f.center().Z > bed_tol:  # ignore what sits on the bed
            overhang_area += area
            if n.Z < -0.985:
                flat_ceiling_area += area

    solids = list(shape.solids())
    try:
        valid = shape.is_valid()
    except Exception:
        valid = None

    report = {
        "bbox_mm": size,
        "volume_cm3": round(shape.volume / 1000.0, 2),
        "surface_cm2": round(total_area / 100.0, 2),
        "solids": len(solids),
        "valid": valid,
        "overhang_threshold_deg": max_overhang,
        "overhang_area_cm2": round(overhang_area / 100.0, 2),
        "flat_downward_area_cm2": round(flat_ceiling_area / 100.0, 2),
        "needs_support": flat_ceiling_area > 1.0,
        "estimated_grams": {
            m: round(shape.volume / 1000.0 * d, 1) for m, d in
            ([(material, DENSITY.get(material.upper(), 1.24))] if material else DENSITY.items())
        },
    }
    if bed:
        bx, by, bz = bed
        report["bed_mm"] = [bx, by, bz]
        fits = size[0] <= bx and size[1] <= by and size[2] <= bz
        # allow a diagonal fit in XY
        diag = math.hypot(size[0], size[1]) <= math.hypot(bx, by)
        report["fits_bed_upright"] = fits

        # best simple orientation: lay the part down on its largest face
        dims = sorted(size)
        report["fits_bed_if_laid_on_side"] = (dims[0] <= bz and dims[1] <= bx and dims[2] <= by)
        report["fits_bed_diagonal"] = diag
    return report


def check_fit(inner, outer, clearance: float = 0.2) -> dict:
    """How two solids overlap, and total gap if one is meant to slide in another."""
    overlap = inner & outer
    v = getattr(overlap, "volume", 0.0) if overlap is not None else 0.0
    ib, ob = inner.bounding_box(), outer.bounding_box()
    return {
        "interference_cm3": round(v / 1000.0, 4),
        "interferes": v > 1e-6,
        "inner_bbox_mm": [round(ib.size.X, 2), round(ib.size.Y, 2), round(ib.size.Z, 2)],
        "outer_bbox_mm": [round(ob.size.X, 2), round(ob.size.Y, 2), round(ob.size.Z, 2)],
        "clearance_target_mm": clearance,
    }
