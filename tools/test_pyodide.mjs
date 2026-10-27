// Corre la suite de pruebas DENTRO de Pyodide (el mismo motor que usa el navegador).
//
//   node tools/test_pyodide.mjs RUTA_A_PYODIDE_COMPLETO [site]
//
// Detecta diferencias de comportamiento entre las bibliotecas nativas y las de
// WebAssembly (p. ej. la versión de GEOS que trae Pyodide).
import { readFileSync } from "node:fs";
import path from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const pyodideDir = path.resolve(process.argv[2] || "");
const site = path.resolve(process.argv[3] || path.join(root, "site"));
const { loadPyodide } = await import(pathToFileURL(path.join(pyodideDir, "pyodide.mjs")).href);

const manifest = JSON.parse(readFileSync(path.join(site, "py", "manifest.json"), "utf8"));
const py = await loadPyodide({ indexURL: pyodideDir + "/" });
const pkgs = Object.values(manifest.pyodide).flat();
const wheels = Object.values(manifest.wheels).flat().map((w) => pathToFileURL(path.join(site, "py", w)).href);
await py.loadPackage([...pkgs, "pytest", ...wheels], { messageCallback: () => {} });

py.FS.mkdirTree("/work/tests");
py.FS.mount(py.FS.filesystems.NODEFS, { root: path.join(root, "tests") }, "/work/tests");
const args = JSON.stringify((process.env.PYTEST_ARGS || "tests").split(/\s+/).filter(Boolean));
const code = py.runPython(`
import json, os, pytest
os.chdir("/work")
int(pytest.main(["-q", "-p", "no:cacheprovider", *json.loads(${JSON.stringify(args)})]))
`);
process.exit(code);
