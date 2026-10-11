"""
shapewright.render - a tiny software renderer (numpy + Pillow).

No GPU, no OpenGL, no OpenCascade viewer needed: it rasterises a tessellated
mesh with flat shading and a painter's algorithm.  Good enough for an agent to
"see" what it built and catch gross mistakes.
"""

from __future__ import annotations

from typing import Iterable, Sequence

import numpy as np
from PIL import Image, ImageDraw

# palette (RGB) used to tell parts apart in an assembly
PALETTE = [
    (218, 210, 194), (197, 141, 96), (120, 160, 190), (150, 190, 150),
    (190, 150, 190), (210, 190, 120), (160, 160, 175), (200, 130, 130),
]

_LIGHT = np.array([0.35, 0.5, 0.79])
_LIGHT = _LIGHT / np.linalg.norm(_LIGHT)


def mesh_of(shape, tolerance: float = 0.15) -> np.ndarray:
    """Tessellate a build123d shape to an (N, 3, 3) float array of triangles."""
    tris: list = []
    for face in shape.faces():
        try:
            verts, idx = face.tessellate(tolerance)
        except Exception:
            continue
        vv = np.array([[p.X, p.Y, p.Z] for p in verts], dtype=float)
        for a, b, c in idx:
            tris.append([vv[a], vv[b], vv[c]])
    return np.array(tris, dtype=float) if tris else np.zeros((0, 3, 3))


def _rot(ax: float, ay: float, az: float) -> np.ndarray:
    ax, ay, az = np.radians([ax, ay, az])
    rx = np.array([[1, 0, 0], [0, np.cos(ax), -np.sin(ax)], [0, np.sin(ax), np.cos(ax)]])
    ry = np.array([[np.cos(ay), 0, np.sin(ay)], [0, 1, 0], [-np.sin(ay), 0, np.cos(ay)]])
    rz = np.array([[np.cos(az), -np.sin(az), 0], [np.sin(az), np.cos(az), 0], [0, 0, 1]])
    return rz @ ry @ rx


VIEWS = {
    "iso": _rot(-64, 0, -30),
    "iso2": _rot(-64, 0, 200),
    "front": _rot(-90, 0, 0),
    "back": _rot(90, 0, 0),
    "right": _rot(0, -90, 0),
    "left": _rot(0, 90, 0),
    "top": _rot(0, 0, 0),
    "bottom": _rot(180, 0, 0),
}


def _panel(tris: np.ndarray, cols: np.ndarray, view: np.ndarray, label: str,
           size: int, bg, outline: bool, pad: float = 0.9) -> Image.Image:
    img = Image.new("RGB", (size, size), bg)
    draw = ImageDraw.Draw(img)
    if len(tris):
        v = tris @ view.T
        n = np.cross(v[:, 1] - v[:, 0], v[:, 2] - v[:, 0])
        a = np.linalg.norm(n, axis=1)
        n = n / np.where(a[:, None] == 0, 1, a[:, None])
        keep = n[:, 2] > 0
        v, n, c = v[keep], n[keep], cols[keep]

        lo, hi = v[:, :, :2].reshape(-1, 2).min(0), v[:, :, :2].reshape(-1, 2).max(0)
        scale = (size * pad) / max((hi - lo).max(), 1e-6)
        offs = (np.array([size, size]) - (hi + lo) * scale) / 2
        pts = (v[:, :, :2] * scale + offs)
        pts[:, :, 1] = size - pts[:, :, 1]

        colored = np.clip(c * (0.28 + 0.72 * np.clip(n @ _LIGHT, 0, 1))[:, None], 0, 255)
        colors = colored.astype(int)

        order = np.argsort(v[:, :, 2].mean(axis=1))
        for i in order:
            col = tuple(int(x) for x in colors[i])
            edge = tuple(int(x * 0.5) for x in colors[i]) if outline else None
            draw.polygon([tuple(p) for p in pts[i]], fill=col, outline=edge)
    draw.text((8, 8), label, fill=(238, 238, 238))
    return img


def render(parts, views: Sequence[str] = ("iso", "front", "right", "top"),
           size: int = 520, tolerance: float = 0.2, outline: bool = False,
           bg=(26, 28, 34), path: str | None = None) -> Image.Image:
    """
    parts : a build123d shape, or a sequence of (name, shape) pairs.
    views : names from VIEWS (or explicit 3x3 arrays).
    """
    if hasattr(parts, "faces"):  # single shape
        parts = [("part", parts)]
    parts = list(parts)

    tri_blocks, col_blocks = [], []
    for i, (_, shape) in enumerate(parts):
        m = mesh_of(shape, tolerance)
        if len(m):
            tri_blocks.append(m)
            col_blocks.append(np.tile(np.array(PALETTE[i % len(PALETTE)]), (len(m), 1)))
    tris = np.vstack(tri_blocks) if tri_blocks else np.zeros((0, 3, 3))
    cols = np.vstack(col_blocks) if col_blocks else np.zeros((0, 3))

    mats = [VIEWS[v] if isinstance(v, str) else v for v in views]
    labels = [v if isinstance(v, str) else "view" for v in views]

    cols_n = 2 if len(mats) > 1 else 1
    rows_n = int(np.ceil(len(mats) / cols_n))
    gap = 6
    sheet = Image.new("RGB", (cols_n * size + gap * (cols_n + 1),
                              rows_n * size + gap * (rows_n + 1)), (12, 13, 16))
    for k, (m, lab) in enumerate(zip(mats, labels)):
        panel = _panel(tris, cols, m, lab, size, bg, outline)
        r, c = divmod(k, cols_n)
        sheet.paste(panel, (gap + c * (size + gap), gap + r * (size + gap)))
    if path:
        sheet.save(path)
    return sheet


def png_bytes(img: Image.Image) -> bytes:
    import io

    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()
