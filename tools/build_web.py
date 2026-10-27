"""Arma el sitio web estático de Trazo en site/ (o --out).

    python tools/build_web.py [--pyodide CARPETA] [--out site]

Sin --pyodide, descarga la distribución completa de Pyodide (una sola vez, ~390 MB)
a .cache/ desde https://github.com/pyodide/pyodide/releases. Solo se copian al
sitio el núcleo y los paquetes que Trazo usa (~20 MB en vez de ~450 MB).

El resultado no necesita servidor: se puede publicar en cualquier hosting
estático y en cualquier subruta (todas las rutas son relativas).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PYODIDE_VERSION = "0.29.3"
CORE = ["pyodide.js", "pyodide.mjs", "pyodide.asm.js", "pyodide.asm.wasm", "python_stdlib.zip",
        "pyodide-lock.json", "package.json"]
# paquetes de la distribución de Pyodide (se cargan por nombre)
PYODIDE_PKGS = {
    "base": ["numpy", "shapely", "pillow"],
    "dxf": ["fonttools", "pyparsing", "typing-extensions"],
}
# ruedas de Python puro desde PyPI
PYPI_WHEELS = {
    "base": ["potracer", "Hershey-Fonts"],
    "svg": ["svgelements"],
    "dxf": ["ezdxf"],
}


def resolve(lock: dict, names: list[str]) -> list[str]:
    pkgs = {k.lower(): v for k, v in lock["packages"].items()}
    out: list[str] = []

    def visit(n: str):
        n = n.lower()
        if n in out:
            return
        if n not in pkgs:
            raise SystemExit(f"El paquete '{n}' no está en pyodide-lock.json")
        for d in pkgs[n].get("depends", []):
            visit(d)
        out.append(n)

    for n in names:
        visit(n)
    return out


def fetch_pyodide(version: str = PYODIDE_VERSION) -> Path:
    """Descarga y extrae la distribución completa de Pyodide en .cache/ (si no está ya)."""
    import tarfile
    import urllib.request

    dest = ROOT / ".cache" / f"pyodide-{version}"
    if (dest / "pyodide" / "pyodide-lock.json").exists():
        return dest / "pyodide"
    dest.mkdir(parents=True, exist_ok=True)
    url = f"https://github.com/pyodide/pyodide/releases/download/{version}/pyodide-{version}.tar.bz2"
    tmp = dest / "pyodide.tar.bz2"
    print(f"Descargando {url} …")
    urllib.request.urlretrieve(url, tmp)
    with tarfile.open(tmp, "r:bz2") as tf:
        tf.extractall(dest, filter="data")
    tmp.unlink()
    return dest / "pyodide"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--pyodide", type=Path, help="carpeta pyodide/ de la distribución completa")
    ap.add_argument("--out", default=ROOT / "site", type=Path)
    a = ap.parse_args()
    src, out = a.pyodide or fetch_pyodide(), a.out
    if not (src / "pyodide-lock.json").exists():
        raise SystemExit(f"No encuentro pyodide-lock.json en {src}")

    if out.exists():
        shutil.rmtree(out)
    shutil.copytree(ROOT / "web", out)

    # núcleo + paquetes de Pyodide
    pdir = out / "pyodide"
    pdir.mkdir()
    for f in CORE:
        shutil.copy2(src / f, pdir / f)
    lock = json.loads((src / "pyodide-lock.json").read_text())
    pkgs = {k.lower(): v for k, v in lock["packages"].items()}
    groups_pyodide = {}
    for group, names in PYODIDE_PKGS.items():
        resolved = resolve(lock, names)
        groups_pyodide[group] = resolved
        for n in resolved:
            shutil.copy2(src / pkgs[n]["file_name"], pdir / pkgs[n]["file_name"])

    # ruedas: trazo + Python puro
    wdir = out / "py"
    wdir.mkdir()
    with tempfile.TemporaryDirectory() as tmp:
        subprocess.run([sys.executable, "-m", "pip", "wheel", "-q", "--no-deps", "-w", tmp, str(ROOT)], check=True)
        trazo_whl = next(Path(tmp).glob("trazo-*.whl"))
        shutil.copy2(trazo_whl, wdir / trazo_whl.name)
    groups_wheels: dict[str, list[str]] = {}
    for group, names in PYPI_WHEELS.items():
        with tempfile.TemporaryDirectory() as tmp:
            subprocess.run([sys.executable, "-m", "pip", "download", "-q", "--only-binary=:all:", "--no-deps",
                            "--python-version", "3.13", "--platform", "any", "--implementation", "py",
                            "-d", tmp, *names], check=True)
            files = sorted(p.name for p in Path(tmp).glob("*.whl"))
            for f in files:
                shutil.copy2(Path(tmp) / f, wdir / f)
        groups_wheels[group] = files
    groups_wheels["base"] = [trazo_whl.name] + groups_wheels["base"]

    # manifiesto que lee el worker
    import importlib.util
    spec = importlib.util.spec_from_file_location("trazo_init", ROOT / "trazo" / "__init__.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    manifest = {"version": mod.__version__, "pyodide": groups_pyodide, "wheels": groups_wheels}
    (wdir / "manifest.json").write_text(json.dumps(manifest, indent=2))

    # versión de caché del service worker = huella del contenido
    h = hashlib.sha256()
    for p in sorted(out.rglob("*")):
        if p.is_file() and p.name != "sw.js":
            h.update(p.relative_to(out).as_posix().encode())
            h.update(hashlib.sha256(p.read_bytes()).digest())
    precache = ["./"] + sorted(p.relative_to(out).as_posix() for p in out.rglob("*")
                               if p.is_file() and p.name not in ("sw.js", "index.html", "package.json")
                               and not p.name.endswith(".mjs"))
    sw = out / "sw.js"
    sw.write_text(sw.read_text().replace("__CACHE_VERSION__", f"{mod.__version__}-{h.hexdigest()[:10]}")
                  .replace("__PRECACHE__", json.dumps(precache)))

    size = sum(p.stat().st_size for p in out.rglob("*") if p.is_file())
    print(f"Sitio listo en {out}  ({size / 1e6:.1f} MB, Trazo {mod.__version__})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
