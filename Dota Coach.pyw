"""Doble clic: abre los ajustes de Dota Coach sin ventana de consola (Windows abre los .pyw con pythonw).

Si Windows lo abre con otro Python (el del sistema, sin las dependencias), se relanza con el del proyecto
(.venv\\Scripts\\pythonw.exe).
"""
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
VENV_PYTHONW = ROOT / ".venv" / "Scripts" / "pythonw.exe"

if VENV_PYTHONW.exists() and Path(sys.executable).resolve().parent != VENV_PYTHONW.parent.resolve():
    subprocess.Popen([str(VENV_PYTHONW), str(Path(__file__).resolve())], cwd=str(ROOT),
                     creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    sys.exit(0)

sys.path.insert(0, str(ROOT))
from coach.cli import main  # noqa: E402

main([])
