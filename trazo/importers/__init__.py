"""Selección de importador por extensión."""
from __future__ import annotations

from pathlib import Path

from ..geometry import Document

VECTOR = {".svg", ".dxf"}
RASTER = {".png", ".jpg", ".jpeg", ".bmp", ".gif", ".webp", ".tif", ".tiff"}
SUPPORTED = VECTOR | RASTER


def is_raster(path: str) -> bool:
    return Path(path).suffix.lower() in RASTER


def load(path: str, **options) -> Document:
    ext = Path(path).suffix.lower()
    if ext == ".svg":
        from . import svg
        return svg.load(path, **options)
    if ext == ".dxf":
        from . import dxf
        return dxf.load(path, **options)
    if ext in RASTER:
        from . import raster
        return raster.load(path, **options)
    raise ValueError(f"Formato no soportado: {ext} (use SVG, DXF, PNG o JPG)")
