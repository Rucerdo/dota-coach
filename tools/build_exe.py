"""Compila dist/DotaCoach.exe con PyInstaller (un solo archivo, sin consola).

Sin argumentos abre los ajustes; `DotaCoach.exe run` lanza el coach y `DotaCoach.exe autostart` espera a Dota
(lo usa la opción de arranque automático). Los datos (caché, informes, config) van a %APPDATA%\DotaCoach.

Uso:  python tools/build_exe.py
"""
from pathlib import Path

import PyInstaller.__main__

ROOT = Path(__file__).resolve().parent.parent

args = [
    str(ROOT / "run.py"),
    "--noconfirm", "--clean", "--onefile", "--windowed",
    "--name", "DotaCoach",
    "--add-data", f"{ROOT / 'coach' / 'engine' / 'hero_traits.json'};coach/engine",
    "--collect-data", "customtkinter",
    "--hidden-import", "comtypes.stream",
    "--collect-all", "winrt",          # OCR de Windows (paquetes de PyWinRT: módulos nativos por espacio de nombres)
    "--distpath", str(ROOT / "dist"),
    "--workpath", str(ROOT / "build"),
    "--specpath", str(ROOT / "build"),
]
PyInstaller.__main__.run(args)
print(f"Listo: {ROOT / 'dist' / 'DotaCoach.exe'}")
