"""Genera los archivos del logotipo de Trazo (símbolo + nombre en Syncopate a trazos)."""
import sys
from pathlib import Path

from fontTools.pens.boundsPen import BoundsPen
from fontTools.pens.svgPathPen import SVGPathPen
from fontTools.pens.transformPen import TransformPen
from fontTools.ttLib import TTFont

FONT, OUT = Path(sys.argv[1]), Path(sys.argv[2])
AZUL, AZUL_900, VERDE, NOCHE, BLANCO = "#00476A", "#002F47", "#00FFC7", "#04202F", "#FFFFFF"


def wordmark(text="TRAZO", height=40.0, tracking=0.06):
    f = TTFont(FONT)
    gs, cmap, upm = f.getGlyphSet(), f.getBestCmap(), f["head"].unitsPerEm
    cap = f["OS/2"].sCapHeight or upm * 0.7
    s = height / cap
    pen = SVGPathPen(gs)
    x = 0.0
    for ch in text:
        name = cmap[ord(ch)]
        tp = TransformPen(pen, (s, 0, 0, -s, x, height))
        gs[name].draw(tp)
        x += gs[name].width * s + tracking * height * 2.2
    bp = BoundsPen(gs)
    gs[cmap[ord(text[-1])]].draw(bp)
    width = x - tracking * height * 2.2 - (gs[cmap[ord(text[-1])]].width - bp.bounds[2]) * s
    return pen.getCommands(), width


def symbol(x=0, y=0, size=64, grid=True):
    k = size / 64
    parts = [f'<rect x="{x}" y="{y}" width="{size}" height="{size}" fill="{AZUL}"/>']
    if grid:  # retícula de puntos (papel de ingeniería)
        dots = "".join(f'<circle cx="{x + (6 + i * 8) * k:.2f}" cy="{y + (6 + j * 8) * k:.2f}" r="{0.9 * k:.2f}"/>'
                       for i in range(7) for j in range(7))
        parts.append(f'<g fill="{AZUL_900}">{dots}</g>')
    if size <= 24:  # tamaños de favicon: T sólida, sin detalle
        parts.append(f'<g fill="{VERDE}"><rect x="{x + 12 * k:.2f}" y="{y + 12 * k:.2f}" width="{40 * k:.2f}" '
                     f'height="{9 * k:.2f}"/><rect x="{x + 27 * k:.2f}" y="{y + 12 * k:.2f}" width="{10 * k:.2f}" '
                     f'height="{40 * k:.2f}"/></g>')
        return "".join(parts)
    # barra de la T: trazo sólido; tallo: relleno en zigzag de una sola línea continua
    rows = [21.75 + 4.0 * i for i in range(8)]
    pts = [(27.25, 18.0)]  # nace de la barra
    for i, yy in enumerate(rows):
        a, b = (27.25, 36.75) if i % 2 == 0 else (36.75, 27.25)
        pts += [(a, yy), (b, yy)]
    d = "M" + " L".join(f"{x + px * k:.2f},{y + py * k:.2f}" for px, py in pts)
    parts.append(f'<rect x="{x + 12 * k:.2f}" y="{y + 12 * k:.2f}" width="{40 * k:.2f}" height="{7 * k:.2f}" '
                 f'fill="{VERDE}"/>')
    parts.append(f'<path d="{d}" fill="none" stroke="{VERDE}" stroke-width="{2.5 * k:.2f}" '
                 f'stroke-linejoin="miter" stroke-linecap="square"/>')
    return "".join(parts)


def svg(w, h, body, title="Trazo"):
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {w:.1f} {h:.1f}" role="img" '
            f'aria-label="{title}"><title>{title}</title>{body}</svg>\n')


OUT.mkdir(parents=True, exist_ok=True)
(OUT / "trazo-simbolo.svg").write_text(svg(64, 64, symbol()), encoding="utf-8")
(OUT / "trazo-simbolo-simple.svg").write_text(svg(16, 16, symbol(0, 0, 16, grid=False)), encoding="utf-8")
d, ww = wordmark(height=26)
for name, color in (("trazo-logo", AZUL), ("trazo-logo-blanco", BLANCO)):
    body = symbol(0, 0, 64) + f'<path transform="translate(84,19)" fill="{color}" d="{d}"/>'
    (OUT / f"{name}.svg").write_text(svg(84 + ww + 2, 64, body), encoding="utf-8")
(OUT / "trazo-nombre.svg").write_text(svg(ww + 1, 26, f'<path fill="{AZUL}" d="{d}"/>'), encoding="utf-8")
(OUT / "trazo-nombre-blanco.svg").write_text(svg(ww + 1, 26, f'<path fill="{BLANCO}" d="{d}"/>'), encoding="utf-8")
print("ok", round(ww, 1))
