"""Línea de comandos.

  trazo dibujo.svg -o dibujo.gcode --pen "Fineliner 0.5" --fit
  trazo logo.png --raster-mode trace --image-width 80 --pattern zigzag
  trazo calibrate --pen "Sharpie fino"
  trazo profiles
  trazo serve            (interfaz web local)
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from . import __version__, calibration, gcode, job, pipeline, preview
from .profiles import ProfileStore

COMMANDS = {"gcode", "serve", "calibrate", "profiles"}


def _common(p: argparse.ArgumentParser):
    p.add_argument("--machine", help="perfil de máquina")
    p.add_argument("--material", help="perfil de material")
    p.add_argument("--pen", help="pluma por defecto")
    p.add_argument("-o", "--output", help="archivo .gcode de salida (o carpeta con --per-pen)")


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="trazo", description="G-code para plotter de pluma en impresoras 3D")
    ap.add_argument("--version", action="version", version=f"trazo {__version__}")
    sub = ap.add_subparsers(dest="cmd")

    g = sub.add_parser("gcode", help="convertir SVG/DXF/PNG/JPG a G-code")
    g.add_argument("input")
    _common(g)
    g.add_argument("--config", help="JSON con ajustes (mismo formato que la interfaz web)")
    g.add_argument("--map", action="append", default=[], metavar="CLAVE=PLUMA",
                   help="asigna un color/capa a una pluma; PLUMA vacía = omitir")
    g.add_argument("--group-by", choices=["color", "layer"])
    sc = g.add_mutually_exclusive_group()
    sc.add_argument("--fit", action="store_true", help="ajustar al área de dibujo")
    sc.add_argument("--scale", type=float)
    sc.add_argument("--width", type=float, help="ancho final en mm")
    sc.add_argument("--height", type=float, help="alto final en mm")
    g.add_argument("--rotate", type=float)
    g.add_argument("--mirror-x", action="store_true")
    g.add_argument("--mirror-y", action="store_true")
    g.add_argument("--align", choices=["center", "bl", "br", "tl", "tr", "origin"])
    g.add_argument("--offset", type=float, nargs=2, metavar=("X", "Y"))
    g.add_argument("--pattern", choices=["lines", "zigzag", "cross", "concentric", "none"])
    g.add_argument("--angle", type=float)
    g.add_argument("--no-outline", action="store_true")
    g.add_argument("--single-stroke", action="store_true", help="ignora el ancho de trazo del diseño")
    g.add_argument("--no-clip", action="store_true")
    g.add_argument("--per-pen", action="store_true", help="un archivo por pluma")
    g.add_argument("--preview", help="guardar vista previa SVG")
    r = g.add_argument_group("imágenes")
    r.add_argument("--raster-mode", choices=["trace", "centerline", "hatch", "edges"])
    r.add_argument("--image-width", type=float, help="ancho de la imagen en mm")
    r.add_argument("--threshold", type=float, help="umbral 0-1 (por defecto Otsu)")
    r.add_argument("--invert", action="store_true")
    r.add_argument("--colors", type=int, help="colores a separar en modo trace")
    r.add_argument("--levels", type=int, help="niveles de tono en modo hatch")
    r.add_argument("--hatch-spacing", type=float)

    c = sub.add_parser("calibrate", help="patrón de calibración para una pluma")
    _common(c)

    sub.add_parser("profiles", help="listar perfiles")

    s = sub.add_parser("serve", help="interfaz web local")
    s.add_argument("--port", type=int, default=8765)
    s.add_argument("--host", default="127.0.0.1")
    s.add_argument("--no-browser", action="store_true")
    return ap


def _config_from_args(a) -> dict:
    d = job.default_settings()
    if a.config:
        user = json.loads(Path(a.config).read_text(encoding="utf-8"))
        for k, v in user.items():
            if isinstance(v, dict) and isinstance(d.get(k), dict):
                d[k].update(v)
            else:
                d[k] = v
    for k in ("machine", "material"):
        if getattr(a, k):
            d[k] = getattr(a, k)
    if a.pen:
        d["default_pen"] = a.pen
    if a.map:
        pm = d.setdefault("pen_map", {})
        for m in a.map:
            key, _, pen = m.partition("=")
            pm[key] = pen
    if a.group_by:
        d["group_by"] = a.group_by
    L = d["layout"]
    if a.fit:
        L["scale_mode"] = "fit"
    elif a.scale:
        L.update(scale_mode="factor", scale=a.scale)
    elif a.width:
        L.update(scale_mode="width", target=a.width)
    elif a.height:
        L.update(scale_mode="height", target=a.height)
    if a.rotate is not None:
        L["rotate"] = a.rotate
    L["mirror_x"] = L.get("mirror_x") or a.mirror_x
    L["mirror_y"] = L.get("mirror_y") or a.mirror_y
    if a.align:
        L["align"] = a.align
    if a.offset:
        L["offset_x"], L["offset_y"] = a.offset
    if a.pattern:
        d["fill"]["pattern"] = a.pattern
    if a.angle is not None:
        d["fill"]["angle"] = a.angle
    if a.no_outline:
        d["fill"]["outline"] = False
    if a.single_stroke:
        d["stroke"]["mode"] = "single"
    if a.no_clip:
        d["clip"] = False
    if a.per_pen:
        d["per_pen"] = True
    imp = d["import"]
    for k, attr in (("raster_mode", "raster_mode"), ("width_mm", "image_width"), ("threshold", "threshold"),
                    ("colors", "colors"), ("levels", "levels"), ("hatch_spacing", "hatch_spacing")):
        v = getattr(a, attr)
        if v is not None:
            imp[k] = v
    if a.invert:
        imp["invert"] = True
    return d


def _write(files, output: str | None, input_path: Path, per_pen: bool = False):
    if not files:
        print("No se generó G-code (¿no hay trazos o plumas asignadas?)", file=sys.stderr)
        return 1
    if len(files) == 1 and not per_pen:
        out = Path(output) if output else input_path.with_suffix(".gcode")
        out.write_text(files[0].text, encoding="ascii", errors="replace")
        print(f"  -> {out}  ({files[0].text.count(chr(10))} líneas, {gcode.format_time(files[0].seconds)})")
    else:
        folder = Path(output) if output else input_path.parent
        folder.mkdir(parents=True, exist_ok=True)
        for f in files:
            (folder / f.name).write_text(f.text, encoding="ascii", errors="replace")
            print(f"  -> {folder / f.name}  ({', '.join(f.pens)}, {gcode.format_time(f.seconds)})")
    return 0


def cmd_gcode(a) -> int:
    store = ProfileStore()
    d = _config_from_args(a)
    src = Path(a.input)
    imp = d.pop("import")
    doc = job.import_file(src, imp)
    out = job.run(doc, d, store, title=src.stem)
    for gr in out.plan.groups:
        pen = d.get("pen_map", {}).get(gr.key, d.get("default_pen") or "(por defecto)")
        print(f"  grupo {gr.key}: {gr.items} elementos -> {pen or '(omitido)'}")
    for w in out.plan.warnings:
        print(f"  aviso: {w}")
    st = out.stats
    print(f"  dibujo {st.draw_mm / 1000:.2f} m, viaje {st.travel_mm / 1000:.2f} m, "
          f"{st.lifts} levantadas, ~{gcode.format_time(st.seconds)}")
    if a.preview:
        m = store.get("machines", d.get("machine"))
        mat = store.get("materials", d.get("material"))
        Path(a.preview).write_text(preview.svg(out.plan.jobs, m, mat, out.plan.drawable), encoding="utf-8")
        print(f"  vista previa -> {a.preview}")
    output = a.output
    per_pen = bool(d.get("per_pen"))
    if output and per_pen and output.endswith(".gcode"):
        output = str(Path(output).parent)
    return _write(out.files, output, src, per_pen)


def cmd_calibrate(a) -> int:
    store = ProfileStore()
    m = store.get("machines", a.machine)
    mat = store.get("materials", a.material)
    pen = store.get("pens", a.pen)
    area = pipeline.drawable_area(m, mat)
    pj = calibration.pattern(pen, area)
    files, _ = gcode.generate([pj], m, mat, title="calibracion")
    return _write(files, a.output or "calibracion.gcode", Path("calibracion.gcode"))


def cmd_profiles(_a) -> int:
    store = ProfileStore()
    print(f"Perfiles de usuario: {store.path}")
    for kind, label in (("machines", "Máquinas"), ("pens", "Plumas"), ("materials", "Materiales")):
        print(f"\n{label}:")
        for p in store.all(kind):
            extra = {"machines": lambda p: f"{p.x_max:g}x{p.y_max:g} {p.flavor}",
                     "pens": lambda p: f"punta {p.tip:g} mm, {p.draw_feed:g} mm/min",
                     "materials": lambda p: f"{p.width:g}x{p.height:g} mm, {p.thickness:g} mm"}[kind](p)
            print(f"  - {p.name}  ({extra})")
    return 0


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv:
        argv = ["serve"]
    elif argv[0] not in COMMANDS and not argv[0].startswith("-"):
        argv.insert(0, "gcode")
    a = build_parser().parse_args(argv)
    if a.cmd == "serve":
        from .server import serve
        serve(a.host, a.port, open_browser=not a.no_browser)
        return 0
    return {"gcode": cmd_gcode, "calibrate": cmd_calibrate, "profiles": cmd_profiles}[a.cmd](a)


if __name__ == "__main__":
    raise SystemExit(main())
