"""Vista previa: SVG del resultado real (ancho de punta) y datos para la UI."""
from __future__ import annotations

import numpy as np

from .gcode import PenJob
from .profiles import MachineProfile, MaterialProfile


def _pts(p: np.ndarray) -> str:
    return " ".join(f"{x:.2f},{y:.2f}" for x, y in p)


def svg(jobs: list[PenJob], m: MachineProfile, mat: MaterialProfile, drawable, travels: bool = True) -> str:
    bx0, by0 = min(m.x_min + m.pen_offset_x, 0), min(m.y_min + m.pen_offset_y, 0)
    bx1 = max(m.x_max + m.pen_offset_x, m.x_max)
    by1 = max(m.y_max + m.pen_offset_y, m.y_max)
    W, H = bx1 - bx0 + 10, by1 - by0 + 10
    out = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{W * 3:.0f}" height="{H * 3:.0f}" '
           f'viewBox="{bx0 - 5:.2f} {-by1 - 5:.2f} {W:.2f} {H:.2f}">',
           f'<rect x="{bx0 - 5}" y="{-by1 - 5}" width="{W}" height="{H}" fill="#e9e9e4"/>',
           '<g transform="scale(1,-1)">',
           f'<rect x="{m.x_min}" y="{m.y_min}" width="{m.x_max - m.x_min}" height="{m.y_max - m.y_min}" '
           'fill="#d4d4cf" stroke="#999" stroke-width="0.3"/>',
           f'<rect x="{mat.origin_x}" y="{mat.origin_y}" width="{mat.width}" height="{mat.height}" '
           'fill="#ffffff" stroke="#bbb" stroke-width="0.3"/>',
           f'<rect x="{drawable[0]}" y="{drawable[1]}" width="{drawable[2] - drawable[0]}" '
           f'height="{drawable[3] - drawable[1]}" fill="none" stroke="#4a90d9" stroke-width="0.3" '
           'stroke-dasharray="2 1"/>']
    pos = np.array([m.park_x + m.pen_offset_x, m.park_y + m.pen_offset_y])
    for j in jobs:
        out.append(f'<g fill="none" stroke="{j.pen.color}" stroke-width="{j.pen.tip}" '
                   'stroke-linecap="round" stroke-linejoin="round" opacity="0.9">')
        for p in j.paths:
            if len(p) == 1:
                out.append(f'<circle cx="{p[0, 0]:.2f}" cy="{p[0, 1]:.2f}" r="{j.pen.tip / 2}" '
                           f'fill="{j.pen.color}" stroke="none"/>')
            else:
                out.append(f'<polyline points="{_pts(p)}"/>')
        out.append("</g>")
        if travels:
            segs = []
            for p in j.paths:
                segs.append(f"M{pos[0]:.2f},{pos[1]:.2f}L{p[0, 0]:.2f},{p[0, 1]:.2f}")
                pos = p[-1]
            out.append(f'<path d="{"".join(segs)}" fill="none" stroke="#e5484d" stroke-width="0.15" '
                       'stroke-dasharray="0.8 0.6" opacity="0.7"/>')
    out.append("</g></svg>")
    return "\n".join(out)


def to_json(jobs: list[PenJob], decimals: int = 2) -> list[dict]:
    """Trayectorias compactas: lista plana [x0,y0,x1,y1,...] por trazo."""
    out = []
    for j in jobs:
        out.append({
            "pen": j.pen.name, "color": j.pen.color, "tip": j.pen.tip, "label": j.label,
            "paths": [np.round(p, decimals).ravel().tolist() for p in j.paths],
        })
    return out
