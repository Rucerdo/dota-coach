"""Caché en disco de las APIs públicas (Valve datafeed, OpenDota).

Si no hay red, se devuelve la última copia aunque esté caducada: el coach sigue funcionando offline
con los datos del último parche descargado.
"""
import json
import logging
import re
import threading
import time
from pathlib import Path

import requests

from .. import config

log = logging.getLogger(__name__)

_session = requests.Session()
_session.headers["User-Agent"] = "DotaCoach/0.1"
_lock = threading.Lock()


class FetchError(Exception):
    """No hay red y tampoco copia en caché."""


def _path(name: str) -> Path:
    safe = re.sub(r"[^A-Za-z0-9_.-]", "_", name)
    return config.CACHE_DIR / f"{safe}.json"


def read_cached(name: str) -> tuple[float, object] | None:
    try:
        blob = json.loads(_path(name).read_text(encoding="utf-8"))
        return float(blob["fetched"]), blob["data"]
    except (OSError, ValueError, KeyError, TypeError):
        return None


def write_cached(name: str, data) -> None:
    p = _path(name)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps({"fetched": time.time(), "data": data}, ensure_ascii=False), encoding="utf-8")
    tmp.replace(p)


def cached_json(name: str, url: str, ttl: float, params: dict | None = None, timeout: float = 20.0):
    """JSON de 'url', guardado como 'name' durante 'ttl' segundos."""
    with _lock:
        hit = read_cached(name)
    if hit and time.time() - hit[0] < ttl:
        return hit[1]
    try:
        r = _session.get(url, params=params, timeout=timeout)
        r.raise_for_status()
        data = r.json()
    except (requests.RequestException, ValueError) as e:
        if hit:
            log.warning("sin red para %s (%s): uso la copia de hace %.0f h", name, e, (time.time() - hit[0]) / 3600)
            return hit[1]
        raise FetchError(f"no se pudo descargar {url}: {e}") from e
    with _lock:
        write_cached(name, data)
    return data


def download_file(url: str, dest: Path, timeout: float = 20.0) -> Path | None:
    if dest.exists():
        return dest
    try:
        r = _session.get(url, timeout=timeout)
        r.raise_for_status()
    except requests.RequestException as e:
        log.warning("no se pudo descargar %s: %s", url, e)
        return None
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(r.content)
    return dest
