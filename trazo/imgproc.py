"""Procesamiento de imagen mínimo, solo con numpy y Pillow.

Sustituye lo que antes venía de scipy / scikit-image para que el motor pese
poco al cargarse en el navegador (Pyodide).
"""
from __future__ import annotations

from collections import deque

import numpy as np
from PIL import Image, ImageDraw


def otsu(img: np.ndarray, bins: int = 256) -> float:
    """Umbral de Otsu para valores en [0, 1]."""
    hist, edges = np.histogram(img.ravel(), bins=bins, range=(0.0, 1.0))
    hist = hist.astype(float)
    if hist.sum() == 0:
        return 0.5
    centers = (edges[:-1] + edges[1:]) / 2
    w0 = np.cumsum(hist)
    w1 = w0[-1] - w0
    m0 = np.cumsum(hist * centers)
    mu0 = np.divide(m0, w0, out=np.zeros_like(m0), where=w0 > 0)
    mu1 = np.divide(m0[-1] - m0, w1, out=np.zeros_like(m0), where=w1 > 0)
    between = w0 * w1 * (mu0 - mu1) ** 2
    return float(centers[int(np.argmax(between[:-1]))])


def _shift_sum(a: np.ndarray, kernel: np.ndarray, axis: int) -> np.ndarray:
    r = len(kernel) // 2
    pad = [(0, 0), (0, 0)]
    pad[axis] = (r, r)
    p = np.pad(a, pad, mode="edge")
    out = np.zeros_like(a, dtype=float)
    n = a.shape[axis]
    for i, w in enumerate(kernel):
        sl = [slice(None), slice(None)]
        sl[axis] = slice(i, i + n)
        out += w * p[tuple(sl)]
    return out


def gaussian(img: np.ndarray, sigma: float) -> np.ndarray:
    if sigma <= 0:
        return img.astype(float)
    r = max(1, int(np.ceil(3 * sigma)))
    x = np.arange(-r, r + 1)
    k = np.exp(-(x * x) / (2 * sigma * sigma))
    k /= k.sum()
    return _shift_sum(_shift_sum(img.astype(float), k, 0), k, 1)


def median3(a: np.ndarray) -> np.ndarray:
    """Filtro de mediana 3x3."""
    p = np.pad(a, 1, mode="edge")
    h, w = a.shape
    stack = np.stack([p[i:i + h, j:j + w] for i in range(3) for j in range(3)])
    return np.median(stack, axis=0).astype(a.dtype)


def bilinear(img: np.ndarray, rows: np.ndarray, cols: np.ndarray) -> np.ndarray:
    """Muestreo bilineal (bordes: valor más cercano)."""
    h, w = img.shape
    r = np.clip(rows, 0, h - 1)
    c = np.clip(cols, 0, w - 1)
    r0 = np.floor(r).astype(int)
    c0 = np.floor(c).astype(int)
    r1 = np.minimum(r0 + 1, h - 1)
    c1 = np.minimum(c0 + 1, w - 1)
    fr, fc = r - r0, c - c0
    top = img[r0, c0] * (1 - fc) + img[r0, c1] * fc
    bot = img[r1, c0] * (1 - fc) + img[r1, c1] * fc
    return top * (1 - fr) + bot * fr


def _nbrs(p: np.ndarray):
    """Vecinos P2..P9 (sentido horario desde arriba) de una imagen 0/1 con borde."""
    return (p[:-2, 1:-1], p[:-2, 2:], p[1:-1, 2:], p[2:, 2:],
            p[2:, 1:-1], p[2:, :-2], p[1:-1, :-2], p[:-2, :-2])


def skeletonize(mask: np.ndarray) -> np.ndarray:
    """Adelgazamiento de Zhang-Suen: esqueleto de 1 px."""
    im = np.pad(mask.astype(np.uint8), 1)
    while True:
        changed = False
        for step in (0, 1):
            p = np.pad(im[1:-1, 1:-1], 1)
            n = _nbrs(p)
            b = sum(x.astype(np.int16) for x in n)
            seq = list(n) + [n[0]]
            a = sum(((seq[i] == 0) & (seq[i + 1] == 1)).astype(np.int16) for i in range(8))
            p2, _, p4, _, p6, _, p8, _ = n
            if step == 0:
                c = (p2 * p4 * p6 == 0) & (p4 * p6 * p8 == 0)
            else:
                c = (p2 * p4 * p8 == 0) & (p2 * p6 * p8 == 0)
            core = im[1:-1, 1:-1]
            m = (core == 1) & (b >= 2) & (b <= 6) & (a == 1) & c
            if m.any():
                core[m] = 0
                changed = True
        if not changed:
            break
    return im[1:-1, 1:-1].astype(bool)


def canny(gray: np.ndarray, sigma: float = 2.0, low: float = 0.1, high: float = 0.25) -> np.ndarray:
    """Detector de bordes de Canny. low/high son fracciones del gradiente máximo."""
    g = gaussian(gray, sigma)
    p = np.pad(g, 1, mode="edge")
    gx = (p[:-2, 2:] + 2 * p[1:-1, 2:] + p[2:, 2:]) - (p[:-2, :-2] + 2 * p[1:-1, :-2] + p[2:, :-2])
    gy = (p[2:, :-2] + 2 * p[2:, 1:-1] + p[2:, 2:]) - (p[:-2, :-2] + 2 * p[:-2, 1:-1] + p[:-2, 2:])
    mag = np.hypot(gx, gy)
    mmax = mag.max()
    if mmax <= 1e-12:
        return np.zeros_like(gray, dtype=bool)
    ang = (np.rad2deg(np.arctan2(gy, gx)) + 180.0) % 180.0
    q = np.zeros_like(mag, dtype=np.int8)        # 0: horizontal, 1: 45°, 2: vertical, 3: 135°
    q[(ang >= 22.5) & (ang < 67.5)] = 1
    q[(ang >= 67.5) & (ang < 112.5)] = 2
    q[(ang >= 112.5) & (ang < 157.5)] = 3
    m = np.pad(mag, 1)
    c = m[1:-1, 1:-1]
    pairs = [(m[1:-1, 2:], m[1:-1, :-2]), (m[2:, 2:], m[:-2, :-2]),
             (m[2:, 1:-1], m[:-2, 1:-1]), (m[2:, :-2], m[:-2, 2:])]
    nms = np.zeros_like(c, dtype=bool)
    for k, (a, b) in enumerate(pairs):
        sel = q == k
        nms |= sel & (c >= a) & (c >= b)
    weak = nms & (mag >= low * mmax)
    strong = nms & (mag >= high * mmax)
    # histéresis: bordes débiles conectados (8-vecinos) a uno fuerte
    h, w = weak.shape
    out = np.zeros_like(weak)
    todo = deque(zip(*np.nonzero(strong)))
    for r, cc in todo:
        out[r, cc] = True
    while todo:
        r, cc = todo.popleft()
        for dr in (-1, 0, 1):
            for dc in (-1, 0, 1):
                rr, c2 = r + dr, cc + dc
                if 0 <= rr < h and 0 <= c2 < w and weak[rr, c2] and not out[rr, c2]:
                    out[rr, c2] = True
                    todo.append((rr, c2))
    return out


def rasterize(polys, shape: tuple[int, int], to_px) -> np.ndarray:
    """Rasteriza polígonos (con huecos) en una máscara booleana.

    polys: lista de (exterior, [huecos]) como arrays Nx2; to_px convierte a (col, fila).
    """
    h, w = shape
    im = Image.new("1", (w, h), 0)
    dr = ImageDraw.Draw(im)
    for ext, holes in polys:
        dr.polygon([tuple(p) for p in to_px(ext)], fill=1)
        for hole in holes:
            dr.polygon([tuple(p) for p in to_px(hole)], fill=0)
    return np.asarray(im, dtype=bool)
