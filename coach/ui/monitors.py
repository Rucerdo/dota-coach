"""Monitores de Windows: el panel se abre maximizado en la pantalla secundaria si la hay (el juego va en la
principal); si solo hay una, en la principal."""
import ctypes
import ctypes.wintypes as wt
from dataclasses import dataclass

MONITORINFOF_PRIMARY = 1


@dataclass
class Monitor:
    x: int
    y: int
    width: int
    height: int     # área de trabajo (sin la barra de tareas)
    primary: bool

    @property
    def geometry(self) -> str:
        return f"{self.width}x{self.height}+{self.x}+{self.y}"


class _MONITORINFO(ctypes.Structure):
    _fields_ = [("cbSize", wt.DWORD), ("rcMonitor", wt.RECT), ("rcWork", wt.RECT), ("dwFlags", wt.DWORD)]


def list_monitors() -> list[Monitor]:
    out: list[Monitor] = []
    try:
        user32 = ctypes.windll.user32
    except AttributeError:
        return out
    proc = ctypes.WINFUNCTYPE(ctypes.c_int, wt.HMONITOR, wt.HDC, ctypes.POINTER(wt.RECT), wt.LPARAM)

    def callback(hmon, _hdc, _rect, _data):
        info = _MONITORINFO()
        info.cbSize = ctypes.sizeof(_MONITORINFO)
        if user32.GetMonitorInfoW(hmon, ctypes.byref(info)):
            r = info.rcWork
            out.append(Monitor(r.left, r.top, r.right - r.left, r.bottom - r.top,
                               bool(info.dwFlags & MONITORINFOF_PRIMARY)))
        return 1
    user32.EnumDisplayMonitors(None, None, proc(callback), 0)
    return out


def preferred_monitor(monitors: list[Monitor]) -> Monitor | None:
    """La secundaria más grande si hay; si no, la principal."""
    secondary = [m for m in monitors if not m.primary]
    if secondary:
        return max(secondary, key=lambda m: m.width * m.height)
    return next((m for m in monitors if m.primary), monitors[0] if monitors else None)
