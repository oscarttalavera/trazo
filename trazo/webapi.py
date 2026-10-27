"""Funciones que la interfaz web llama dentro del navegador (Pyodide, en un Web Worker).

Todo entra y sale como JSON. Los perfiles del usuario viven en el navegador
(localStorage) y llegan en cada llamada; nada se guarda en disco.
"""
from __future__ import annotations

import base64
import io
import json
import uuid
import zipfile
from collections import OrderedDict
from dataclasses import asdict
from pathlib import Path

from . import __version__, calibration, gcode, importers, job, pipeline, preview
from . import text as htext
from .importers import raster
from .profiles import FIELD_INFO, KINDS, ProfileStore, from_dict, to_dict

FILES: dict[str, dict] = {}
DOC_CACHE: "OrderedDict[str, object]" = OrderedDict()


class UserError(Exception):
    """Error que se muestra tal cual al usuario."""


def _store(profiles_json: str | None) -> ProfileStore:
    data = json.loads(profiles_json) if profiles_json else {}
    return ProfileStore(data=data or {})


def meta(profiles_json: str = "") -> str:
    st = _store(profiles_json)
    return json.dumps({
        "version": __version__,
        "defaults": job.default_settings(),
        "profiles": {k: [dict(to_dict(p), _builtin=st.is_builtin(k, p.name)) for p in st.all(k)] for k in KINDS},
        "fields": FIELD_INFO,
        "fonts": htext.FONTS,
        "raster_modes": list(raster.MODES),
        "formats": sorted(importers.SUPPORTED),
    })


def normalize_profile(kind: str, data_json: str) -> str:
    """Limpia un perfil editado en la interfaz (tipos y campos válidos)."""
    if kind not in KINDS:
        raise UserError("Tipo de perfil desconocido")
    d = json.loads(data_json)
    if not str(d.get("name", "")).strip():
        raise UserError("El perfil necesita un nombre")
    return json.dumps(asdict(from_dict(KINDS[kind], d)))


def open_path(name: str, path: str) -> str:
    """Registra un archivo que el worker ya escribió en el sistema de archivos virtual."""
    ext = Path(name).suffix.lower()
    if ext not in importers.SUPPORTED:
        raise UserError(f"Formato no soportado: {ext or '(sin extensión)'}. Use SVG, DXF, PNG o JPG.")
    fid = uuid.uuid4().hex[:12]
    FILES[fid] = {"path": path, "name": name, "raster": importers.is_raster(path)}
    return json.dumps({"file_id": fid, "name": name, "raster": FILES[fid]["raster"], "ext": ext})


def _doc(fid: str, imp: dict):
    if fid not in FILES:
        raise UserError("Archivo no encontrado; vuelva a abrirlo.")
    info = FILES[fid]
    opts = dict(imp or {})
    if not info["raster"]:  # las opciones de imagen no afectan a los vectores
        opts = {k: opts[k] for k in ("curve_tol", "text_font", "dxf_closed_as_fill", "dxf_use_lineweight")
                if k in opts}
    key = fid + json.dumps(opts, sort_keys=True)
    if key in DOC_CACHE:
        DOC_CACHE.move_to_end(key)
        return DOC_CACHE[key]
    try:
        doc = importers.load(info["path"], **opts)
    except UserError:
        raise
    except Exception as e:  # noqa: BLE001 - se informa a la interfaz
        raise UserError(f"No se pudo leer el archivo: {e}") from e
    DOC_CACHE[key] = doc
    while len(DOC_CACHE) > 6:
        DOC_CACHE.popitem(last=False)
    return doc


def _run(fid: str, settings_json: str, profiles_json: str):
    settings = json.loads(settings_json)
    imp = settings.pop("import", {})
    doc = _doc(fid, imp)
    title = gcode._slug(Path(FILES[fid]["name"]).stem)[:40] or "dibujo"
    try:
        return job.run(doc, settings, _store(profiles_json), title=title), doc
    except KeyError as e:
        raise UserError(str(e).strip("'\"")) from e


def plan(fid: str, settings_json: str, profiles_json: str = "") -> str:
    out, doc = _run(fid, settings_json, profiles_json)
    res = job.summary(out)
    res["source_bounds"] = doc.bounds()
    res["extent"] = doc.extent
    return json.dumps(res)


def _download(files: list[gcode.GcodeFile], zip_name: str) -> str:
    if not files:
        raise UserError("No hay trazos para generar (¿plumas sin asignar?).")
    if len(files) == 1:
        return json.dumps({"name": files[0].name, "mime": "text/plain",
                           "text": files[0].text.encode("ascii", "replace").decode("ascii")})
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for f in files:
            z.writestr(f.name, f.text.encode("ascii", "replace"))
    return json.dumps({"name": f"{zip_name}.zip", "mime": "application/zip",
                       "b64": base64.b64encode(buf.getvalue()).decode("ascii")})


def make_gcode(fid: str, settings_json: str, profiles_json: str = "") -> str:
    out, _ = _run(fid, settings_json, profiles_json)
    return _download(out.files, gcode._slug(Path(FILES[fid]["name"]).stem)[:40] or "dibujo")


def make_calibration(body_json: str, profiles_json: str = "", download: bool = False) -> str:
    body = json.loads(body_json)
    st = _store(profiles_json)
    try:
        m = st.get("machines", body.get("machine"))
        mat = st.get("materials", body.get("material"))
        pen = st.get("pens", body.get("pen"))
    except KeyError as e:
        raise UserError(str(e).strip("'\"")) from e
    area = pipeline.drawable_area(m, mat)
    pj = calibration.pattern(pen, area)
    files, stats = gcode.generate([pj], m, mat, title=f"calibracion_{gcode._slug(pen.name)}")
    if download:
        return _download(files, "calibracion")
    return json.dumps({
        "jobs": preview.to_json([pj]), "drawable": area, "warnings": [], "groups": [],
        "stats": {"draw_mm": stats.draw_mm, "travel_mm": stats.travel_mm, "lifts": stats.lifts,
                  "seconds": stats.seconds, "time": gcode.format_time(stats.seconds), "per_pen": stats.per_pen},
        "files": [{"name": f.name, "pens": f.pens, "lines": f.text.count("\n"),
                   "time": gcode.format_time(f.seconds)} for f in files],
    })


def call(name: str, *args) -> str:
    """Punto de entrada único del worker: devuelve {"ok": …} o {"error": …}."""
    fn = {"meta": meta, "normalize_profile": normalize_profile, "open_path": open_path, "plan": plan,
          "gcode": make_gcode, "calibration": make_calibration}.get(name)
    if fn is None:
        return json.dumps({"error": f"Función desconocida: {name}"})
    try:
        return '{"ok":' + fn(*args) + "}"  # sin decodificar: los planes pueden pesar varios MB
    except UserError as e:
        return json.dumps({"error": str(e)})
    except Exception as e:  # noqa: BLE001
        return json.dumps({"error": f"Error interno: {type(e).__name__}: {e}"})
