"""Importador DXF (ezdxf).

Soporta LINE, (LW)POLYLINE con arcos, ARC, CIRCLE, ELLIPSE, SPLINE, SOLID,
HATCH (como relleno), POINT, TEXT/MTEXT (Hershey) y bloques INSERT anidados.
"""
from __future__ import annotations

import numpy as np
import ezdxf
from ezdxf import colors as dxfcolors
from ezdxf import path as dxfpath
from ezdxf import recover

from .. import geometry as g
from .. import text as htext

# $INSUNITS -> factor a mm
UNITS = {0: 1.0, 1: 25.4, 2: 304.8, 4: 1.0, 5: 10.0, 6: 1000.0, 8: 25.4e-6, 9: 0.0254,
         10: 914.4, 13: 1e-3, 14: 100.0}


def _read(path: str):
    try:
        return ezdxf.readfile(path)
    except ezdxf.DXFStructureError:
        doc, _auditor = recover.readfile(path)
        return doc


def _color(e, doc) -> str:
    try:
        if e.dxf.hasattr("true_color"):
            r, gg, b = ezdxf.colors.int2rgb(e.dxf.true_color)
            return "#%02x%02x%02x" % (r, gg, b)
        aci = e.dxf.get("color", 256)
        if aci in (0, 256):  # BYBLOCK / BYLAYER
            name = e.dxf.layer
            aci = abs(doc.layers.get(name).dxf.color) if doc.layers.has_entry(name) else 7
        if aci == 7:
            return "#000000"
        r, gg, b = dxfcolors.aci2rgb(aci)
        return "#%02x%02x%02x" % (r, gg, b)
    except Exception:  # noqa: BLE001
        return "#000000"


def _expand(entities, depth=0, parent=None):
    """Explota bloques. Lo que está en capa 0 / color BYBLOCK hereda del INSERT."""
    for e in entities:
        if parent is not None:
            if e.dxf.get("layer", "0") == "0":
                e.dxf.layer = parent.dxf.get("layer", "0")
            if e.dxf.get("color", 256) == 0:
                e.dxf.color = parent.dxf.get("color", 256)
                if parent.dxf.hasattr("true_color"):
                    e.dxf.true_color = parent.dxf.true_color
        if e.dxftype() == "INSERT" and depth < 16:
            try:
                yield from _expand(e.virtual_entities(), depth + 1, e)
            except Exception:  # noqa: BLE001
                continue
        else:
            yield e


def load(path: str, curve_tol: float = 0.05, text_font: str = "futural",
         dxf_closed_as_fill: bool = False, dxf_use_lineweight: bool = False, **_) -> g.Document:
    out = g.Document(source=path)
    doc = _read(path)
    k = UNITS.get(int(doc.header.get("$INSUNITS", 0)), 1.0)
    if int(doc.header.get("$INSUNITS", 0)) == 0:
        out.warnings.append("DXF sin unidades ($INSUNITS=0): se asume milímetros.")
    tol = curve_tol / k
    skipped: dict[str, int] = {}

    for e in _expand(doc.modelspace()):
        t = e.dxftype()
        layer = e.dxf.get("layer", "0")
        lay = doc.layers.get(layer) if doc.layers.has_entry(layer) else None
        if lay is not None and (lay.is_off() or lay.is_frozen()):
            continue
        color = _color(e, doc)
        try:
            if t in ("TEXT", "MTEXT", "ATTRIB"):
                if t == "MTEXT":
                    txt = e.plain_text()
                    h = e.dxf.get("char_height", 2.5)
                    ins = e.dxf.insert
                    rot = e.get_rotation() if hasattr(e, "get_rotation") else e.dxf.get("rotation", 0)
                else:
                    txt = e.dxf.text
                    h = e.dxf.get("height", 2.5)
                    ins = e.dxf.insert
                    rot = e.dxf.get("rotation", 0)
                paths = htext.text_paths(txt, ins.x * k, ins.y * k, h * k, rot, text_font)
                if paths:
                    out.items.append(g.Item("stroke", paths, [False] * len(paths), color, 0, layer))
                continue
            if t == "POINT":
                p = e.dxf.location
                out.items.append(g.Item("stroke", [np.array([[p.x * k, p.y * k]])], [False], color, 0, layer))
                continue
            if t == "HATCH" or t == "SOLID":
                paths = list(dxfpath.from_hatch(e)) if t == "HATCH" else [dxfpath.make_path(e)]
                polys = []
                for p in paths:
                    for sp in p.sub_paths():
                        pts = np.array([(v.x, v.y) for v in sp.flattening(tol)]) * k
                        if len(pts) >= 3:
                            polys.append(g.close_path(pts))
                if polys:
                    out.items.append(g.Item("fill", polys, [True] * len(polys), color, 0, layer))
                continue

            p = dxfpath.make_path(e)
        except (TypeError, ValueError, AttributeError, ezdxf.DXFError):
            skipped[t] = skipped.get(t, 0) + 1
            continue

        subs, closed = [], []
        for sp in p.sub_paths():
            pts = np.array([(v.x, v.y) for v in sp.flattening(tol)], float)
            if len(pts) == 0:
                continue
            pts *= k
            subs.append(pts)
            closed.append(bool(sp.is_closed) or (len(pts) > 2 and np.allclose(pts[0], pts[-1])))
        if not subs:
            continue
        width = 0.0
        if t == "LWPOLYLINE" and e.dxf.get("const_width", 0):
            width = e.dxf.const_width * k
        elif dxf_use_lineweight and e.dxf.get("lineweight", -1) > 0:
            width = e.dxf.lineweight / 100.0
        is_fill = dxf_closed_as_fill and all(closed)
        out.items.append(g.Item("fill" if is_fill else "stroke",
                                [g.close_path(s) for s in subs] if is_fill else subs,
                                closed, color, width, layer))
    if skipped:
        out.warnings.append("Entidades DXF no soportadas: " +
                            ", ".join(f"{t} ({n})" for t, n in skipped.items()))
    return out
