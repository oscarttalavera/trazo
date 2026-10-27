"""Importador SVG (svgelements).

- Respeta width/height/viewBox y transformaciones: el resultado queda en mm reales.
- Cada elemento con stroke y fill genera dos Items (trazo y relleno).
- La capa es la etiqueta de capa de Inkscape (o el id del grupo superior).
- El texto <text> se dibuja con fuentes Hershey de un trazo.
"""
from __future__ import annotations

import math

import numpy as np
import svgelements as se

from .. import geometry as g
from .. import text as htext

PX_TO_MM = 25.4 / 96.0
INK_LABEL = "{http://www.inkscape.org/namespaces/inkscape}label"


def _flatten(path: se.Path, tol_px: float) -> tuple[list[np.ndarray], list[bool]]:
    subpaths, closed = [], []
    cur: list = []
    is_closed = False

    def flush():
        nonlocal cur, is_closed
        if len(cur) >= 1:
            subpaths.append(np.array(cur, float))
            closed.append(is_closed)
        cur, is_closed = [], False

    for seg in path:
        if isinstance(seg, se.Move):
            flush()
            cur = [(seg.end.x, seg.end.y)]
        elif isinstance(seg, se.Close):
            if cur:
                cur.append(cur[0])
                is_closed = True
            flush()
        elif isinstance(seg, se.Line):
            if not cur:
                cur = [(seg.start.x, seg.start.y)]
            cur.append((seg.end.x, seg.end.y))
        else:  # curvas: Cubic, Quadratic, Arc
            if not cur:
                cur = [(seg.start.x, seg.start.y)]
            try:
                L = seg.length(error=1e-3)
            except Exception:  # noqa: BLE001 - segmentos degenerados
                L = 0.0
            n = max(2, min(2000, int(math.ceil(L / max(tol_px * 4, 1e-3)))))
            pts = seg.npoint(np.linspace(0, 1, n + 1)[1:])
            cur.extend(map(tuple, pts))
    flush()
    return subpaths, closed


def load(path: str, curve_tol: float = 0.05, text_font: str = "futural", **_) -> g.Document:
    doc = g.Document(source=path)
    svg = se.SVG.parse(path, reify=True, ppi=96)
    tol_px = curve_tol / PX_TO_MM
    # px (Y abajo) -> mm (Y arriba); se usa la altura del documento para voltear
    height_px = float(svg.height or 0) or None
    flip = None

    for el in svg.elements():
        if isinstance(el, se.Group) or el is svg:
            continue
        values = getattr(el, "values", {})
        if values.get("visibility") in ("hidden", "collapse"):
            continue
        layer = values.get(INK_LABEL) or "0"

        if isinstance(el, se.Text):
            if not el.text:
                continue
            m = el.transform
            sx = math.sqrt(abs(m.a * m.d - m.b * m.c)) or 1.0
            p = m.point_in_matrix_space(se.Point(el.x, el.y))
            rot = -math.degrees(math.atan2(m.b, m.a))
            color = el.fill if el.fill is not None and el.fill.value is not None else el.stroke
            item_paths = htext.text_paths(
                el.text, p.x * PX_TO_MM, -p.y * PX_TO_MM, 0.7 * el.font_size * sx * PX_TO_MM,
                rotation=rot, font=text_font, anchor=getattr(el, "anchor", "start") or "start")
            if item_paths:
                doc.items.append(g.Item("stroke", item_paths, [False] * len(item_paths),
                                        _hex(color), 0.0, layer))
            continue

        if isinstance(el, se.Image):
            doc.warnings.append("SVG con imagen incrustada: se ignora (impórtela como PNG/JPG).")
            continue
        if not isinstance(el, se.Shape):
            continue

        try:
            sp = se.Path(el)
        except Exception:  # noqa: BLE001
            continue
        if len(sp) == 0:
            continue
        subpaths, closed = _flatten(sp, tol_px)
        subpaths = [np.column_stack([p[:, 0] * PX_TO_MM, -p[:, 1] * PX_TO_MM]) for p in subpaths]
        if not subpaths:
            continue

        stroke, fill = el.stroke, el.fill
        has_stroke = stroke is not None and stroke.value is not None and stroke.alpha > 0
        has_fill = fill is not None and fill.value is not None and fill.alpha > 0
        if has_fill:
            # se cierran todos los subtrayectos para el relleno (regla SVG)
            fp = [g.close_path(p) for p in subpaths if len(p) >= 3]
            if fp:
                doc.items.append(g.Item("fill", fp, [True] * len(fp), _hex(fill), 0.0, layer))
        if has_stroke:
            sw = float(getattr(el, "implicit_stroke_width", None) or el.stroke_width or 0.0) * PX_TO_MM
            doc.items.append(g.Item("stroke", subpaths, closed, _hex(stroke), sw, layer))

    # Y queda negativa: se desplaza para que el documento empiece en 0
    if height_px:
        flip = g.translate(0, height_px * PX_TO_MM)
        doc = doc.transformed(flip)
        doc.extent = (0.0, 0.0, float(svg.width or 0) * PX_TO_MM, height_px * PX_TO_MM)
    return doc


def _hex(c) -> str:
    if c is None or getattr(c, "value", None) is None:
        return "#000000"
    return g.normalize_color(c.hex)
