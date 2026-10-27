"""Generación de G-code compatible con Marlin (1.x/2.x), Klipper y firmwares
tipo RepRap. Solo se usan comandos básicos: G0/G1/G4/G21/G28/G90, M0, M84,
M104/M140/M107 (apagar calefactores), M117 y M204 opcionales.

Nunca se mueve el extrusor ni se calienta nada.
"""
from __future__ import annotations

import math
import unicodedata
from dataclasses import dataclass, field

import numpy as np

from . import __version__
from .profiles import MachineProfile, MaterialProfile, PenProfile


@dataclass
class PenJob:
    pen: PenProfile
    paths: list[np.ndarray]          # coordenadas de cama (punta de la pluma)
    label: str = ""


@dataclass
class GcodeFile:
    name: str
    text: str
    pens: list[str]
    seconds: float


@dataclass
class Stats:
    draw_mm: float = 0.0
    travel_mm: float = 0.0
    lifts: int = 0
    seconds: float = 0.0
    out_of_bounds: int = 0
    per_pen: list[dict] = field(default_factory=list)


def ascii_msg(s: str, n: int) -> str:
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode()
    s = "".join(ch for ch in s if ch.isprintable() and ch not in ";()")
    return s[:n].strip()


def _move_time(d: float, v: float, a: float) -> float:
    """Trapecio simple: arranca y termina en reposo."""
    if d <= 0:
        return 0.0
    if a <= 0:
        return d / v
    if d >= v * v / a:
        return d / v + v / a
    return 2 * math.sqrt(d / a)


def path_time(p: np.ndarray, v: float, a: float, corner_deg: float = 50) -> float:
    if len(p) < 2:
        return 0.0
    seg = np.diff(p, axis=0)
    lens = np.hypot(*seg.T)
    if len(seg) == 1:
        return _move_time(float(lens[0]), v, a)
    u = seg / np.maximum(lens[:, None], 1e-9)
    cosang = np.clip((u[:-1] * u[1:]).sum(1), -1, 1)
    sharp = np.nonzero(cosang < math.cos(math.radians(corner_deg)))[0] + 1
    t = 0.0
    for run in np.split(lens, sharp):
        t += _move_time(float(run.sum()), v, a)
    return t


class Writer:
    def __init__(self, m: MachineProfile, mat: MaterialProfile):
        self.m, self.mat = m, mat
        if m.contact_mode == "fixed":
            self.z_contact = m.contact_z_fixed + mat.thickness
        else:
            self.z_contact = mat.thickness + m.nozzle_clearance
        self.z_up = self.z_contact + m.pen_lift
        self.z_safe = min(self.z_contact + m.safe_z_lift, m.z_max)
        self.lines: list[str] = []
        self.oob = 0
        self.cur_z: float | None = None
        self.cur_xy: tuple[float, float] | None = None

    # -- utilidades --
    def f(self, v: float) -> str:
        s = f"{v:.{self.m.decimals}f}".rstrip("0").rstrip(".")
        return "0" if s in ("-0", "") else s

    def z_down(self, pen: PenProfile) -> float:
        press = pen.press if pen.press is not None else self.m.pen_press
        return max(self.z_contact - press, 0.0)

    def xy(self, p) -> tuple[float, float]:
        x, y = p[0] - self.m.pen_offset_x, p[1] - self.m.pen_offset_y
        eps = 1e-6
        if not (self.m.x_min - eps <= x <= self.m.x_max + eps and self.m.y_min - eps <= y <= self.m.y_max + eps):
            self.oob += 1
            x = min(max(x, self.m.x_min), self.m.x_max)
            y = min(max(y, self.m.y_min), self.m.y_max)
        return x, y

    def emit(self, s: str):
        self.lines.append(s)

    def msg(self, text: str):
        if self.m.message_cmd:
            self.emit(self.m.message_cmd.replace("{msg}", ascii_msg(text, self.m.max_message_len)))

    def pause(self, text: str):
        self.emit(f"; >>> PAUSA: {ascii_msg(text, 200)}")
        self.msg(text)
        if self.m.pause_cmd:
            self.emit(self.m.pause_cmd.replace("{msg}", ascii_msg(text, self.m.max_message_len)))

    def travel(self, p):
        x, y = self.xy(p)
        if self.cur_xy is not None and abs(self.cur_xy[0] - x) < 1e-4 and abs(self.cur_xy[1] - y) < 1e-4:
            return
        self.emit(f"G0 X{self.f(x)} Y{self.f(y)} F{self.f(self.m.travel_feed)}")
        self.cur_xy = (x, y)

    def z(self, z: float, g: str = "G0"):
        if self.cur_z is not None and abs(self.cur_z - z) < 1e-4:
            return
        self.emit(f"{g} Z{self.f(z)} F{self.f(self.m.z_feed)}")
        self.cur_z = z

    # -- bloques --
    def header(self, title: str, jobs: list[PenJob], seconds: float):
        m = self.m
        e = self.emit
        e(f"; Generado por Trazo {__version__} - plotter de pluma")
        e(f"; Archivo: {title}")
        e(f"; Maquina: {m.name} ({m.flavor})  Material: {self.mat.name} {self.f(self.mat.thickness)} mm")
        for j in jobs:
            e(f"; Pluma: {j.pen.name}  punta {self.f(j.pen.tip)} mm  capa: {j.label}")
        e(f"; Z contacto {self.f(self.z_contact)}  arriba {self.f(self.z_up)}  seguro {self.f(self.z_safe)}")
        e(f"; Tiempo estimado: {format_time(seconds)}")
        e("G21 ; milimetros")
        e("G90 ; coordenadas absolutas")
        if m.disable_heaters:
            e("M104 S0 ; boquilla apagada")
            e("M140 S0 ; cama apagada")
            e("M107 ; ventilador apagado")
        if m.flavor != "klipper":
            e("M84 S0 ; no apagar motores por inactividad durante pausas")
        if m.acceleration and m.acceleration > 0:
            e(f"M204 S{self.f(m.acceleration)}")
        if m.start_gcode.strip():
            e("; --- inicio personalizado ---")
            self.lines += m.start_gcode.strip().splitlines()
        if m.home == "all":
            e("G28 ; home (sin pluma insertada en modo 'insert')")
        elif m.home == "xy":
            e("G28 X Y")
        self.cur_z = None
        self.z(self.z_safe)

    def load_pen(self, job: PenJob, first: bool):
        """Colocar la pluma antes de dibujar con ella."""
        start = job.paths[0][0] if job.paths and len(job.paths[0]) else (self.m.park_x, self.m.park_y)
        if self.m.contact_mode == "insert":
            self.z(self.z_safe)
            if not first:  # retirar la anterior arriba, para no manchar al bajar
                self.pause("Retire la pluma")
            # sobre el primer punto del dibujo, a la altura de contacto
            self.travel(start)
            self.z(self.z_contact)
            self.emit(f"; Inserte '{ascii_msg(job.pen.name, 60)}' hasta tocar la superficie, apriete y continue")
            self.pause(f"Pluma: {job.pen.name}")
            self.z(self.z_up)
        else:
            if not first:
                self.z(self.z_safe)
                self.emit(f"G0 X{self.f(self.m.park_x)} Y{self.f(self.m.park_y)} F{self.f(self.m.travel_feed)}")
                self.cur_xy = (self.m.park_x, self.m.park_y)
                self.pause(f"Pluma: {job.pen.name}")
            self.z(self.z_up)

    def body(self, job: PenJob):
        pen = job.pen
        feed = pen.draw_feed * self.mat.speed_factor
        zd = self.z_down(pen)
        self.msg(f"Dibujando {pen.name}")
        self.emit(f"; --- pluma: {pen.name} ({len(job.paths)} trazos) ---")
        for p in job.paths:
            if len(p) == 0:
                continue
            self.travel(p[0])
            self.z(zd, "G1")
            if pen.dwell_ms > 0:
                self.emit(f"G4 P{int(pen.dwell_ms)}")
            first = True
            for q in p[1:]:
                x, y = self.xy(q)
                if first:
                    self.emit(f"G1 X{self.f(x)} Y{self.f(y)} F{self.f(feed)}")
                    first = False
                else:
                    self.emit(f"G1 X{self.f(x)} Y{self.f(y)}")
                self.cur_xy = (x, y)
            self.z(self.z_up, "G1")

    def footer(self):
        m = self.m
        self.z(self.z_safe)
        self.emit(f"G0 X{self.f(m.park_x)} Y{self.f(m.park_y)} F{self.f(m.travel_feed)}")
        self.cur_xy = (m.park_x, m.park_y)
        if m.end_gcode.strip():
            self.emit("; --- final personalizado ---")
            self.lines += m.end_gcode.strip().splitlines()
        self.msg("Dibujo terminado")
        self.emit("M84 ; motores apagados")
        self.emit("; fin")

    def text(self) -> str:
        return "\n".join(self.lines) + "\n"


def estimate(job: PenJob, m: MachineProfile, mat: MaterialProfile, start=(0.0, 0.0)) -> dict:
    v = job.pen.draw_feed * mat.speed_factor / 60.0
    vt = m.travel_feed / 60.0
    vz = m.z_feed / 60.0
    a = m.acceleration if m.acceleration > 0 else 1000.0
    press = job.pen.press if job.pen.press is not None else m.pen_press
    dz = m.pen_lift + press
    pos = np.asarray(start, float)
    t = draw = travel = 0.0
    for p in job.paths:
        if not len(p):
            continue
        d = float(np.hypot(*(p[0] - pos)))
        travel += d
        t += _move_time(d, vt, a) + 2 * dz / vz + job.pen.dwell_ms / 1000.0
        t += path_time(p, v, a)
        if len(p) > 1:
            draw += float(np.hypot(*np.diff(p, axis=0).T).sum())
        pos = p[-1]
    return {"pen": job.pen.name, "label": job.label, "paths": len(job.paths),
            "draw_mm": draw, "travel_mm": travel, "lifts": len(job.paths), "seconds": t}


def format_time(s: float) -> str:
    s = int(round(s))
    h, r = divmod(s, 3600)
    mi, se = divmod(r, 60)
    return f"{h} h {mi:02d} min" if h else f"{mi} min {se:02d} s"


def generate(jobs: list[PenJob], m: MachineProfile, mat: MaterialProfile, title: str = "dibujo",
             per_pen: bool = False) -> tuple[list[GcodeFile], Stats]:
    jobs = [j for j in jobs if j.paths]
    stats = Stats()
    park = (m.park_x + m.pen_offset_x, m.park_y + m.pen_offset_y)
    est = [estimate(j, m, mat, park) for j in jobs]
    stats.per_pen = est
    stats.draw_mm = sum(e["draw_mm"] for e in est)
    stats.travel_mm = sum(e["travel_mm"] for e in est)
    stats.lifts = sum(e["lifts"] for e in est)
    stats.seconds = sum(e["seconds"] for e in est)
    files: list[GcodeFile] = []
    if not jobs:
        return files, stats

    groups = [[j] for j in jobs] if per_pen else [jobs]
    for gi, group in enumerate(groups):
        w = Writer(m, mat)
        secs = sum(estimate(j, m, mat, park)["seconds"] for j in group)
        w.header(title, group, secs)
        for k, job in enumerate(group):
            w.load_pen(job, first=(k == 0))
            w.body(job)
        w.footer()
        stats.out_of_bounds += w.oob
        if per_pen:
            name = f"{title}_{gi + 1:02d}_{_slug(group[0].pen.name)}.gcode"
        else:
            name = f"{title}.gcode"
        files.append(GcodeFile(name, w.text(), [j.pen.name for j in group], secs))
    return files, stats


def _slug(s: str) -> str:
    s = ascii_msg(s, 60)
    return "".join(c if c.isalnum() else "_" for c in s).strip("_") or "pluma"
