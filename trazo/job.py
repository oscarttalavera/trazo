"""Capa de servicio compartida por la CLI y la interfaz web."""
from __future__ import annotations

from dataclasses import asdict, dataclass, fields
from pathlib import Path

from . import fill as F
from . import gcode, importers, pipeline, preview
from . import optimize as opt
from .geometry import Document
from .profiles import ProfileStore


def _apply(obj, d: dict | None):
    if not d:
        return obj
    names = {f.name: f for f in fields(obj)}
    for k, v in d.items():
        if k in names:
            setattr(obj, k, v)
    return obj


def settings_from_dict(d: dict) -> pipeline.Settings:
    s = pipeline.Settings()
    _apply(s.layout, d.get("layout"))
    _apply(s.fill, d.get("fill"))
    _apply(s.stroke, d.get("stroke"))
    for k in ("group_by", "pen_map", "default_pen", "group_order", "density_map", "density_gamma",
              "simplify_tol", "merge_tol", "min_len", "reorder", "clip"):
        if k in d and (d[k] is not None or k == "merge_tol"):
            setattr(s, k, d[k])
    return s


def default_settings() -> dict:
    s = pipeline.Settings()
    return {
        "layout": asdict(s.layout), "fill": asdict(s.fill), "stroke": asdict(s.stroke),
        "group_by": s.group_by, "simplify_tol": s.simplify_tol, "merge_tol": s.merge_tol,
        "min_len": s.min_len, "reorder": s.reorder, "clip": s.clip, "per_pen": False,
        "density_gamma": s.density_gamma,
        "import": {"curve_tol": 0.05, "text_font": "futural", "raster_mode": "trace",
                   "width_mm": None, "threshold": None, "invert": False, "colors": 1,
                   "levels": 4, "hatch_spacing": 1.0, "hatch_angle": 45.0, "gamma": 1.0,
                   "edge_sigma": 2.0, "turdsize": 4, "smooth": 1.0,
                   "dxf_closed_as_fill": False, "dxf_use_lineweight": False},
        "patterns": list(F.PATTERNS),
    }


@dataclass
class Output:
    plan: pipeline.Plan
    files: list[gcode.GcodeFile]
    stats: gcode.Stats


def import_file(path: str | Path, options: dict | None = None) -> Document:
    return importers.load(str(path), **(options or {}))


DRAFT_SIMPLIFY = 0.1  # mm: trazos más toscos y ligeros en el borrador


def _draft_stats(pl: pipeline.Plan, machine, material) -> gcode.Stats:
    """Estimación rápida (sin generar el texto del G-code) para la vista borrador."""
    st = gcode.Stats()
    pos = (machine.park_x + machine.pen_offset_x, machine.park_y + machine.pen_offset_y)
    for j in pl.jobs:
        draw, travel, lifts = opt.travel_stats(j.paths, pos)
        sec = draw / (j.pen.draw_feed * material.speed_factor) * 60 + travel / machine.travel_feed * 60
        st.draw_mm += draw
        st.travel_mm += travel
        st.lifts += lifts
        st.seconds += sec
        st.per_pen.append({"pen": j.pen.name, "seconds": sec})
        if j.paths:
            pos = tuple(j.paths[-1][-1])
    return st


def run(doc: Document, d: dict, store: ProfileStore, title: str = "dibujo", draft: bool = False) -> Output:
    machine = store.get("machines", d.get("machine"))
    material = store.get("materials", d.get("material"))
    pens = {p.name: p for p in store.all("pens")}
    s = settings_from_dict(d)
    if draft:  # sin reordenar ni generar G-code: lo justo para ver el resultado
        s.reorder = False
        s.simplify_tol = max(s.simplify_tol, DRAFT_SIMPLIFY)
    pl = pipeline.plan(doc, machine, material, pens, s)
    if draft:
        return Output(pl, [], _draft_stats(pl, machine, material))
    files, stats = gcode.generate(pl.jobs, machine, material, title, per_pen=bool(d.get("per_pen")))
    if stats.out_of_bounds:
        pl.warnings.append(f"{stats.out_of_bounds} punto(s) fuera del recorrido de la máquina "
                           "(revise el offset de la pluma).")
    return Output(pl, files, stats)


def summary(out: Output) -> dict:
    st = out.stats
    return {
        "warnings": out.plan.warnings,
        "groups": [asdict(gr) for gr in out.plan.groups],
        "drawable": out.plan.drawable,
        "design_bounds": out.plan.design_bounds,
        "scale": out.plan.scale,
        "matrix": out.plan.matrix,
        "stats": {"draw_mm": st.draw_mm, "travel_mm": st.travel_mm, "lifts": st.lifts,
                  "seconds": st.seconds, "time": gcode.format_time(st.seconds),
                  "per_pen": st.per_pen},
        "files": [{"name": f.name, "pens": f.pens, "lines": f.text.count("\n"),
                   "time": gcode.format_time(f.seconds)} for f in out.files],
        "jobs": preview.to_json(out.plan.jobs),
    }
