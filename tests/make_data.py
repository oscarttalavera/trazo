"""Genera archivos de prueba en tests/data."""
from pathlib import Path

import ezdxf
import numpy as np
from PIL import Image, ImageDraw

D = Path(__file__).parent / "data"
D.mkdir(exist_ok=True)

# DXF con varias entidades, capas y un bloque
doc = ezdxf.new("R2010", setup=True)
doc.header["$INSUNITS"] = 4
doc.layers.add("CORTE", color=1)
doc.layers.add("GRABADO", color=5)
msp = doc.modelspace()
msp.add_line((0, 0), (80, 0), dxfattribs={"layer": "CORTE"})
msp.add_lwpolyline([(0, 0, 0, 0, 0), (80, 0, 0, 0, 0), (80, 50, 0, 0, 0.5), (0, 50)], close=True,
                   dxfattribs={"layer": "CORTE"})
msp.add_circle((20, 25), 10, dxfattribs={"layer": "GRABADO"})
msp.add_arc((60, 25), 12, 0, 180, dxfattribs={"layer": "GRABADO"})
msp.add_ellipse((60, 25), major_axis=(8, 0), ratio=0.5, dxfattribs={"layer": "GRABADO"})
msp.add_spline([(5, 40), (20, 48), (35, 35), (50, 45)], dxfattribs={"layer": "GRABADO"})
msp.add_text("DXF 123", height=5, dxfattribs={"layer": "GRABADO", "insert": (30, 5)})
msp.add_lwpolyline([(5, 5), (25, 5)], dxfattribs={"layer": "CORTE", "const_width": 2.0})
blk = doc.blocks.new("ESTRELLA")
pts = [(np.cos(a) * (4 if i % 2 else 8), np.sin(a) * (4 if i % 2 else 8))
       for i, a in enumerate(np.linspace(np.pi / 2, np.pi / 2 + 2 * np.pi, 11)[:-1])]
blk.add_lwpolyline(pts, close=True)
for x in (10, 40, 70):
    msp.add_blockref("ESTRELLA", (x, 60), dxfattribs={"layer": "GRABADO", "xscale": 0.8})
hatch = msp.add_hatch(color=3, dxfattribs={"layer": "RELLENO"})
hatch.paths.add_polyline_path([(85, 0), (110, 0), (110, 25), (85, 25)], is_closed=True)
doc.saveas(D / "sample.dxf")

# Logo PNG a 2 colores con transparencia
im = Image.new("RGBA", (600, 400), (0, 0, 0, 0))
dr = ImageDraw.Draw(im)
dr.ellipse((40, 40, 360, 360), fill=(220, 30, 30, 255))
dr.ellipse((120, 120, 280, 280), fill=(0, 0, 0, 0))
dr.rectangle((300, 150, 560, 250), fill=(20, 20, 160, 255))
dr.line((60, 380, 560, 380), fill=(20, 20, 160, 255), width=4)
im.save(D / "logo.png", dpi=(150, 150))

# Foto sintética: degradado radial + texto
yy, xx = np.mgrid[:300, :400]
g = 255 * np.clip(np.hypot(xx - 200, yy - 150) / 220, 0, 1)
Image.fromarray(g.astype(np.uint8)).convert("RGB").save(D / "foto.jpg", quality=90)

# Dibujo de línea (para centerline)
im = Image.new("L", (400, 300), 255)
dr = ImageDraw.Draw(im)
dr.line((20, 280, 200, 20, 380, 280), fill=0, width=6)
dr.arc((100, 100, 300, 300), 180, 360, fill=0, width=6)
im.save(D / "linea.png")
print("ok")
