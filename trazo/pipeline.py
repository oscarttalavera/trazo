"""Del documento importado a trabajos por pluma listos para G-code."""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import shapely
from shapely.geometry import LineString

from . import fill as F
from . import geometry as g
from . import optimize as opt
from . import tone
from .gcode import PenJob
from .profiles import MachineProfile, MaterialProfile, PenProfile


@dataclass
class Layout:
    scale_mode: str = "real"   # real | fit | factor | width | height
    scale: float = 1.0         # para factor
    target: float = 100.0      # mm para width/height
    rotate: float = 0.0
    mirror_x: bool = False
    mirror_y: bool = False
    align: str = "center"      # center | tl tc tr cl cr bl bc br | origin
    offset_x: float = 0.0
    offset_y: float = 0.0


@dataclass
class Settings:
    layout: Layout = field(default_factory=Layout)
    fill: F.FillSettings = field(default_factory=F.FillSettings)
    stroke: F.StrokeSettings = field(default_factory=F.StrokeSettings)
    group_by: str = "color"            # color | layer
    pen_map: dict = field(default_factory=dict)   # clave de grupo -> nombre de pluma ("" = omitir)
    default_pen: str | None = None
    group_order: list = field(default_factory=list)  # orden de dibujo de los grupos
    # densidad por grupo: número 0-1 (o %), "auto" (según el tono) o ausente
    # (automático solo para negro/grises; los colores van sólidos)
    density_map: dict = field(default_factory=dict)
    density_gamma: float = 1.0         # curva de tonos para "auto" (>1 aclara)
    simplify_tol: float = 0.02
    merge_tol: float | None = None     # None = medio diámetro de la punta
    min_len: float = 0.0
    reorder: bool = True
    clip: bool = True


@dataclass
class Group:
    key: str
    color: str
    items: int
    kinds: dict
    density: float = 1.0               # densidad efectiva del grupo
    tone: float = 1.0                  # densidad que daría "auto"


@dataclass
class Plan:
    jobs: list[PenJob]
    groups: list[Group]
    warnings: list[str]
    drawable: tuple[float, float, float, float]
    design_bounds: tuple[float, float, float, float] | None
    scale: float
    matrix: list | None = None         # documento -> cama (3x3)


def drawable_area(m: MachineProfile, mat: MaterialProfile) -> tuple[float, float, float, float]:
    """Rectángulo (cama) donde la pluma puede dibujar: material - margen ∩ alcance."""
    x0 = max(mat.origin_x + mat.margin, m.x_min + m.pen_offset_x)
    y0 = max(mat.origin_y + mat.margin, m.y_min + m.pen_offset_y)
    x1 = min(mat.origin_x + mat.width - mat.margin, m.x_max + m.pen_offset_x)
    y1 = min(mat.origin_y + mat.height - mat.margin, m.y_max + m.pen_offset_y)
    return x0, y0, max(x0, x1), max(y0, y1)


def group_key(item: g.Item, by: str) -> str:
    return item.layer if by == "layer" else item.color


def groups(doc: g.Document, by: str) -> list[Group]:
    out: dict[str, Group] = {}
    for it in doc.items:
        k = group_key(it, by)
        if k not in out:
            out[k] = Group(k, it.color, 0, {"stroke": 0, "fill": 0})
        out[k].items += 1
        out[k].kinds[it.kind] += 1
    return list(out.values())


def layout_matrix(doc: g.Document, L: Layout, area) -> tuple[np.ndarray, float]:
    b = doc.bounds()
    if b is None:
        return g.identity(), 1.0
    cx, cy = (b[0] + b[2]) / 2, (b[1] + b[3]) / 2
    m = g.translate(-cx, -cy)
    m = g.scale(-1 if L.mirror_x else 1, -1 if L.mirror_y else 1) @ m
    m = g.rotate(L.rotate) @ m
    # caja tras rotar
    corners = np.vstack([g.apply(m, p) for it in doc.items for p in it.paths if len(p)])
    # medio ancho de trazo: los trazos gruesos sobresalen de su eje
    pad = max((it.width / 2 for it in doc.items if it.kind == "stroke"), default=0.0)
    bw = max(corners[:, 0].max() - corners[:, 0].min() + 2 * pad, 1e-9)
    bh = max(corners[:, 1].max() - corners[:, 1].min() + 2 * pad, 1e-9)
    aw, ah = area[2] - area[0], area[3] - area[1]
    s = {"real": 1.0, "factor": L.scale, "width": L.target / bw, "height": L.target / bh,
         "fit": min(aw / bw, ah / bh) if aw > 0 and ah > 0 else 1.0}.get(L.scale_mode, 1.0)
    m = g.scale(s) @ m
    minx, miny = (corners[:, 0].min() - pad) * s, (corners[:, 1].min() - pad) * s
    maxx, maxy = (corners[:, 0].max() + pad) * s, (corners[:, 1].max() + pad) * s
    if L.align == "origin" and not (L.mirror_x or L.mirror_y or L.rotate):
        # el (0,0) del documento cae en la esquina inferior izquierda del área
        return g.translate(area[0] + pad * s + L.offset_x, area[1] + pad * s + L.offset_y) @ g.scale(s), s
    # código de 2 letras: vertical (t/c/b) + horizontal (l/c/r); "center" = cc
    code = "cc" if L.align in ("center", "origin") or len(L.align) != 2 else L.align
    tx = {"l": area[0] - minx, "r": area[2] - maxx}.get(code[1], (area[0] + area[2]) / 2 - (minx + maxx) / 2)
    ty = {"b": area[1] - miny, "t": area[3] - maxy}.get(code[0], (area[1] + area[3]) / 2 - (miny + maxy) / 2)
    return g.translate(tx + L.offset_x, ty + L.offset_y) @ m, s


def _clip(paths: list[np.ndarray], rect) -> tuple[list[np.ndarray], int]:
    x0, y0, x1, y1 = rect
    out, clipped = [], 0
    eps = 1e-6
    for p in paths:
        inside = ((p[:, 0] >= x0 - eps) & (p[:, 0] <= x1 + eps) &
                  (p[:, 1] >= y0 - eps) & (p[:, 1] <= y1 + eps))
        if inside.all():
            out.append(p)
            continue
        clipped += 1
        if len(p) < 2:
            continue
        res = shapely.clip_by_rect(LineString(p), x0, y0, x1, y1)
        out += [s for s in F._lines(res) if len(s) >= 2]
    return out, clipped


def plan(doc: g.Document, machine: MachineProfile, material: MaterialProfile,
         pens: dict[str, PenProfile], settings: Settings) -> Plan:
    warnings = list(doc.warnings)
    area = drawable_area(machine, material)
    if area[2] - area[0] <= 0 or area[3] - area[1] <= 0:
        warnings.append("El área de dibujo es nula: revise offset de pluma, posición y margen del material.")
    mtx, s = layout_matrix(doc, settings.layout, area)
    placed = doc.transformed(mtx)
    grp = groups(doc, settings.group_by)
    if settings.group_order:
        rank = {k: i for i, k in enumerate(settings.group_order)}
        grp.sort(key=lambda gr: rank.get(gr.key, len(rank)))
    default_pen = settings.default_pen or next(iter(pens), None)
    for gr in grp:
        gr.tone = tone.tone_density(gr.color, settings.density_gamma)
        gr.density = tone.resolve(settings.density_map.get(gr.key), gr.color, settings.density_gamma)

    # agrupa por pluma, en el orden de los grupos
    by_pen: dict[str, list[g.Item]] = {}
    labels: dict[str, list[str]] = {}
    for gr in grp:
        pen_name = settings.pen_map.get(gr.key, default_pen)
        if not pen_name or pen_name not in pens:
            continue
        by_pen.setdefault(pen_name, [])
        labels.setdefault(pen_name, []).append(gr.key)
    for it in placed.items:
        pen_name = settings.pen_map.get(group_key(it, settings.group_by), default_pen)
        if pen_name in by_pen:
            by_pen[pen_name].append(it)

    jobs: list[PenJob] = []
    thin_total = clipped_total = 0
    start = np.array([machine.park_x + machine.pen_offset_x, machine.park_y + machine.pen_offset_y])
    for pen_name, items in by_pen.items():
        pen = pens[pen_name]
        paths: list[np.ndarray] = []
        for it in items:
            spec = settings.density_map.get(group_key(it, settings.group_by))
            d = tone.resolve(spec, it.color, settings.density_gamma)
            r = F.item_paths(it, pen.tip, pen.overlap, settings.fill, settings.stroke, d)
            paths += r.paths
            thin_total += r.thin_features
        if settings.clip:
            paths, c = _clip(paths, area)
            clipped_total += c
        paths = opt.prepare(paths, settings.simplify_tol, settings.min_len)
        merge = settings.merge_tol if settings.merge_tol is not None else pen.tip * 0.5
        if settings.reorder:
            paths = opt.order(paths, start, merge)
        else:
            paths = opt.join_close(paths, merge)
        if paths:
            start = paths[-1][-1]
            jobs.append(PenJob(pen, paths, ", ".join(labels[pen_name])))

    if thin_total:
        warnings.append(f"{thin_total} detalle(s) más delgados que la punta se dibujaron por su eje central.")
    if clipped_total:
        warnings.append(f"{clipped_total} trazo(s) recortados por salirse del área de dibujo.")
    b = placed.bounds()
    if b and (b[0] < area[0] - 0.01 or b[1] < area[1] - 0.01 or b[2] > area[2] + 0.01 or b[3] > area[3] + 0.01):
        if not settings.clip:
            warnings.append("El diseño se sale del área de dibujo.")
    return Plan(jobs, grp, warnings, area, b, s, mtx.tolist())
