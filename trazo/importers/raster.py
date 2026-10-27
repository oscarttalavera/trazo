"""Importador de imágenes PNG/JPG.

Modos:
  trace      Logos/line art: vectoriza las regiones (potrace) como rellenos.
             Con colors>1 separa por color (una capa por color -> una pluma).
  centerline Dibujos de línea/manuscritos: esqueleto -> trazos de un pase.
  hatch      Fotos/escala de grises: rayado por niveles de tono (cada nivel
             es una capa, se puede asignar a plumas distintas).
  edges      Bordes (Canny) -> trazos de un pase.
  grays      Escala de grises por niveles: regiones rellenas, una capa por
             tono; con densidad "auto" se dibujan todas con la misma pluma.
"""
from __future__ import annotations

import numpy as np
from PIL import Image, ImageOps

from .. import geometry as g
from .. import imgproc
from .. import tone

MODES = ("trace", "grays", "centerline", "hatch", "edges")


def _load_gray_rgb(path: str, max_px: int):
    im = Image.open(path)
    im = ImageOps.exif_transpose(im)
    dpi = im.info.get("dpi", (0, 0))[0] or 0
    if im.mode in ("RGBA", "LA", "P"):
        im = im.convert("RGBA")
        bg = Image.new("RGBA", im.size, (255, 255, 255, 255))
        im = Image.alpha_composite(bg, im)
    im = im.convert("RGB")
    w0 = im.width
    s = max_px / max(im.size)
    if s < 1:
        im = im.resize((max(1, round(im.width * s)), max(1, round(im.height * s))), Image.LANCZOS)
    return im, dpi, w0


def load(path: str, raster_mode: str = "trace", width_mm: float | None = None,
         threshold: float | None = None, invert: bool = False, colors: int = 1,
         levels: int = 4, hatch_spacing: float = 1.0, hatch_angle: float = 45.0,
         gamma: float = 1.0, edge_sigma: float = 2.0, turdsize: int = 4,
         smooth: float = 1.0, max_px: int = 1600, curve_tol: float = 0.05, **_) -> g.Document:
    im, dpi, w0 = _load_gray_rgb(path, max_px)
    W, H = im.size
    if not width_mm:
        width_mm = w0 * 25.4 / dpi if 30 <= dpi <= 2400 else 100.0
    mmpx = width_mm / W
    gray = np.asarray(im.convert("L"), float) / 255.0
    dark = 1.0 - gray
    if invert:
        dark = 1.0 - dark

    doc = g.Document(source=path, extent=(0.0, 0.0, W * mmpx, H * mmpx))
    to_mm = lambda pts: np.column_stack([pts[:, 0] * mmpx, (H - pts[:, 1]) * mmpx])  # noqa: E731

    if raster_mode == "trace":
        if colors <= 1:
            masks = [(_bw_mask(dark, threshold), "#000000", "negro")]
        else:
            masks = _color_masks(im, colors, invert)
        for mask, color, name in masks:
            paths = _potrace(mask, turdsize, smooth, curve_tol / mmpx)
            paths = [g.close_path(to_mm(p)) for p in paths if len(p) >= 3]
            if paths:
                doc.items.append(g.Item("fill", paths, [True] * len(paths), color, 0.0, name))
    elif raster_mode == "grays":
        # cobertura de tinta que reproduce la luminancia de cada píxel
        lin = np.where(gray <= 0.04045, gray / 12.92, ((gray + 0.055) / 1.055) ** 2.4)
        cov = 1.0 - lin
        if invert:
            cov = 1.0 - cov
        cov = np.clip(cov, 0, 1) ** (1.0 / max(gamma, 0.05))
        n = max(1, int(levels))
        q = imgproc.median3(np.rint(cov * n).astype(np.int16))
        for k in range(n, 0, -1):
            mask = q == k
            if mask.mean() < 0.0005:
                continue
            paths = _potrace(mask, turdsize, smooth, curve_tol / mmpx)
            paths = [g.close_path(to_mm(p)) for p in paths if len(p) >= 3]
            if paths:
                d = k / n
                doc.items.append(g.Item("fill", paths, [True] * len(paths), tone.gray_for_density(d), 0.0,
                                        f"gris {round(d * 100)}%"))
    elif raster_mode == "centerline":
        mask = _bw_mask(dark, threshold)
        for p in _skeleton_paths(imgproc.skeletonize(mask)):
            p = g.simplify(p.astype(float), 0.7)
            doc.items.append(g.Item("stroke", [to_mm(p[:, ::-1])], [False], "#000000", 0.0, "línea"))
    elif raster_mode == "edges":
        e = imgproc.canny(gray, sigma=edge_sigma)
        for p in _skeleton_paths(e):
            p = g.simplify(p.astype(float), 0.7)
            doc.items.append(g.Item("stroke", [to_mm(p[:, ::-1])], [False], "#000000", 0.0, "bordes"))
    elif raster_mode == "hatch":
        d = np.clip(dark, 0, 1) ** (1.0 / max(gamma, 0.05))
        for lvl, paths in enumerate(_tone_hatch(d, mmpx, levels, hatch_spacing, hatch_angle)):
            if paths:
                # gris por nivel: permite asignar plumas distintas a tonos claros/oscuros
                v = int(round(200 * (1 - (lvl + 1) / levels)))
                doc.items.append(g.Item("stroke", paths, [False] * len(paths), "#%02x%02x%02x" % (v, v, v),
                                        0.0, f"tono {lvl + 1}"))
    else:
        raise ValueError(f"Modo de imagen desconocido: {raster_mode}")

    if not doc.items:
        doc.warnings.append("La imagen no produjo trazos: revise umbral / inversión.")
    return doc


# --- Binarización / color -------------------------------------------------

def _bw_mask(dark: np.ndarray, threshold: float | None) -> np.ndarray:
    if threshold is None:
        t = imgproc.otsu(dark)
        t = min(max(t, 0.15), 0.85)
    else:
        t = float(threshold)
    return dark > t


def _color_masks(im: Image.Image, colors: int, invert: bool):
    q = im.quantize(colors=colors + 1, method=Image.Quantize.MEDIANCUT)
    idx = np.asarray(q)
    pal = np.array(q.getpalette()[: 3 * (colors + 1)]).reshape(-1, 3)
    border = np.concatenate([idx[0], idx[-1], idx[:, 0], idx[:, -1]])
    bg = np.bincount(border).argmax()
    out = []
    for i in range(len(pal)):
        if i == bg:
            continue
        mask = idx == i
        if mask.mean() < 0.001:
            continue
        c = "#%02x%02x%02x" % tuple(int(v) for v in pal[i])
        out.append((~mask if invert else mask, c, c))
    return out


def _potrace(mask: np.ndarray, turdsize: int, alphamax: float, tol_px: float) -> list[np.ndarray]:
    import potrace
    # potracer invierte la imagen: True = fondo
    plist = potrace.Bitmap(~mask).trace(turdsize=turdsize, alphamax=alphamax)
    out = []
    for curve in plist:
        cur = curve.start_point
        pts = [(cur.x, cur.y)]
        for seg in curve.segments:
            if seg.is_corner:
                pts.append((seg.c.x, seg.c.y))
                pts.append((seg.end_point.x, seg.end_point.y))
            else:
                p0 = np.array(pts[-1])
                p1 = np.array([seg.c1.x, seg.c1.y])
                p2 = np.array([seg.c2.x, seg.c2.y])
                p3 = np.array([seg.end_point.x, seg.end_point.y])
                L = np.linalg.norm(p1 - p0) + np.linalg.norm(p2 - p1) + np.linalg.norm(p3 - p2)
                n = int(min(200, max(2, np.ceil(np.sqrt(L / max(tol_px, 1e-3)) * 2))))
                t = np.linspace(0, 1, n + 1)[1:, None]
                b = ((1 - t) ** 3) * p0 + 3 * ((1 - t) ** 2) * t * p1 + 3 * (1 - t) * t ** 2 * p2 + t ** 3 * p3
                pts.extend(map(tuple, b))
        out.append(np.array(pts, float))
    return out


# --- Esqueleto -> polilíneas ---------------------------------------------

_NB = [(-1, -1), (-1, 0), (-1, 1), (0, -1), (0, 1), (1, -1), (1, 0), (1, 1)]


def _skeleton_paths(skel: np.ndarray, min_px: int = 3) -> list[np.ndarray]:
    """Recorre un esqueleto de 1 px y devuelve polilíneas (fila, columna)."""
    sk = np.pad(skel.astype(bool), 1)
    pix = set(zip(*np.nonzero(sk)))
    if not pix:
        return []

    def nbrs(p):
        r, c = p
        return [(r + dr, c + dc) for dr, dc in _NB if (r + dr, c + dc) in pix]

    deg = {p: len(nbrs(p)) for p in pix}
    visited: set = set()

    def key(a, b):
        return (a, b) if a < b else (b, a)

    def walk(start, nxt):
        path = [start, nxt]
        visited.add(key(start, nxt))
        prev, cur = start, nxt
        while deg[cur] == 2:
            cand = [q for q in nbrs(cur) if q != prev and key(cur, q) not in visited]
            if not cand:
                break
            prev, cur = cur, cand[0]
            visited.add(key(prev, cur))
            path.append(cur)
        return path

    paths = []
    for p in sorted(pix):
        if deg[p] != 2:
            for q in nbrs(p):
                if key(p, q) not in visited:
                    paths.append(walk(p, q))
    for p in sorted(pix):  # ciclos cerrados
        for q in nbrs(p):
            if key(p, q) not in visited:
                paths.append(walk(p, q))
    out = []
    for pth in paths:
        spur = deg[pth[0]] == 1 or deg[pth[-1]] == 1
        if len(pth) >= 2 and not (spur and len(pth) < min_px):
            out.append(np.array(pth, float) - 1.0)
    return out


# --- Rayado por tonos -----------------------------------------------------

def _tone_hatch(dark: np.ndarray, mmpx: float, levels: int, spacing: float, angle: float):
    H, W = dark.shape
    Wmm, Hmm = W * mmpx, H * mmpx
    angles = [angle, angle + 90, angle + 45, angle - 45, angle + 22.5, angle - 22.5]
    corners = np.array([[0, 0], [Wmm, 0], [0, Hmm], [Wmm, Hmm]])
    step = min(mmpx, spacing / 3)
    result = []
    for lvl in range(levels):
        thr = (lvl + 0.5) / levels
        a = np.radians(angles[lvl % len(angles)])
        d = np.array([np.cos(a), np.sin(a)])
        n = np.array([-d[1], d[0]])
        pn, pd = corners @ n, corners @ d
        offs = np.arange(pn.min() + spacing * (0.5 + lvl / levels), pn.max(), spacing)
        ts = np.arange(pd.min(), pd.max() + step, step)
        paths = []
        for j, o in enumerate(offs):
            pts = o * n + ts[:, None] * d
            inside = (pts[:, 0] >= 0) & (pts[:, 0] <= Wmm) & (pts[:, 1] >= 0) & (pts[:, 1] <= Hmm)
            if not inside.any():
                continue
            col = pts[:, 0] / mmpx - 0.5
            row = (Hmm - pts[:, 1]) / mmpx - 0.5
            v = imgproc.bilinear(dark, row, col)
            on = inside & (v > thr)
            if not on.any():
                continue
            edges = np.diff(np.concatenate([[0], on.astype(np.int8), [0]]))
            starts, ends = np.nonzero(edges == 1)[0], np.nonzero(edges == -1)[0] - 1
            segs = [pts[[s, e]] for s, e in zip(starts, ends) if e > s]
            if j % 2:  # zigzag para facilitar el enlace
                segs = [s[::-1] for s in segs[::-1]]
            paths += segs
        result.append(paths)
    return result
