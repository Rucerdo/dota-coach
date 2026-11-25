"""Rutas, configuración por defecto y persistencia.

Todo vive en %APPDATA%/DotaCoach salvo que se defina COACH_HOME (lo usan los tests para no tocar
la configuración real).
"""
import copy
import json
import os
from pathlib import Path

APP_DIR = Path(os.environ.get("COACH_HOME") or Path(os.environ.get("APPDATA") or Path.home()) / "DotaCoach")
CONFIG_PATH = APP_DIR / "config.json"
CACHE_DIR = APP_DIR / "cache"
LOG_PATH = APP_DIR / "coach.log"

DEFAULTS = {
    "gsi_port": 53124,          # el traductor usa 53123: pueden convivir
    "dota_dir": "",
    "lang": "es",
    "role": "auto",             # auto | carry | core | support
    "rank_bracket": 0,          # 0 = todos; 1 Herald, 2 Guardian, ... 8 Immortal (para el meta de OpenDota)
    "ai": {
        "provider": "none",     # none | claude | openai | gemini | groq | openrouter | deepseek | custom
        "model": "",            # vacío = el modelo por defecto del proveedor
        "base_url": "",         # solo 'custom' (Ollama, LM Studio...)
        "keys_enc": {},         # {proveedor: clave cifrada con DPAPI}
    },
    "advisor": {
        "min_seconds_between_ai": 45,
        "periodic_minutes": 8,
        "max_tips": 2,
    },
    "vision": True,             # reconocer los héroes de la barra superior (experimental)
    "topbar": {},               # ajustes finos de la barra superior (mismas claves que el traductor)
    "tts": False,               # leer los consejos en voz alta (voz de Windows)
    "overlay": {
        "x_frac": 0.70,
        "y_frac": 0.12,
        "width_frac": 0.28,
        "max_lines": 4,
        "line_seconds": 20,
        "font_family": "Segoe UI",
        "font_size": 13,
    },
}


def _merge(base: dict, over: dict) -> dict:
    out = copy.deepcopy(base)
    for k, v in (over or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _merge(out[k], v)
        else:
            out[k] = v
    return out


def load() -> dict:
    APP_DIR.mkdir(parents=True, exist_ok=True)
    try:
        saved = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        saved = {}
    return _merge(DEFAULTS, saved)


def save(cfg: dict):
    APP_DIR.mkdir(parents=True, exist_ok=True)
    tmp = CONFIG_PATH.with_suffix(".tmp")
    tmp.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(CONFIG_PATH)
