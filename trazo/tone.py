"""Tonos de gris -> densidad de tinta.

La densidad es la fracción del área que cubre la tinta. Para que un gris
de pantalla se vea igual en papel, se usa la luminancia lineal (sRGB):
cubrir d del papel con tinta negra refleja (1 - d) de la luz.
"""
from __future__ import annotations


def _lin(c: float) -> float:
    c /= 255.0
    return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4


def _enc(v: float) -> int:
    v = min(max(v, 0.0), 1.0)
    c = v * 12.92 if v <= 0.0031308 else 1.055 * v ** (1 / 2.4) - 0.055
    return int(round(c * 255))


def rgb(hexcolor: str) -> tuple[int, int, int]:
    h = (hexcolor or "#000000").lstrip("#")
    if len(h) == 3:
        h = "".join(ch * 2 for ch in h)
    try:
        return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
    except ValueError:
        return 0, 0, 0


def is_neutral(hexcolor: str, tol: int = 18) -> bool:
    """Negro, grises y blanco (sin croma apreciable)."""
    c = rgb(hexcolor)
    return max(c) - min(c) <= tol


def tone_density(hexcolor: str, gamma: float = 1.0) -> float:
    r, g, b = (_lin(v) for v in rgb(hexcolor))
    y = 0.2126 * r + 0.7152 * g + 0.0722 * b
    d = min(max(1.0 - y, 0.0), 1.0)
    return d ** max(gamma, 0.05)


def gray_for_density(d: float) -> str:
    v = _enc(1.0 - d)
    return "#%02x%02x%02x" % (v, v, v)


def resolve(spec, color: str, gamma: float = 1.0) -> float:
    """spec: None (automático solo para grises), 'auto', o un número 0-1."""
    if spec is None or spec == "":
        return tone_density(color, gamma) if is_neutral(color) else 1.0
    if spec == "auto":
        return tone_density(color, gamma)
    try:
        v = float(spec)
    except (TypeError, ValueError):
        return 1.0
    return min(max(v / 100.0 if v > 1.0 else v, 0.0), 1.0)
