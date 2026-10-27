# Integrar Trazo en tools.tritic3d.com

Contexto para continuar desde el proyecto de **tools.tritic3d.com** (GitHub Pages).

## Qué es Trazo y en qué estado está
- Generador de G-code para plotter de pluma en impresoras 3D (Ender 3 V1 y
  similares). Acepta SVG, DXF, PNG y JPG y ajusta el ancho de línea al
  diámetro de la punta.
- Tiene varios colores (pausa o un archivo por pluma) y **densidades de gris
  con una sola pluma**.
- Versión **0.3.0**, en `main` de **`oscarttalavera/trazo`** (repositorio
  **privado**).
- **Sitio 100 % estático:**
  - el motor en Python corre en el navegador con Pyodide 0.29.3 (WebAssembly),
    dentro de un Web Worker;
  - no hay backend, y los archivos del usuario no salen del navegador;
  - carga inicial de ~17 MB; luego queda en caché por service worker y
    funciona sin conexión.
- **Interfaz** con el sistema visual Tritic, tema claro y oscuro, y logotipo
  propio en `docs/marca/`.
- **Pruebas:** 49 que corren en CPython y dentro de Pyodide en el CI.
- **No se ha probado aún en una impresora real.**

## Qué se publica
Cada etiqueta `v*` del repo de Trazo crea un Release con
**`trazo-web-<versión>.zip`** (~12 MB comprimido, ~20 MB descomprimido). El
contenido se sube **tal cual** a una carpeta. Todas las rutas son relativas.

```
index.html  app.js  worker.js  sw.js  icons.js  style.css  manifest.webmanifest
assets/  fonts/  pyodide/  py/
```

Requisitos que GitHub Pages ya cumple:
- HTTPS, que exige el service worker;
- `.wasm` servido como `application/wasm`;
- archivos `.whl` y `.zip` permitidos;
- ningún archivo supera los 100 MB.

**Si el sitio se publica desde una rama (no con Actions)**, agregue
`.nojekyll` en la raíz para que Jekyll no procese la carpeta.

## Convivencia con las demás herramientas del dominio
- El service worker (`trazo/sw.js`) solo controla `/trazo/` y sus cachés
  empiezan con `trazo-`, así que no toca otras herramientas.
- localStorage es compartido por todo `tools.tritic3d.com`. Trazo usa solo
  claves `trazo.*`. Si otra herramienta usa un service worker en la raíz `/`,
  revisar que no intercepte `/trazo/`.

## Opciones de integración

### A. El sitio de tools descarga el Release de Trazo al desplegar (recomendada)
El repo de tools fija la versión en un archivo (p. ej. `trazo.version` con
`v0.3.0`). Su workflow de Pages descarga ese zip y lo descomprime en
`<carpeta del sitio>/trazo/` antes de publicar.

- **Ventajas:** el código de Trazo y su CI se quedan en su repo; actualizar es
  cambiar una línea; no se infla el historial del repo de tools.
- **Requisito:** como el repo de Trazo es privado, el workflow de tools
  necesita un token de lectura. Por ejemplo, un *fine-grained PAT* con
  `Contents: Read-only` sobre `oscarttalavera/trazo`, guardado como secreto
  `TRAZO_TOKEN` en el repo de tools. Otra opción es hacer público el repo de
  Trazo.

Paso de ejemplo; hay que adaptar `_site` a la carpeta que publique el workflow
de tools:

```yaml
- name: Incluir Trazo
  env:
    GH_TOKEN: ${{ secrets.TRAZO_TOKEN }}
  run: |
    V=$(cat trazo.version)
    gh release download "$V" --repo oscarttalavera/trazo --pattern "trazo-web-$V.zip" --dir /tmp/trazo
    mkdir -p _site/trazo
    unzip -q "/tmp/trazo/trazo-web-$V.zip" -d _site/trazo
```

Si hoy el sitio de tools se publica desde una rama sin Actions, hay que
pasarlo a un workflow de Pages: *Settings → Pages → Source: GitHub Actions*,
con `actions/upload-pages-artifact` y `actions/deploy-pages`.

### B. Copiar los archivos al repo de tools
Descomprimir el zip en `trazo/` dentro del repo de tools y hacer commit.

- **Ventajas:** lo más simple, sin tokens.
- **Desventajas:** unos 20 MB por versión en el historial y actualización
  manual.

### C. Mover el código de Trazo al repo de tools (monorepo)
Solo si se quiere un único repositorio. Habría que mover `trazo/`, `web/`,
`tools/`, `tests/` y `pyproject.toml` a una subcarpeta y adaptar las rutas de
`.github/workflows/web.yml`. El CI debe seguir corriendo las pruebas en los dos
motores. No se recomienda: mezcla una app con Python y pruebas pesadas con el
resto del sitio.

## Pasos sugeridos en el proyecto de tools
1. Revisar cómo se despliega hoy tools.tritic3d.com: rama o Actions, carpeta
   de salida, generador (HTML plano, Jekyll, Astro…).
2. Implementar la opción A (o B) para servir Trazo en
   `https://tools.tritic3d.com/trazo/`.
3. Agregar Trazo al índice o menú de herramientas:
   - nombre «Trazo»;
   - descripción corta: «G-code para plotter de pluma en impresoras 3D»;
   - icono `trazo-simbolo.svg` (está en el zip, en `assets/`).
4. Verificar en producción:
   - el motor arranca (*Motor listo*);
   - abrir un SVG, un DXF y una foto en modo «Escala de grises» y descargar el
     G-code;
   - recargar sin conexión (DevTools → Network → Offline) y que siga
     funcionando;
   - que `/trazo/pyodide/pyodide.asm.wasm` responda con `application/wasm`.
5. Opcional: que el pie o la cabecera común de tools enlace a Trazo. Trazo ya
   lleva su propia firma «una herramienta de Tritic».

## Para seguir desarrollando Trazo
El desarrollo sigue en `oscarttalavera/trazo`; lea su `CLAUDE.md`, que tiene
la arquitectura, las reglas que no se deben romper y el backlog.

**Publicar una versión nueva:**
1. subir la versión en `trazo/__init__.py` y en `pyproject.toml`;
2. hacer push a `main`;
3. `git tag vX.Y.Z && git push origin vX.Y.Z`;
4. en el repo de tools, cambiar `trazo.version` (opción A).

Más adelante se puede automatizar: un `repository_dispatch` desde el
workflow de Trazo que abra un PR en tools con la nueva versión.

**Próximos pasos con más valor:**
- probar en una Ender 3 V1 real (pausa `M0`, modo «insert», offset de pluma);
- envío directo por USB con la **Web Serial API**;
- pruebas end-to-end de la interfaz en el CI.
