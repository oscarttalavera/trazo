@echo off
rem Lanzador para Windows desde el código fuente (requiere Python 3.10+ instalado).
cd /d "%~dp0"
if not exist .venv (
  echo Creando entorno virtual e instalando dependencias, solo la primera vez...
  py -3 -m venv .venv || python -m venv .venv
  .venv\Scripts\python -m pip install --upgrade pip
  .venv\Scripts\python -m pip install -e .
)
.venv\Scripts\python -m trazo serve
pause
