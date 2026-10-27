"""Conversión de elementos a trayectorias según el diámetro de la punta.

Reglas:
  * Relleno: la región se contrae medio diámetro (compensación de herramienta)
    para que la tinta llegue justo al borde del diseño. Se dibuja el contorno
    (1..n pasadas) y el interior con el patrón elegido; separación entre
    pasadas = diámetro * (1 - traslape).
  * Partes más delgadas que la punta: se dibujan por su eje central.
  * Trazo más ancho que la punta: se convierte en región y se rellena con
    pasadas paralelas (concéntricas por defecto).
  * Densidad < 100 % (escala de grises con una sola pluma): se abre la
    separación entre líneas para cubrir solo esa fracción del área.
      líneas/zigzag/concéntrico: separación = punta / d
      cruzado (dos direcciones): separación = punta / (1 - sqrt(1 - d))
"""
from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np
import shapely
from shapely.geometry import LineString, MultiPolygon, Point, Polygon
from shapely.geometry.base import BaseGeometry
from shapely import affinity

from .geometry import Item

PATTERNS = ("lines", "zigzag", "cross", "concentric", "none")


@dataclass
class FillSettings:
    pattern: str = "zigzag"     # lines | zigzag | cross | concentric | none
    angle: float = 45.0
    outline: bool = True
    outline_passes: int = 1
    fill_rule: str = "evenodd"  # evenodd | nonzero
    compensate: bool = True
    thin: str = "centerline"    # centerline | outline | skip
    outline_light: bool = False  # dibujar contorno también en densidades < 100 %
    link_light: bool = False     # enlazar líneas (zigzag) en densidades < 100 %: menos levantadas, marca bordes


@dataclass
class StrokeSettings:
    mode: str = "width"         # width (respeta el ancho del diseño) | single (siempre 1 pasada)
    tolerance: float = 0.3      # margen sobre la punta antes de hacer más pasadas
    pattern: str = "concentric"
    min_width: float = 0.0      # ignora/avisa trazos más finos que esto (0 = no)


@dataclass
class Result:
    paths: list[np.ndarray]
    thin_features: int = 0
    lost_area: float = 0.0


# --- Regiones --------------------------------------------------------------

def _xor_all(geoms: list[BaseGeometry]) -> BaseGeometry:
    if not geoms:
        return Polygon()
    while len(geoms) > 1:  # reducción balanceada
        nxt = [shapely.symmetric_difference(geoms[i], geoms[i + 1]) for i in range(0, len(geoms) - 1, 2)]
        if len(geoms) % 2:
            nxt.append(geoms[-1])
        geoms = nxt
    return geoms[0]


def region(item: Item, rule: str = "evenodd") -> BaseGeometry:
    polys = []
    for p in item.paths:
        if len(p) >= 3:
            poly = shapely.make_valid(Polygon(p))
            poly = _polygonal(poly)
            if not poly.is_empty:
                polys.append(poly)
    if rule == "nonzero":
        return shapely.union_all(polys) if polys else Polygon()
    return _polygonal(shapely.make_valid(_xor_all(polys)))


def _polygonal(geom: BaseGeometry) -> BaseGeometry:
    """Extrae solo la parte poligonal de una geometría (descarta líneas/puntos)."""
    if geom.is_empty:
        return Polygon()
    if isinstance(geom, (Polygon, MultiPolygon)):
        return geom
    parts = [g for g in getattr(geom, "geoms", []) if isinstance(g, (Polygon, MultiPolygon))]
    return shapely.union_all(parts) if parts else Polygon()


def _polys(geom: BaseGeometry) -> list[Polygon]:
    if geom.is_empty:
        return []
    if isinstance(geom, Polygon):
        return [geom]
    out = []
    for gg in getattr(geom, "geoms", []):
        out += _polys(gg)
    return out


def _rings(geom: BaseGeometry) -> list[np.ndarray]:
    out = []
    for p in _polys(geom):
        out.append(np.asarray(p.exterior.coords))
        out += [np.asarray(r.coords) for r in p.interiors]
    return [r for r in out if len(r) >= 3]


def _lines(geom: BaseGeometry) -> list[np.ndarray]:
    if geom.is_empty:
        return []
    if isinstance(geom, LineString):
        return [np.asarray(geom.coords)]
    out = []
    for gg in getattr(geom, "geoms", []):
        out += _lines(gg)
    return out


# --- Patrones de relleno ---------------------------------------------------

def _hatch(geom: BaseGeometry, spacing: float, angle: float, link: bool, tip: float) -> list[np.ndarray]:
    if geom.is_empty or spacing <= 0:
        return []
    rot = affinity.rotate(geom, -angle, origin=(0, 0))
    minx, miny, maxx, maxy = rot.bounds
    # rejilla global (múltiplos de spacing) para que figuras vecinas alineen
    k0 = math.floor(miny / spacing)
    ys = (np.arange(k0, math.ceil(maxy / spacing) + 1) + 0.5) * spacing
    ys = ys[(ys > miny) & (ys < maxy)]
    if len(ys) == 0:  # región más angosta que la separación: una línea al centro
        ys = np.array([(miny + maxy) / 2])
    scan = shapely.linestrings([[[minx - 1, y], [maxx + 1, y]] for y in ys])
    shapely.prepare(rot)
    inter = shapely.intersection(scan, rot)
    rows: list[list[np.ndarray]] = []
    for gg in inter:
        segs = [s for s in _lines(gg) if len(s) >= 2]
        segs = [s[[0, -1]] if s[0, 0] <= s[-1, 0] else s[[-1, 0]] for s in segs]
        rows.append(sorted(segs, key=lambda s: s[0, 0]))

    if link:
        paths = _zigzag(rows, rot, spacing, tip)
    else:
        paths = [s for r in rows for s in r]
    a = math.radians(angle)
    c, s_ = math.cos(a), math.sin(a)
    R = np.array([[c, -s_], [s_, c]])
    return [p @ R.T for p in paths]


def _zigzag(rows, rot, spacing, tip) -> list[np.ndarray]:
    """Une líneas de filas consecutivas si el conector queda dentro de la región."""
    tol = min(0.05, tip * 0.1)
    zone = rot.buffer(tol)
    shapely.prepare(zone)
    remaining = [list(r) for r in rows]
    out = []
    max_link = spacing * 3.0
    for j in range(len(remaining)):
        while remaining[j]:
            seg = remaining[j].pop(0)
            chain = [seg[0], seg[1]]
            forward = True
            jj = j + 1
            while jj < len(remaining) and remaining[jj]:
                end = chain[-1]
                forward = not forward
                # siguiente segmento empieza por el extremo más cercano
                cand = remaining[jj]
                if forward:
                    dists = [np.hypot(*(c[0] - end)) for c in cand]
                else:
                    dists = [np.hypot(*(c[1] - end)) for c in cand]
                k = int(np.argmin(dists))
                if dists[k] > max_link:
                    break
                nseg = cand[k] if forward else cand[k][::-1]
                if not zone.covers(LineString([end, nseg[0]])):
                    break
                cand.pop(k)
                chain += [nseg[0], nseg[1]]
                jj += 1
            out.append(np.array(chain))
    return out


def _concentric(geom: BaseGeometry, spacing: float, tip: float, max_rings: int = 5000) -> list[np.ndarray]:
    out = []
    cur = geom
    k = 0
    while not cur.is_empty and k < max_rings:
        out += _rings(cur)
        # núcleo que el último anillo no alcanza a cubrir -> pasada por el eje
        nxt = geom.buffer(-(k + 1) * spacing)
        core = cur.difference(nxt.buffer(spacing)) if not nxt.is_empty else cur
        for poly in _polys(core):
            if not poly.buffer(-tip / 2 * 0.98).is_empty:
                out += _centerlines(poly, tip)
        k += 1
        cur = nxt
    return out


def _centerlines(geom: BaseGeometry, tip: float) -> list[np.ndarray]:
    """Eje central aproximado de regiones delgadas (rasteriza y esqueletiza)."""
    from skimage.draw import polygon as fill_poly
    from skimage.morphology import skeletonize
    from .importers.raster import _skeleton_paths
    from .geometry import simplify

    if geom.is_empty:
        return []
    minx, miny, maxx, maxy = geom.bounds
    res = tip / 6
    W, H = (maxx - minx) / res + 4, (maxy - miny) / res + 4
    if max(W, H) > 3000:
        res *= max(W, H) / 3000
        W, H = (maxx - minx) / res + 4, (maxy - miny) / res + 4
    img = np.zeros((int(H) + 1, int(W) + 1), bool)
    for p in _polys(geom):
        def draw(ring, val):
            c = (np.asarray(ring.coords)[:, 0] - minx) / res + 2
            r = (np.asarray(ring.coords)[:, 1] - miny) / res + 2
            rr, cc = fill_poly(r, c, img.shape)
            img[rr, cc] = val
        draw(p.exterior, True)
        for hole in p.interiors:
            draw(hole, False)
    out = []
    for pth in _skeleton_paths(skeletonize(img), min_px=2):
        pth = simplify(pth, 0.7)
        xy = np.column_stack([(pth[:, 1] - 2) * res + minx, (pth[:, 0] - 2) * res + miny])
        out.append(xy)
    if not out:  # muy pequeño: un punto en el centro
        c = geom.representative_point()
        out.append(np.array([[c.x, c.y]]))
    return out


# --- API -------------------------------------------------------------------

MIN_DENSITY = 0.02


def density_spacing(tip: float, overlap: float, density: float, pattern: str) -> tuple[float, bool]:
    """Separación entre pasadas para cubrir `density` del área. (separación, es_parcial)"""
    solid = tip * (1 - min(max(overlap, 0.0), 0.9))
    d = min(max(density, 0.0), 1.0)
    if d >= 0.999:
        return solid, False
    if pattern == "cross":
        sd = tip / (1 - math.sqrt(1 - d))
    else:
        sd = tip / d
    if sd <= solid * 1.001:
        return solid, False
    return sd, True


def fill_geometry(geom: BaseGeometry, tip: float, overlap: float, fs: FillSettings,
                  density: float = 1.0) -> Result:
    if geom.is_empty or density < MIN_DENSITY:
        return Result([])
    tip = max(tip, 0.01)
    r = tip / 2
    s, partial = density_spacing(tip, overlap, density, fs.pattern)
    # En tonos parciales no se contrae la región: así dos tonos vecinos no
    # dejan una franja blanca entre ellos (la tinta sobresale como máximo ½ punta).
    compensate = fs.compensate and not partial
    inner = geom.buffer(-r) if compensate else geom
    paths: list[np.ndarray] = []
    thin = 0
    lost = 0.0

    # partes que la punta no alcanza (más delgadas que el diámetro)
    if compensate and fs.thin != "skip":
        rest = geom.difference(inner.buffer(r * 1.02)) if not inner.is_empty else geom
        slivers = [p for p in _polys(rest)
                   if p.area > tip * tip * 0.35 and p.minimum_rotated_rectangle.length > 2.5 * tip]
        if slivers:
            thin = len(slivers)
            sg = shapely.union_all(slivers)
            paths += _centerlines(sg, tip) if fs.thin == "centerline" else _rings(sg)
    elif compensate:
        lost = geom.area - inner.buffer(r).area

    if inner.is_empty:
        return Result(paths, thin, lost)

    if fs.pattern == "concentric":
        paths += _concentric(inner, s, tip)
        return Result(paths, thin, lost)

    hatch_region = inner
    if (fs.outline and (not partial or fs.outline_light)) or fs.pattern == "none":
        passes = max(1, int(fs.outline_passes))
        for k in range(passes):
            ring = inner if k == 0 else inner.buffer(-k * s)
            if ring.is_empty:
                break
            paths += _rings(ring)
            hatch_region = ring
        hatch_region = hatch_region.buffer(-s * 0.5)
    if fs.pattern in ("lines", "zigzag", "cross") and not hatch_region.is_empty:
        link = fs.pattern != "lines" and (not partial or fs.link_light)
        paths += _hatch(hatch_region, s, fs.angle, link, tip)
        if fs.pattern == "cross":
            paths += _hatch(hatch_region, s, fs.angle + 90, link, tip)
    return Result(paths, thin, lost)


def item_paths(item: Item, tip: float, overlap: float, fs: FillSettings, ss: StrokeSettings,
               density: float = 1.0) -> Result:
    if density < MIN_DENSITY:
        return Result([])
    if item.kind == "fill":
        return fill_geometry(region(item, fs.fill_rule), tip, overlap, fs, density)

    if ss.mode == "single" or item.width <= tip * (1 + ss.tolerance):
        out = []
        for p, closed in zip(item.paths, item.closed):
            if closed and len(p) > 2 and not np.allclose(p[0], p[-1]):
                p = np.vstack([p, p[:1]])
            out.append(p)
        return Result(out)

    # trazo grueso -> región -> pasadas paralelas
    hw = item.width / 2
    parts = []
    for p, closed in zip(item.paths, item.closed):
        if len(p) == 1:
            parts.append(Point(p[0]).buffer(hw))
        elif len(p) >= 2:
            pts = np.vstack([p, p[:1]]) if closed and not np.allclose(p[0], p[-1]) else p
            parts.append(LineString(pts).buffer(hw, cap_style="round", join_style="round"))
    geom = shapely.union_all(parts) if parts else Polygon()
    sfs = FillSettings(pattern=ss.pattern, angle=fs.angle, outline=True, compensate=True, thin="centerline",
                       outline_light=fs.outline_light, link_light=fs.link_light)
    return fill_geometry(geom, tip, overlap, sfs, density)
