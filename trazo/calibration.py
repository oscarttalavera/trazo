"""Patrón de calibración para una pluma.

Incluye:
  * 5 cuadros rellenos con traslape 0-40 % -> elegir el que cubre sin saturar.
  * Escalera de líneas separadas 1.0x, 1.5x y 2x la punta -> ver ancho real.
  * Regla de hasta 100 mm con marcas cada 10 mm -> verificar escala (pasos/mm).
  * Círculo de 20 mm -> holgura de correas (debe cerrar sin escalón).
"""
from __future__ import annotations

import numpy as np
from shapely.geometry import Point, box

from . import fill as F
from . import optimize as opt
from .gcode import PenJob
from .profiles import PenProfile
from .text import text_paths


def pattern(pen: PenProfile, area) -> PenJob:
    x0, y0, x1, y1 = area
    tip = pen.tip
    paths: list[np.ndarray] = []
    top = y1 - 2
    paths += text_paths(f"Trazo - {pen.name} - punta {tip:g} mm", x0 + 2, top - 4, 4)

    # cuadros de traslape
    size, gap = 10.0, 4.0
    y = top - 10 - size
    fs = F.FillSettings(pattern="zigzag", angle=45, outline=True)
    for i, ov in enumerate([0.0, 0.1, 0.2, 0.3, 0.4]):
        x = x0 + 2 + i * (size + gap)
        r = F.fill_geometry(box(x, y, x + size, y + size), tip, ov, fs)
        paths += r.paths
        paths += text_paths(f"{int(ov * 100)}%", x + 1, y - 5, 2.5)

    # escalera de líneas
    y -= 12
    ly = y - 12
    lx = x0 + 2
    for mult in (1.0, 1.5, 2.0):
        for k in range(6):
            xx = lx + k * tip * mult
            paths.append(np.array([[xx, ly], [xx, ly + 10]]))
        paths += text_paths(f"{mult:g}x", lx, ly - 5, 2.5)
        lx += 6 * tip * mult + 8

    # círculo de 20 mm
    cx, cy = lx + 12, ly + 5
    c = np.asarray(Point(cx, cy).buffer(10, quad_segs=64).exterior.coords)
    paths.append(c)

    # regla
    L = float(min(100.0, (x1 - x0) - 4))
    L -= L % 10
    ry = ly - 16
    paths.append(np.array([[x0 + 2, ry], [x0 + 2 + L, ry]]))
    for k in range(int(L // 10) + 1):
        xx = x0 + 2 + k * 10
        h = 4 if k % 5 == 0 else 2
        paths.append(np.array([[xx, ry], [xx, ry + h]]))
    paths += text_paths(f"{L:g} mm", x0 + 2, ry - 6, 2.5)

    paths = opt.order(opt.prepare(paths), (x0, y1), tip * 0.5)
    return PenJob(pen, paths, "calibración")
