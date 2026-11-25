"""Abrir el coach solo cuando se abre Dota (y cerrarlo al cerrar Dota).

`coach autostart` se queda esperando en segundo plano: cuando aparece dota2.exe lanza el modo en directo y,
cuando Dota se cierra, cierra el coach (con su informe de la partida) y vuelve a esperar. Para que arranque al
iniciar sesión se añade una entrada en HKCU\\...\\Run (solo del usuario, sin permisos de administrador). Solo se
toca el registro cuando el usuario marca o desmarca la opción en los ajustes.
"""
import logging
import subprocess
import sys
import time
from pathlib import Path

log = logging.getLogger(__name__)

RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
VALUE_NAME = "DotaCoach"
ROOT = Path(__file__).resolve().parents[1]
CHECK_EVERY = 5.0


def dota_running() -> bool:
    try:
        out = subprocess.run(["tasklist", "/FI", "IMAGENAME eq dota2.exe", "/NH"], capture_output=True, text=True,
                             timeout=10, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0)).stdout
    except (OSError, subprocess.SubprocessError):
        return False
    return "dota2.exe" in out.lower()


def command(frozen: bool | None = None, executable: str | None = None) -> str:
    """Línea de órdenes que se registra para el arranque (sin consola cuando se puede)."""
    frozen = getattr(sys, "frozen", False) if frozen is None else frozen
    exe = Path(executable or sys.executable)
    if frozen:
        return f'"{exe}" autostart'
    pythonw = exe.with_name("pythonw.exe")
    return f'"{pythonw if pythonw.exists() else exe}" "{ROOT / "run.py"}" autostart'


def is_enabled() -> bool:
    import winreg
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as key:
            winreg.QueryValueEx(key, VALUE_NAME)
            return True
    except OSError:
        return False


def set_enabled(enabled: bool):
    import winreg
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE) as key:
        if enabled:
            winreg.SetValueEx(key, VALUE_NAME, 0, winreg.REG_SZ, command())
        else:
            try:
                winreg.DeleteValue(key, VALUE_NAME)
            except FileNotFoundError:
                pass


class DotaWatcher:
    """should_stop() para el modo en directo: True cuando Dota lleva cerrado dos comprobaciones seguidas."""

    def __init__(self, running=dota_running, every: float = CHECK_EVERY):
        self.running, self.every = running, every
        self.last_check = 0.0
        self.misses = 0

    def should_stop(self) -> bool:
        now = time.time()
        if now - self.last_check < self.every:
            return False
        self.last_check = now
        self.misses = 0 if self.running() else self.misses + 1
        return self.misses >= 2


def run_autostart(cfg_loader, start_live):
    """Bucle: espera a Dota → lanza el coach → al cerrarse Dota, vuelve a esperar."""
    log.info("arranque automático: esperando a que se abra Dota 2")
    while True:
        while not dota_running():
            time.sleep(CHECK_EVERY)
        log.info("Dota 2 abierto: arranco el coach")
        try:
            start_live(cfg_loader(), DotaWatcher().should_stop)
        except Exception:
            log.exception("el coach se cerró con un error")
        while dota_running():  # si se cerró el panel a mano, no reabrir hasta la próxima vez que se abra Dota
            time.sleep(CHECK_EVERY)
