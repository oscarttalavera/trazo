/* Trazo — motor en un Web Worker: Python (Pyodide) ejecuta todo el cálculo
   dentro del navegador. Los archivos nunca salen de la computadora del usuario. */
"use strict";
const BASE = new URL("./", self.location.href).href;
importScripts(BASE + "pyodide/pyodide.js");

let py = null, api = null, manifest = null;
const loaded = new Set();
const status = (text, pct) => self.postMessage({ type: "status", text, pct });

async function loadGroup(group) {
  if (loaded.has(group)) return;
  const pkgs = manifest.pyodide[group] || [];
  const wheels = (manifest.wheels[group] || []).map((w) => BASE + "py/" + w);
  if (pkgs.length || wheels.length) await py.loadPackage([...pkgs, ...wheels], { messageCallback: () => {}, errorCallback: () => {} });
  loaded.add(group);
}

const ready = (async () => {
  status("Descargando el motor de cálculo…", 5);
  manifest = await (await fetch(BASE + "py/manifest.json", { cache: "no-cache" })).json();
  py = await loadPyodide({ indexURL: BASE + "pyodide/" });
  status("Cargando bibliotecas geométricas…", 55);
  await loadGroup("base");
  status("Iniciando Trazo…", 90);
  api = py.pyimport("trazo.webapi");
  status("Listo", 100);
})();

async function call(name, args) {
  const raw = api.call(name, ...args);
  return JSON.parse(raw);
}

self.onmessage = async (e) => {
  const { id, method, args = [], file } = e.data;
  try {
    await ready;
    if (method === "open") {
      // carga perezosa de lo que necesita cada formato
      const ext = file.name.split(".").pop().toLowerCase();
      if (ext === "dxf") { status("Cargando lector DXF…", 50); await loadGroup("dxf"); }
      if (ext === "svg") await loadGroup("svg");
      const dir = "/tmp/archivos";
      try { py.FS.mkdirTree(dir); } catch (_) { /* ya existe */ }
      const path = `${dir}/${Date.now()}_${Math.random().toString(36).slice(2, 8)}.${ext}`;
      py.FS.writeFile(path, new Uint8Array(file.buffer));
      self.postMessage({ id, result: await call("open_path", [file.name, path]) });
      status("Listo", 100);
      return;
    }
    self.postMessage({ id, result: await call(method, args) });
  } catch (err) {
    // ¿el intérprete quedó inutilizable? (p. ej. una excepción C++ de GEOS)
    let fatal = false;
    try { py.runPython("1"); } catch (_) { fatal = true; }
    const msg = err && err.message ? err.message.split("\n").filter(Boolean).slice(-1)[0] : String(err);
    self.postMessage({ id, fatal, result: { error: "Error del motor: " + msg } });
  }
};
ready.catch((err) => self.postMessage({ type: "fatal", text: String(err && err.message ? err.message : err) }));
