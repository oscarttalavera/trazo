"""Modelo geométrico común a todos los importadores.

Convención: todas las coordenadas están en milímetros con el eje Y hacia
arriba (igual que la cama de la impresora vista desde arriba, con el frente
abajo). Los importadores se encargan de convertir unidades y voltear Y.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Literal

import numpy as np

Kind = Literal["stroke", "fill"]


@dataclass
class Item:
    """Un elemento dibujable.

    - kind="stroke": cada polilínea se dibuja siguiendo su eje; `width` es el
      ancho de trazo del diseño (0 = línea fina, una sola pasada).
    - kind="fill": las polilíneas cerradas definen una región a rellenar.
    """

    kind: Kind
    paths: list[np.ndarray]
    closed: list[bool]
    color: str = "#000000"
    width: float = 0.0
    layer: str = "0"

    def transformed(self, m: np.ndarray, width_scale: float = 1.0) -> "Item":
        return Item(
            kind=self.kind,
            paths=[apply(m, p) for p in self.paths],
            closed=list(self.closed),
            color=self.color,
            width=self.width * width_scale,
            layer=self.layer,
        )


@dataclass
class Document:
    items: list[Item] = field(default_factory=list)
    source: str = ""
    warnings: list[str] = field(default_factory=list)

    def bounds(self) -> tuple[float, float, float, float] | None:
        pts = [p for it in self.items for p in it.paths if len(p)]
        if not pts:
            return None
        allp = np.vstack(pts)
        return (float(allp[:, 0].min()), float(allp[:, 1].min()),
                float(allp[:, 0].max()), float(allp[:, 1].max()))

    def transformed(self, m: np.ndarray) -> "Document":
        s = math.sqrt(abs(np.linalg.det(m[:2, :2])))
        return Document([it.transformed(m, s) for it in self.items], self.source, list(self.warnings))


# --- Matrices afines 3x3 -----------------------------------------------------

def identity() -> np.ndarray:
    return np.eye(3)


def translate(dx: float, dy: float) -> np.ndarray:
    m = np.eye(3)
    m[0, 2], m[1, 2] = dx, dy
    return m


def scale(sx: float, sy: float | None = None) -> np.ndarray:
    return np.diag([sx, sx if sy is None else sy, 1.0])


def rotate(deg: float) -> np.ndarray:
    a = math.radians(deg)
    c, s = math.cos(a), math.sin(a)
    return np.array([[c, -s, 0], [s, c, 0], [0, 0, 1.0]])


def apply(m: np.ndarray, pts: np.ndarray) -> np.ndarray:
    if len(pts) == 0:
        return pts
    return pts @ m[:2, :2].T + m[:2, 2]


# --- Utilidades de polilíneas ---------------------------------------------

def path_length(p: np.ndarray) -> float:
    if len(p) < 2:
        return 0.0
    return float(np.hypot(*np.diff(p, axis=0).T).sum())


def dedupe(p: np.ndarray, eps: float = 1e-6) -> np.ndarray:
    """Elimina vértices consecutivos repetidos."""
    if len(p) < 2:
        return p
    keep = np.ones(len(p), bool)
    keep[1:] = np.hypot(*np.diff(p, axis=0).T) > eps
    return p[keep]


def simplify(p: np.ndarray, tol: float) -> np.ndarray:
    """Douglas-Peucker iterativo (sin recursión, para polilíneas largas)."""
    n = len(p)
    if n < 3 or tol <= 0:
        return p
    keep = np.zeros(n, bool)
    keep[0] = keep[-1] = True
    stack = [(0, n - 1)]
    while stack:
        i, j = stack.pop()
        if j <= i + 1:
            continue
        a, b = p[i], p[j]
        seg = b - a
        L = math.hypot(*seg)
        pts = p[i + 1:j]
        if L < 1e-12:
            d = np.hypot(*(pts - a).T)
        else:
            d = np.abs(seg[0] * (pts[:, 1] - a[1]) - seg[1] * (pts[:, 0] - a[0])) / L
        k = int(np.argmax(d))
        if d[k] > tol:
            k += i + 1
            keep[k] = True
            stack.append((i, k))
            stack.append((k, j))
    return p[keep]


def close_path(p: np.ndarray) -> np.ndarray:
    if len(p) and not np.allclose(p[0], p[-1]):
        return np.vstack([p, p[:1]])
    return p


def normalize_color(c: str | None) -> str:
    if not c:
        return "#000000"
    c = c.strip().lower()
    if c.startswith("#") and len(c) == 4:
        c = "#" + "".join(ch * 2 for ch in c[1:])
    return c[:7]
