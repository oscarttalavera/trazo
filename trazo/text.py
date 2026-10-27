"""Texto con fuentes Hershey de un solo trazo (ideales para plotter)."""
from __future__ import annotations

import numpy as np

from . import geometry as g

FONTS = ["futural", "futuram", "rowmans", "rowmand", "scripts", "scriptc",
         "timesr", "timesrb", "timesi", "cursive", "gothiceng"]

_cache: dict[str, object] = {}


def _font(name: str):
    from HersheyFonts import HersheyFonts
    if name not in _cache:
        f = HersheyFonts()
        f.load_default_font(name if name in f.default_font_names else "futural")
        f.normalize_rendering(1.0)
        _cache[name] = f
    return _cache[name]


def _join(segments) -> list[np.ndarray]:
    paths: list[list] = []
    for a, b in segments:
        if paths and np.allclose(paths[-1][-1], a, atol=1e-9):
            paths[-1].append(b)
        else:
            paths.append([a, b])
    return [np.array(p, float) for p in paths]


def text_paths(text: str, x: float, y: float, cap_height: float, rotation: float = 0.0,
               font: str = "futural", anchor: str = "start", line_spacing: float = 1.6) -> list[np.ndarray]:
    """Devuelve polilíneas en mm (Y arriba). (x, y) es el punto de la línea base."""
    f = _font(font)
    base = _join(f.lines_for_text("H"))
    hp = np.vstack(base)
    y0, cap = hp[:, 1].min(), hp[:, 1].max() - hp[:, 1].min()
    s = cap_height / cap if cap > 0 else cap_height
    out: list[np.ndarray] = []
    for i, line in enumerate(text.split("\n")):
        paths = _join(f.lines_for_text(line))
        if not paths:
            continue
        w = max(p[:, 0].max() for p in paths)
        dx = {"middle": -w / 2, "end": -w}.get(anchor, 0.0)
        m = g.translate(x, y) @ g.rotate(rotation) @ g.translate(0, -i * cap_height * line_spacing) \
            @ g.scale(s) @ g.translate(dx, -y0)
        out += [g.apply(m, p) for p in paths]
    return out
