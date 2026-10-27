import re
from pathlib import Path

import numpy as np
import pytest
import shapely
from shapely.geometry import LineString, box

from trazo import calibration, fill as F, gcode, importers, job, optimize, pipeline
from trazo.geometry import Item
from trazo.profiles import MachineProfile, MaterialProfile, PenProfile, ProfileStore

DATA = Path(__file__).parent / "data"


@pytest.fixture(autouse=True)
def _home(tmp_path, monkeypatch):
    monkeypatch.setenv("TRAZO_HOME", str(tmp_path))


@pytest.fixture(scope="session", autouse=True)
def _data():
    if not (DATA / "sample.dxf").exists():
        import runpy
        runpy.run_path(str(Path(__file__).parent / "make_data.py"))


def ink(paths, tip):
    """Región que cubre la tinta de una lista de trayectorias."""
    parts = [LineString(p).buffer(tip / 2) if len(p) > 1 else shapely.Point(p[0]).buffer(tip / 2) for p in paths]
    return shapely.union_all(parts)


# --- importadores ---------------------------------------------------------

def test_svg_units_and_widths():
    doc = importers.load(str(DATA / "sample.svg"))
    rect = next(i for i in doc.items if i.color == "#ff0000")
    xs, ys = rect.paths[0][:, 0], rect.paths[0][:, 1]
    assert xs.min() == pytest.approx(5, abs=1e-3) and xs.max() == pytest.approx(35, abs=1e-3)
    # viewBox 200 -> 100 mm: y=10..50 (abajo) -> 45..25 mm con Y arriba
    assert ys.max() == pytest.approx(45, abs=1e-3) and ys.min() == pytest.approx(25, abs=1e-3)
    assert rect.width == pytest.approx(0.5, abs=1e-3)
    kinds = {(i.kind, i.color) for i in doc.items}
    assert ("fill", "#0000ff") in kinds and ("stroke", "#008000") in kinds  # texto Hershey
    assert {i.layer for i in doc.items} == {"Contornos", "Texto"}


def test_dxf_entities_layers_units():
    doc = importers.load(str(DATA / "sample.dxf"))
    layers = {i.layer for i in doc.items}
    assert {"CORTE", "GRABADO", "RELLENO"} <= layers
    assert any(i.kind == "fill" for i in doc.items)  # HATCH
    assert any(i.width == pytest.approx(2.0) for i in doc.items)  # LWPOLYLINE con ancho
    b = doc.bounds()
    assert b[2] == pytest.approx(110, abs=0.1)
    # 3 estrellas del bloque
    stars = [i for i in doc.items if i.layer == "GRABADO" and len(i.paths[0]) == 11]
    assert len(stars) == 3


@pytest.mark.parametrize("mode", ["trace", "centerline", "hatch", "edges"])
def test_raster_modes(mode):
    src = DATA / ("linea.png" if mode == "centerline" else "foto.jpg" if mode == "hatch" else "logo.png")
    doc = importers.load(str(src), raster_mode=mode, width_mm=80)
    assert doc.items
    b = doc.bounds()
    assert 0 <= b[0] and b[2] <= 80.5


def test_raster_color_separation():
    doc = importers.load(str(DATA / "logo.png"), raster_mode="trace", colors=2, width_mm=100)
    colors = {i.color for i in doc.items}
    assert len(colors) == 2


# --- ancho de punta -------------------------------------------------------

def test_fill_compensation_stays_inside_and_covers():
    sq = box(0, 0, 10, 10)
    tip = 1.0
    r = F.fill_geometry(sq, tip, 0.15, F.FillSettings(pattern="zigzag"))
    allp = np.vstack(r.paths)
    assert allp.min() >= 0.5 - 1e-6 and allp.max() <= 9.5 + 1e-6
    covered = ink(r.paths, tip)
    assert covered.intersection(sq).area / sq.area > 0.98
    assert covered.difference(sq).area < 0.01


@pytest.mark.parametrize("pattern", ["lines", "cross", "concentric", "none"])
def test_fill_patterns(pattern):
    r = F.fill_geometry(box(0, 0, 20, 10), 0.5, 0.1, F.FillSettings(pattern=pattern))
    assert r.paths
    if pattern != "none":
        assert ink(r.paths, 0.5).area > 0.95 * 200


def test_zigzag_reduces_lifts():
    sq = box(0, 0, 30, 30)
    lines = F.fill_geometry(sq, 0.5, 0.1, F.FillSettings(pattern="lines", outline=False))
    zz = F.fill_geometry(sq, 0.5, 0.1, F.FillSettings(pattern="zigzag", outline=False))
    assert len(zz.paths) < len(lines.paths) / 10


def test_hole_respected():
    outer = np.array([[0, 0], [20, 0], [20, 20], [0, 20], [0, 0]], float)
    hole = np.array([[5, 5], [15, 5], [15, 15], [5, 15], [5, 5]], float)
    it = Item("fill", [outer, hole], [True, True])
    r = F.item_paths(it, 0.5, 0.1, F.FillSettings(), F.StrokeSettings())
    covered = ink(r.paths, 0.5)
    assert covered.intersection(box(5.05, 5.05, 14.95, 14.95)).area < 0.01


def test_thick_stroke_becomes_parallel_passes():
    p = np.array([[0, 0], [30, 0]], float)
    it = Item("stroke", [p], [False], width=3.0)
    r = F.item_paths(it, 0.5, 0.1, F.FillSettings(), F.StrokeSettings())
    assert len(r.paths) >= 2
    target = LineString(p).buffer(1.5)
    covered = ink(r.paths, 0.5)
    assert covered.intersection(target).area / target.area > 0.97
    # en modo "single" solo una pasada
    r1 = F.item_paths(it, 0.5, 0.1, F.FillSettings(), F.StrokeSettings(mode="single"))
    assert len(r1.paths) == 1


def test_thin_feature_uses_centerline():
    thin = box(0, 0, 20, 0.3)  # más delgado que la punta
    r = F.fill_geometry(thin, 0.5, 0.1, F.FillSettings())
    assert r.thin_features == 1
    allp = np.vstack(r.paths)
    assert np.all(np.abs(allp[:, 1] - 0.15) < 0.2)
    assert allp[:, 0].max() - allp[:, 0].min() > 18


# --- optimización ---------------------------------------------------------

def test_order_keeps_everything_and_reduces_travel():
    rng = np.random.default_rng(1)
    segs = [np.array([[x, y], [x + 1, y]]) for x, y in rng.uniform(0, 100, (300, 2))]
    out = optimize.order(segs, (0, 0), merge_tol=0)
    assert len(out) == 300
    assert sum(len(p) for p in out) == 600
    _, t0, _ = optimize.travel_stats(segs)
    _, t1, _ = optimize.travel_stats(out)
    assert t1 < t0 / 3


def test_order_merges_touching_paths():
    a = np.array([[0, 0], [10, 0]], float)
    b = np.array([[20, 0], [10, 0]], float)  # invertido
    out = optimize.order([a, b], (0, 0), merge_tol=0.1)
    assert len(out) == 1 and len(out[0]) == 4


# --- G-code -----------------------------------------------------------------

def _plan(src="sample.svg", **settings):
    st = ProfileStore()
    doc = importers.load(str(DATA / src))
    d = {"default_pen": "Fineliner 0.5", **settings}
    return job.run(doc, d, st, title="t")


def test_gcode_is_safe_and_in_bounds():
    out = _plan(layout={"scale_mode": "fit"})
    text = out.files[0].text
    assert "G28" in text and "M0 " in text
    assert not re.search(r"\bE-?\d", text), "nunca debe mover el extrusor"
    assert not re.search(r"M10[49] S[1-9]", text) and not re.search(r"M1(40|90) S[1-9]", text)
    m = MachineProfile()
    for x, y in re.findall(r"^G[01] X([-\d.]+) Y([-\d.]+)", text, re.M):
        assert m.x_min <= float(x) <= m.x_max and m.y_min <= float(y) <= m.y_max
    zs = {float(z) for z in re.findall(r"Z([-\d.]+)", text)}
    w = gcode.Writer(m, MaterialProfile())
    assert min(zs) == pytest.approx(w.z_contact - m.pen_press)
    assert out.stats.out_of_bounds == 0


def test_pen_offset_shifts_nozzle():
    st = ProfileStore()
    st.save("machines", {**MachineProfile().__dict__, "name": "off", "pen_offset_x": 30.0})
    area = pipeline.drawable_area(st.get("machines", "off"), MaterialProfile(width=200, height=200))
    assert area[0] == 30.0  # la pluma no alcanza X<30
    out = _plan(machine="off", layout={"scale_mode": "fit"})
    assert out.stats.out_of_bounds == 0


def test_multi_pen_single_file_and_per_pen():
    pen_map = {"#ff0000": "Sharpie fino", "#0000ff": "Fineliner 0.3"}
    single = _plan(pen_map=pen_map)
    assert len(single.files) == 1
    assert single.files[0].text.count("M0 ") >= 3  # insertar + (retirar + insertar) por cambio
    per = _plan(pen_map=pen_map, per_pen=True)
    assert len(per.files) == len(single.plan.jobs) == 3
    assert all("G28" in f.text for f in per.files)


def test_omit_group():
    out = _plan(pen_map={"#ff0000": ""})
    assert all("#ff0000" not in j.label for j in out.plan.jobs)


def test_klipper_flavor():
    st = ProfileStore()
    out = job.run(importers.load(str(DATA / "sample.svg")),
                  {"machine": "Genérica Klipper 220", "default_pen": "Fineliner 0.5"}, st)
    text = out.files[0].text
    assert "PAUSE" in text and "M84 S0" not in text


def test_fixed_contact_mode():
    m = MachineProfile(contact_mode="fixed", contact_z_fixed=2.0)
    mat = MaterialProfile(thickness=3.0)
    w = gcode.Writer(m, mat)
    assert w.z_contact == pytest.approx(5.0)
    pen = PenProfile()
    files, _ = gcode.generate([gcode.PenJob(pen, [np.array([[50, 50], [60, 60]])])], m, mat)
    assert "M0" not in files[0].text  # una sola pluma montada: sin pausa


def test_layout_fit_inside_area():
    out = _plan(layout={"scale_mode": "fit", "rotate": 90})
    a = out.plan.drawable
    b = out.plan.design_bounds
    assert b[0] >= a[0] - 1e-6 and b[2] <= a[2] + 1e-6 and b[1] >= a[1] - 1e-6 and b[3] <= a[3] + 1e-6


def test_calibration_pattern():
    m, mat, pen = MachineProfile(), MaterialProfile(), PenProfile()
    pj = calibration.pattern(pen, pipeline.drawable_area(m, mat))
    files, stats = gcode.generate([pj], m, mat, "cal")
    assert stats.out_of_bounds == 0 and stats.draw_mm > 500


def test_ascii_messages():
    assert gcode.ascii_msg("Bolígrafo ñandú; (x)", 40) == "Boligrafo nandu x"


# --- servidor -------------------------------------------------------------

def test_server_roundtrip():
    from fastapi.testclient import TestClient
    from trazo.server import app
    c = TestClient(app)
    meta = c.get("/api/meta").json()
    assert meta["profiles"]["machines"]
    with open(DATA / "sample.dxf", "rb") as fh:
        up = c.post("/api/upload", files={"file": ("sample.dxf", fh)}).json()
    res = c.post("/api/plan", json={"file_id": up["file_id"], "settings": {"group_by": "layer"}}).json()
    assert {g["key"] for g in res["groups"]} >= {"CORTE", "GRABADO"}
    r = c.post("/api/gcode", json={"file_id": up["file_id"], "settings": {"per_pen": False}})
    assert r.status_code == 200 and r.text.startswith("; Generado por Trazo")
    r = c.put("/api/profiles/pens", json={"name": "Mi pluma", "tip": 0.42})
    assert r.status_code == 200
    assert any(p["name"] == "Mi pluma" for p in c.get("/api/meta").json()["profiles"]["pens"])
    bad = c.post("/api/upload", files={"file": ("x.pdf", b"%PDF")})
    assert bad.status_code == 400
