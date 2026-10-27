# Trazo — guía para continuar el desarrollo

Generador de G-code para plotter de pluma sobre impresoras 3D cartesianas
(Ender 3 V1 y similares). Una herramienta de **Tritic**. Interfaz y documentación
en **español**; identificadores de código en inglés y comentarios en español.

## Arquitectura (desde v0.3.0)
- **100 % web y estático.** El motor en Python (`trazo/`) corre en el navegador
  con **Pyodide 0.29.3** dentro de un Web Worker (`web/worker.js`). No hay
  servidor y los archivos del usuario no salen del navegador.
- `web/app.js` (UI) ⇄ `postMessage` ⇄ `web/worker.js` ⇄ `trazo/webapi.py`
  (`call(nombre, *args)`, todo entra y sale como JSON; los errores para el
  usuario se lanzan como `UserError`).
- `tools/build_web.py` arma `site/`:
  - copia `web/`, el núcleo de Pyodide y solo los paquetes necesarios
    (numpy, shapely, pillow; el grupo `dxf` se carga bajo demanda);
  - construye la rueda de `trazo` y genera `py/manifest.json` y la lista de
    precarga de `sw.js`.
- `web/sw.js` precarga todo al instalarse: la app funciona sin conexión desde
  la primera visita. La versión de caché es una huella del contenido.
- La CLI (`trazo …`) usa el mismo motor; es opcional, para lotes.

## Reglas que no se deben romper
1. **Operaciones booleanas de shapely siempre con `grid_size`.** Usar
   `fill._union` / `fill._difference` o pasar `grid_size=GRID`. Con el GEOS 3.12
   de Pyodide una `TopologyException` **detiene el intérprete entero** (no es
   una excepción de Python que se pueda capturar).
2. **Sin scipy ni scikit-image.** Pesan ~25 MB en el navegador. Lo que haga
   falta va en `trazo/imgproc.py`, con numpy y Pillow.
3. **Rutas relativas** en todo `web/`: el sitio se publica en una subcarpeta
   (`tools.tritic3d.com/trazo/`).
4. **Correr las pruebas en los dos motores** antes de publicar:
   ```bash
   pytest -q
   python tools/build_web.py
   node tools/test_pyodide.mjs .cache/pyodide-0.29.3/pyodide site
   ```
   Lo que pasa en CPython puede fallar en Pyodide; el CI corre ambas.
5. **Sistema visual Tritic** («plano de taller»):
   - IBM Plex Sans/Mono, y Syncopate solo en el nombre TRAZO;
   - filetes en lugar de sombras, esquinas de 0–2 px;
   - **un solo acento verde #00FFC7 por vista** (el botón *Generar G-code*), y
     el verde nunca sobre blanco;
   - chips azules con índice mono verde; tema claro y oscuro con tokens CSS.

   Las fuentes van incluidas en `web/fonts/` (OFL), sin CDN. El logotipo de
   Tritic usa los SVG oficiales de `web/assets/`: versión azul sobre claro,
   blanca sobre azul #00476A, verde sobre azul noche. Nunca se reescribe con una
   fuente.
6. **Claves de almacenamiento en el navegador** con prefijo `trazo.`: el origen
   `tools.tritic3d.com` es compartido con otras herramientas. Claves actuales:
   - `trazo.settings.v1`: ajustes;
   - `trazo.ui.v2`: estado de la interfaz;
   - `trazo.profiles.v1`: perfiles propios.

   Los cachés del service worker usan el prefijo `trazo-`.
7. **G-code seguro.** Nunca calentar ni mover el extrusor. Solo comandos
   básicos: G0/G1/G4/G21/G28/G90, M0, M84, M104/M140/M107 S0, M117 y M204.

## Conceptos del dominio
- **Ancho de punta:**
  - los rellenos se contraen ½ punta;
  - la separación entre pasadas es `punta × (1 − traslape)`;
  - los trazos más gruesos que la punta se hacen con pasadas paralelas;
  - lo más fino que la punta se dibuja por su eje central.
- **Densidad por grupo (color/capa):** sólida, un porcentaje o «auto» según la
  luminancia lineal (`trazo/tone.py`). Negro y grises usan «auto» por defecto;
  los colores van sólidos. Los tonos parciales no se compensan ni llevan
  contorno.
- **Modo de contacto «insert»** (por defecto): home sin pluma; la máquina baja
  a la Z de contacto (grosor del material + holgura) y pausa (`M0`) para
  insertar la pluma tocando la superficie. Al cambiar de pluma hay dos pausas:
  retirar e insertar.
- **Perfiles:** máquina, pluma y material (`trazo/profiles.py`). En la web, los
  perfiles propios viven en localStorage y se pueden exportar e importar en JSON.

## Publicación
- **CI** (`.github/workflows/web.yml`): en cada push corre las pruebas en
  ambos motores y genera el artefacto `trazo-web.zip`. Con una etiqueta `v*`
  crea un Release con `trazo-web-<versión>.zip`.
- **Nueva versión:**
  1. subir `__version__` en `trazo/__init__.py` y en `pyproject.toml`;
  2. hacer push a `main`;
  3. `git tag vX.Y.Z && git push origin vX.Y.Z`.
- La integración con tools.tritic3d.com está en
  `docs/integracion-tools-tritic3d.md`.

## Pendiente / ideas
- **No se ha probado en una impresora real.** Validar en una Ender 3 V1 stock:
  la pausa `M0`, el modo «insert», el offset de la pluma y los tiempos estimados.
- Enviar G-code directo a la impresora por USB con la **Web Serial API**
  (Chrome/Edge), sin pasar por la SD.
- Arcos G2/G3; fuentes TrueType como contorno; punteado para fotos; servo
  (M280); mejora 2-opt del orden; regla *nonzero* exacta.
- Pruebas end-to-end de la interfaz con Playwright en el CI.
