@echo off
rem Construye dist\Trazo\Trazo.exe (carpeta portable) con PyInstaller.
cd /d "%~dp0"
if not exist .venv (
  py -3 -m venv .venv || python -m venv .venv
)
.venv\Scripts\python -m pip install --upgrade pip
.venv\Scripts\python -m pip install -e .[dev]
.venv\Scripts\pyinstaller --noconfirm --clean --name Trazo --console --icon docs\marca\trazo.ico ^
  --add-data "trazo\web;trazo\web" ^
  --collect-all skimage --collect-all HersheyFonts --collect-data ezdxf ^
  --collect-submodules uvicorn ^
  trazo\__main__.py
echo.
echo Listo: dist\Trazo\Trazo.exe  (comprima la carpeta dist\Trazo para distribuir)
pause
