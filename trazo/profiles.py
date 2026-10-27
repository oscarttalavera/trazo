"""Perfiles de máquina, pluma y material, con persistencia en JSON.

Los perfiles del usuario se guardan en:
  - Windows: %APPDATA%\\Trazo\\profiles.json
  - Otros:   ~/.config/trazo/profiles.json
Se puede cambiar con la variable de entorno TRAZO_HOME.
"""
from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, fields
from pathlib import Path


@dataclass
class MachineProfile:
    name: str = "Ender 3 V1"
    flavor: str = "marlin"            # marlin | klipper | generic
    # Recorrido válido de la BOQUILLA (coordenadas de máquina, mm)
    x_min: float = 0.0
    x_max: float = 220.0
    y_min: float = 0.0
    y_max: float = 220.0
    z_max: float = 250.0
    # Posición de la punta de la pluma respecto a la boquilla (mm).
    # Ej.: pluma 35 mm a la derecha y 5 mm al frente -> (35, -5)
    pen_offset_x: float = 0.0
    pen_offset_y: float = 0.0
    travel_feed: float = 6000.0      # mm/min, desplazamientos con pluma arriba
    z_feed: float = 300.0            # mm/min (Ender 3 stock: 5 mm/s)
    acceleration: float = 500.0      # mm/s², 0 = no enviar M204
    home: str = "all"                # all | xy | none
    # Modo de contacto:
    #  insert: tras el home, la máquina baja a la altura de contacto y pausa
    #          para insertar la pluma tocando la superficie (recomendado).
    #  fixed:  la pluma ya está montada; contact_z_fixed es la Z a la que la
    #          punta toca la cama vacía (se suma el grosor del material).
    contact_mode: str = "insert"
    nozzle_clearance: float = 4.0    # (insert) boquilla sobre la superficie al tocar la punta
    contact_z_fixed: float = 2.0     # (fixed)
    pen_lift: float = 1.5            # mm sobre el contacto al viajar
    pen_press: float = 0.5           # mm bajo el contacto al dibujar (compresión del resorte)
    safe_z_lift: float = 15.0        # mm sobre el contacto para inicio/fin/cambio
    park_x: float = 0.0              # posición para cambios de pluma y final
    park_y: float = 200.0
    pause_cmd: str = "M0 {msg}"      # Klipper: "PAUSE"
    message_cmd: str = "M117 {msg}"  # vacío para no enviar mensajes
    disable_heaters: bool = True
    max_message_len: int = 20         # LCD 20x4
    start_gcode: str = ""
    end_gcode: str = ""
    decimals: int = 3


@dataclass
class PenProfile:
    name: str = "Fineliner 0.5"
    tip: float = 0.5                 # diámetro efectivo de la línea (mm)
    color: str = "#000000"           # color para la vista previa
    draw_feed: float = 1800.0        # mm/min
    overlap: float = 0.15            # traslape entre pasadas de relleno (0-0.9)
    dwell_ms: int = 0                # espera tras bajar la pluma
    press: float | None = None       # sustituye pen_press de la máquina


@dataclass
class MaterialProfile:
    name: str = "Bond media carta"
    width: float = 140.0
    height: float = 216.0
    thickness: float = 0.1
    # Esquina inferior izquierda del material sobre la cama (coords. de cama)
    origin_x: float = 0.0
    origin_y: float = 0.0
    margin: float = 8.0
    speed_factor: float = 1.0        # multiplica la velocidad de dibujo


KINDS = {"machines": MachineProfile, "pens": PenProfile, "materials": MaterialProfile}


BUILTIN = {
    "machines": [
        MachineProfile(),
        MachineProfile(name="Ender 3 V2 / Pro", x_max=230, y_max=230),
        MachineProfile(name="Ender 5", x_max=220, y_max=220, z_max=300),
        MachineProfile(name="Ender 5 Plus", x_max=350, y_max=350, z_max=400, park_y=340),
        MachineProfile(name="TwoTrees Bluer", x_max=235, y_max=235, z_max=280),
        MachineProfile(name="Tronxy X5SA", x_max=330, y_max=330, z_max=400, park_y=320),
        MachineProfile(name="Anet A8", x_max=220, y_max=220, z_max=240, z_feed=240,
                       acceleration=0, travel_feed=4800),
        MachineProfile(name="Genérica Klipper 220", flavor="klipper", pause_cmd="PAUSE",
                       message_cmd="M117 {msg}", max_message_len=40),
    ],
    "pens": [
        PenProfile(name="Ultrafino 0.1", tip=0.15, draw_feed=1200),
        PenProfile(name="Fineliner 0.3", tip=0.3, draw_feed=1500),
        PenProfile(name="Fineliner 0.5", tip=0.5),
        PenProfile(name="Bolígrafo 0.7", tip=0.4, draw_feed=1800, dwell_ms=0, press=0.8),
        PenProfile(name="Sharpie ultrafino", tip=0.6, draw_feed=2400),
        PenProfile(name="Sharpie fino", tip=1.0, draw_feed=2400, overlap=0.2),
        PenProfile(name="Marcador mediano 2 mm", tip=2.0, draw_feed=2400, overlap=0.2),
    ],
    "materials": [
        MaterialProfile(),
        MaterialProfile(name="Bond A5", width=148, height=210),
        MaterialProfile(name="Bond carta (parcial)", width=216, height=279),
        MaterialProfile(name="Cartulina 200x200", width=200, height=200, thickness=0.3),
        MaterialProfile(name="Cartón 2 mm", width=200, height=200, thickness=2.0, speed_factor=0.8),
        MaterialProfile(name="MDF 3 mm", width=200, height=200, thickness=3.0, speed_factor=0.7),
        MaterialProfile(name="Acrílico 3 mm", width=200, height=200, thickness=3.0, speed_factor=0.8),
    ],
}


def profiles_path() -> Path:
    base = os.environ.get("TRAZO_HOME")
    if base:
        root = Path(base)
    elif os.name == "nt":
        root = Path(os.environ.get("APPDATA", Path.home())) / "Trazo"
    else:
        root = Path.home() / ".config" / "trazo"
    return root / "profiles.json"


def from_dict(cls, d: dict):
    names = {f.name for f in fields(cls)}
    obj = cls()
    for k, v in d.items():
        if k in names:
            setattr(obj, k, v)
    return obj


class ProfileStore:
    """Perfiles integrados + perfiles del usuario (los del usuario ganan)."""

    def __init__(self, path: Path | None = None, data: dict | None = None):
        """Con `data` ({tipo: [perfiles]}) trabaja en memoria, sin archivo (versión web)."""
        self.memory = data is not None
        self.path = None if self.memory else (path or profiles_path())
        self.user: dict[str, dict[str, dict]] = {k: {} for k in KINDS}
        if self.memory:
            for k in KINDS:
                for d in data.get(k, []) or []:
                    if isinstance(d, dict) and d.get("name"):
                        self.user[k][d["name"]] = asdict(from_dict(KINDS[k], d))
        elif self.path.exists():
            try:
                data = json.loads(self.path.read_text(encoding="utf-8"))
                for k in KINDS:
                    self.user[k] = {d["name"]: d for d in data.get(k, [])}
            except (ValueError, KeyError):
                pass

    def all(self, kind: str) -> list:
        cls = KINDS[kind]
        out = {p.name: p for p in BUILTIN[kind]}
        for name, d in self.user[kind].items():
            out[name] = from_dict(cls, d)
        return list(out.values())

    def get(self, kind: str, name: str | None):
        items = self.all(kind)
        for p in items:
            if p.name == name:
                return p
        if name:
            raise KeyError(f"Perfil '{name}' no encontrado en {kind}")
        return items[0]

    def is_builtin(self, kind: str, name: str) -> bool:
        return any(p.name == name for p in BUILTIN[kind])

    def save(self, kind: str, data: dict):
        obj = from_dict(KINDS[kind], data)
        self.user[kind][obj.name] = asdict(obj)
        self._write()
        return obj

    def delete(self, kind: str, name: str):
        self.user[kind].pop(name, None)
        self._write()

    def export(self) -> dict:
        return {k: list(v.values()) for k, v in self.user.items()}

    def _write(self):
        if self.memory:
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        data = {k: list(v.values()) for k, v in self.user.items()}
        self.path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


def to_dict(p) -> dict:
    return asdict(p)


# Etiquetas y ayuda para el editor de perfiles de la interfaz
FIELD_INFO = {
    "machines": {
        "name": ("Nombre", ""),
        "flavor": ("Firmware", "marlin | klipper | generic", ["marlin", "klipper", "generic"]),
        "x_min": ("X mínimo", "Recorrido de la boquilla (mm)"),
        "x_max": ("X máximo", ""),
        "y_min": ("Y mínimo", ""),
        "y_max": ("Y máximo", ""),
        "z_max": ("Z máximo", ""),
        "pen_offset_x": ("Offset pluma X", "Punta respecto a la boquilla; + = a la derecha"),
        "pen_offset_y": ("Offset pluma Y", "+ = hacia atrás (hacia el fondo de la cama)"),
        "travel_feed": ("Velocidad de viaje", "mm/min con la pluma arriba"),
        "z_feed": ("Velocidad Z", "mm/min (Ender 3 stock: 300)"),
        "acceleration": ("Aceleración", "mm/s² (M204); 0 = no cambiar"),
        "home": ("Home", "all = G28, xy = G28 X Y, none = sin home", ["all", "xy", "none"]),
        "contact_mode": ("Modo de contacto", "insert: pausa para insertar la pluma tocando la superficie; "
                         "fixed: pluma montada y altura calibrada", ["insert", "fixed"]),
        "nozzle_clearance": ("Holgura de boquilla", "(insert) altura de la boquilla sobre la superficie"),
        "contact_z_fixed": ("Z contacto (fixed)", "Z en la que la punta toca la cama vacía"),
        "pen_lift": ("Levantar pluma", "mm sobre el contacto al viajar"),
        "pen_press": ("Presión", "mm bajo el contacto al dibujar (compresión del resorte)"),
        "safe_z_lift": ("Z seguro", "mm sobre el contacto en inicio, fin y cambios"),
        "park_x": ("Estacionar X", "Posición de la boquilla para cambios y final"),
        "park_y": ("Estacionar Y", ""),
        "pause_cmd": ("Comando de pausa", "{msg} = mensaje. Marlin: M0 {msg}; Klipper: PAUSE"),
        "message_cmd": ("Comando de mensaje", "M117 {msg}; vacío = sin mensajes"),
        "disable_heaters": ("Apagar calefactores", "Envía M104 S0 / M140 S0 / M107 al inicio"),
        "max_message_len": ("Largo máx. mensaje", "Caracteres de la pantalla"),
        "start_gcode": ("G-code inicial extra", "Se inserta antes del home"),
        "end_gcode": ("G-code final extra", ""),
        "decimals": ("Decimales", ""),
    },
    "pens": {
        "name": ("Nombre", ""),
        "tip": ("Ancho de línea (mm)", "Ancho REAL medido en el papel (use la calibración)"),
        "color": ("Color", "Solo para la vista previa"),
        "draw_feed": ("Velocidad de dibujo", "mm/min"),
        "overlap": ("Traslape de relleno", "0-0.9; 0.15 = 15 %"),
        "dwell_ms": ("Espera al bajar (ms)", "Para plumas que tardan en soltar tinta"),
        "press": ("Presión propia (mm)", "Vacío = usar la de la máquina"),
    },
    "materials": {
        "name": ("Nombre", ""),
        "width": ("Ancho (mm)", ""),
        "height": ("Alto (mm)", ""),
        "thickness": ("Grosor (mm)", "Papel 0.1, cartón 2, MDF 3..."),
        "origin_x": ("Posición X", "Esquina inferior izquierda sobre la cama"),
        "origin_y": ("Posición Y", ""),
        "margin": ("Margen (mm)", ""),
        "speed_factor": ("Factor de velocidad", "Multiplica la velocidad de la pluma (madera < 1)"),
    },
}
