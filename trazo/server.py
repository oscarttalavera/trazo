"""Servidor local (FastAPI) para la interfaz web."""
from __future__ import annotations

import io
import json
import shutil
import sys
import tempfile
import threading
import uuid
import webbrowser
import zipfile
from collections import OrderedDict
from pathlib import Path

from fastapi import Body, FastAPI, File, HTTPException, UploadFile
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles

from . import __version__, calibration, gcode, importers, job, pipeline, preview
from . import text as htext
from .importers import raster
from .profiles import FIELD_INFO, KINDS, ProfileStore, to_dict


def _web_dir() -> Path:
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).parent.parent))  # PyInstaller
    for cand in (base / "trazo" / "web", Path(__file__).parent / "web"):
        if cand.exists():
            return cand
    raise RuntimeError("No se encontró la carpeta web")


WEB = _web_dir()
UPLOADS = Path(tempfile.mkdtemp(prefix="trazo_"))
FILES: dict[str, dict] = {}
DOC_CACHE: "OrderedDict[str, object]" = OrderedDict()
LOCK = threading.Lock()

app = FastAPI(title="Trazo", version=__version__)
app.mount("/static", StaticFiles(directory=WEB), name="static")


def store() -> ProfileStore:
    return ProfileStore()


@app.get("/")
def index():
    return FileResponse(WEB / "index.html")


@app.get("/api/meta")
def meta():
    st = store()
    return {
        "version": __version__,
        "defaults": job.default_settings(),
        "profiles": {k: [dict(to_dict(p), _builtin=st.is_builtin(k, p.name)) for p in st.all(k)]
                     for k in KINDS},
        "fields": FIELD_INFO,
        "fonts": htext.FONTS,
        "raster_modes": list(raster.MODES),
        "profiles_path": str(st.path),
        "formats": sorted(importers.SUPPORTED),
    }


@app.post("/api/upload")
async def upload(file: UploadFile = File(...)):
    ext = Path(file.filename or "").suffix.lower()
    if ext not in importers.SUPPORTED:
        raise HTTPException(400, f"Formato no soportado: {ext or '(sin extensión)'}")
    fid = uuid.uuid4().hex[:12]
    dest = UPLOADS / f"{fid}{ext}"
    with dest.open("wb") as fh:
        shutil.copyfileobj(file.file, fh)
    FILES[fid] = {"path": str(dest), "name": file.filename, "raster": importers.is_raster(str(dest))}
    return {"file_id": fid, "name": file.filename, "raster": FILES[fid]["raster"]}


def _doc(fid: str, imp: dict):
    if fid not in FILES:
        raise HTTPException(404, "Archivo no encontrado; vuelva a abrirlo.")
    info = FILES[fid]
    opts = dict(imp or {})
    if not info["raster"]:  # opciones de imagen no afectan a vectores
        opts = {k: opts[k] for k in ("curve_tol", "text_font", "dxf_closed_as_fill",
                                      "dxf_use_lineweight") if k in opts}
    key = fid + json.dumps(opts, sort_keys=True)
    with LOCK:
        if key in DOC_CACHE:
            DOC_CACHE.move_to_end(key)
            return DOC_CACHE[key]
    try:
        doc = importers.load(info["path"], **opts)
    except HTTPException:
        raise
    except Exception as e:  # noqa: BLE001 - se informa a la interfaz
        raise HTTPException(422, f"No se pudo leer el archivo: {e}") from e
    with LOCK:
        DOC_CACHE[key] = doc
        while len(DOC_CACHE) > 6:
            DOC_CACHE.popitem(last=False)
    return doc


def _run(fid: str, settings: dict):
    settings = dict(settings)
    imp = settings.pop("import", {})
    doc = _doc(fid, imp)
    title = Path(FILES[fid]["name"]).stem
    title = gcode._slug(title)[:40] or "dibujo"
    try:
        return job.run(doc, settings, store(), title=title), doc
    except KeyError as e:
        raise HTTPException(400, str(e)) from e


@app.post("/api/plan")
def plan(payload: dict = Body(...)):
    out, doc = _run(payload["file_id"], payload.get("settings", {}))
    res = job.summary(out)
    res["source_bounds"] = doc.bounds()
    res["extent"] = doc.extent
    return res


VIEWABLE = {".svg": "image/svg+xml", ".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
            ".gif": "image/gif", ".webp": "image/webp", ".bmp": "image/bmp"}


@app.get("/api/source/{fid}")
def source(fid: str):
    """Archivo original, para superponerlo en la vista previa."""
    info = FILES.get(fid)
    if not info:
        raise HTTPException(404, "Archivo no encontrado")
    ext = Path(info["path"]).suffix.lower()
    if ext not in VIEWABLE:
        raise HTTPException(415, "Formato sin vista directa")
    return FileResponse(info["path"], media_type=VIEWABLE[ext])


def _download(files: list[gcode.GcodeFile], zip_name: str):
    if not files:
        raise HTTPException(400, "No hay trazos para generar (¿plumas sin asignar?).")
    if len(files) == 1:
        return Response(files[0].text.encode("ascii", "replace"), media_type="text/plain",
                        headers={"Content-Disposition": f'attachment; filename="{files[0].name}"'})
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for f in files:
            z.writestr(f.name, f.text.encode("ascii", "replace"))
    return Response(buf.getvalue(), media_type="application/zip",
                    headers={"Content-Disposition": f'attachment; filename="{zip_name}.zip"'})


@app.post("/api/gcode")
def make_gcode(payload: dict = Body(...)):
    out, _ = _run(payload["file_id"], payload.get("settings", {}))
    return _download(out.files, Path(FILES[payload["file_id"]]["name"]).stem)


@app.post("/api/calibration")
def make_calibration(payload: dict = Body(...)):
    st = store()
    m = st.get("machines", payload.get("machine"))
    mat = st.get("materials", payload.get("material"))
    pen = st.get("pens", payload.get("pen"))
    area = pipeline.drawable_area(m, mat)
    pj = calibration.pattern(pen, area)
    files, stats = gcode.generate([pj], m, mat, title=f"calibracion_{gcode._slug(pen.name)}")
    if payload.get("download"):
        return _download(files, "calibracion")
    return {"jobs": preview.to_json([pj]), "drawable": area, "warnings": [], "groups": [],
            "stats": {"draw_mm": stats.draw_mm, "travel_mm": stats.travel_mm, "lifts": stats.lifts,
                      "seconds": stats.seconds, "time": gcode.format_time(stats.seconds),
                      "per_pen": stats.per_pen},
            "files": [{"name": f.name, "pens": f.pens, "lines": f.text.count("\n"),
                       "time": gcode.format_time(f.seconds)} for f in files]}


@app.put("/api/profiles/{kind}")
def save_profile(kind: str, data: dict = Body(...)):
    if kind not in KINDS:
        raise HTTPException(404, "Tipo de perfil desconocido")
    if not str(data.get("name", "")).strip():
        raise HTTPException(400, "El perfil necesita un nombre")
    obj = store().save(kind, data)
    return to_dict(obj)


@app.delete("/api/profiles/{kind}/{name}")
def delete_profile(kind: str, name: str):
    if kind not in KINDS:
        raise HTTPException(404, "Tipo de perfil desconocido")
    store().delete(kind, name)
    return {"ok": True}


def _free_port(host: str, port: int) -> int:
    import socket
    for p in range(port, port + 20):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sk:
            try:
                sk.bind((host, p))
                return p
            except OSError:
                continue
    return port


def serve(host: str = "127.0.0.1", port: int = 8765, open_browser: bool = True):
    import uvicorn
    port = _free_port(host, port)
    url = f"http://{host}:{port}/"
    print(f"Trazo {__version__} en {url}  (Ctrl+C para salir)")
    if open_browser:
        threading.Timer(1.2, lambda: webbrowser.open(url)).start()
    uvicorn.run(app, host=host, port=port, log_level="warning")
