"""Atajos globales con RegisterHotKey (API nativa de Windows).

NO hay gancho de teclado: Windows solo avisa a la app cuando se pulsa la combinación registrada;
el resto de teclas (Alt, Shift, habilidades...) ni pasan por la app y llegan al juego intactas.
(Copiado de dota-translator/app/winkeys.py.)
"""
import ctypes
import ctypes.wintypes as wt
import logging
import threading
from typing import Callable

log = logging.getLogger(__name__)
user32 = ctypes.WinDLL("user32", use_last_error=True)
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

WM_HOTKEY, WM_QUIT, WM_APP = 0x0312, 0x0012, 0x8000
MOD_ALT, MOD_CONTROL, MOD_SHIFT, MOD_WIN, MOD_NOREPEAT = 0x1, 0x2, 0x4, 0x8, 0x4000

_MODS = {"ctrl": MOD_CONTROL, "control": MOD_CONTROL, "alt": MOD_ALT, "shift": MOD_SHIFT, "win": MOD_WIN}
_NAMED = {"enter": 0x0D, "return": 0x0D, "space": 0x20, "tab": 0x09, "insert": 0x2D, "home": 0x24, "end": 0x23,
          "pageup": 0x21, "pagedown": 0x22, "pause": 0x13, **{f"f{i}": 0x6F + i for i in range(1, 25)}}


def parse(hotkey: str) -> tuple[int, int]:
    """'ctrl+shift+enter' → (MOD_CONTROL|MOD_SHIFT, VK_RETURN). ValueError si no se entiende."""
    parts = [p for p in hotkey.lower().replace(" ", "").split("+") if p]
    if not parts:
        raise ValueError("atajo vacío")
    *mods, key = parts
    flags = 0
    for m in mods:
        if m not in _MODS:
            raise ValueError(f"modificador desconocido: {m}")
        flags |= _MODS[m]
    if key in _NAMED:
        vk = _NAMED[key]
    elif len(key) == 1 and key.isalnum():
        vk = ord(key.upper())
    else:
        raise ValueError(f"tecla desconocida: {key}")
    return flags, vk


class GlobalHotkeys:
    """Registra atajos con RegisterHotKey en un hilo propio con su bucle de mensajes."""

    def __init__(self):
        self._thread: threading.Thread | None = None
        self._tid = 0
        self._wanted: dict[int, tuple[int, int]] = {}
        self._callbacks: dict[int, Callable[[], None]] = {}
        self._lock = threading.Lock()
        self.failed: list[str] = []  # atajos que Windows no dejó registrar (ya en uso por otro programa)
        self._names: dict[int, str] = {}

    def set(self, hotkeys: dict[str, tuple[str, Callable[[], None]]]):
        """{nombre: ('ctrl+enter', callback)}. Sustituye los atajos registrados."""
        wanted, callbacks, names = {}, {}, {}
        for i, (name, (combo, cb)) in enumerate(hotkeys.items(), start=1):
            try:
                wanted[i] = parse(combo)
                callbacks[i], names[i] = cb, f"{name} ({combo})"
            except ValueError as e:
                log.warning("atajo no válido %s: %s", combo, e)
        with self._lock:
            self._wanted, self._callbacks, self._names = wanted, callbacks, names
        if self._thread is None:
            ready = threading.Event()
            self._thread = threading.Thread(target=self._loop, args=(ready,), name="hotkeys", daemon=True)
            self._thread.start()
            ready.wait(3)
        else:
            user32.PostThreadMessageW(self._tid, WM_APP, 0, 0)  # re-registrar en su hilo

    def stop(self):
        if self._tid:
            user32.PostThreadMessageW(self._tid, WM_QUIT, 0, 0)
        self._thread = None

    def _register_all(self, registered: set):
        for hid in list(registered):
            user32.UnregisterHotKey(None, hid)
        registered.clear()
        self.failed = []
        with self._lock:
            wanted, names = dict(self._wanted), dict(self._names)
        for hid, (mods, vk) in wanted.items():
            if user32.RegisterHotKey(None, hid, mods | MOD_NOREPEAT, vk):
                registered.add(hid)
            else:
                self.failed.append(names[hid])
                log.warning("Windows no dejó registrar el atajo %s (¿lo usa otro programa?)", names[hid])

    def _loop(self, ready: threading.Event):
        self._tid = kernel32.GetCurrentThreadId()
        registered: set = set()
        msg = wt.MSG()
        user32.PeekMessageW(ctypes.byref(msg), None, 0, 0, 0)  # crea la cola de mensajes del hilo
        self._register_all(registered)
        ready.set()
        while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
            if msg.message == WM_HOTKEY:
                with self._lock:
                    cb = self._callbacks.get(msg.wParam)
                if cb:
                    try:
                        cb()
                    except Exception:
                        log.exception("error en un atajo")
            elif msg.message == WM_APP:
                self._register_all(registered)
        for hid in registered:
            user32.UnregisterHotKey(None, hid)
