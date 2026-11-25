"""Actualización con cada parche: al abrir la aplicación se mira el último parche publicado por Valve y, si es
nuevo, se borra de la caché todo lo que depende de él (héroes, objetos, recetas, costes, habilidades, talentos,
estadísticas de OpenDota y STRATZ, referencias...) para que se vuelva a descargar. Las partidas sueltas de OpenDota
no cambian y se conservan.
"""
import logging
import os
import time
from dataclasses import dataclass, field

import requests

from .. import config
from .cache import read_cached, write_cached

log = logging.getLogger(__name__)

PATCH_LIST_URL = "https://www.dota2.com/datafeed/patchnoteslist"
MARKER = "patch_marker"
# Lo que depende del parche (prefijos de los archivos de caché). No se borran: od_match_* (partidas cerradas),
# valve_patch_<versión> antiguos (las notas de un parche no cambian), plantillas e imágenes.
PATCH_DEPENDENT = ("valve_herolist", "valve_itemlist", "valve_abilitylist", "valve_itemcosts", "valve_herodata_",
                   "valve_patchlist", "od_const_", "od_herostats", "od_itempop_", "od_matchups_", "od_synergy_",
                   "od_bench_", "od_find_", "stratz_")


@dataclass
class UpdateResult:
    latest: str = ""             # último parche publicado (p. ej. 7.43)
    previous: str = ""           # el que había la última vez ("" la primera vez)
    new_patch: bool = False
    cleared: int = 0             # archivos de caché borrados
    missing_traits: list[str] = field(default_factory=list)   # héroes sin rasgos en hero_traits.json
    error: str = ""

    def message(self) -> str:
        if self.error:
            return f"No se pudo comprobar el parche ({self.error}): uso los datos guardados"
        if self.new_patch:
            msg = f"Nuevo parche {self.latest}: datos actualizados"
        else:
            msg = f"Parche {self.latest} · datos al día"
        if self.missing_traits:
            msg += f" · héroes sin rasgos: {', '.join(self.missing_traits)}"
        return msg


def latest_patch(timeout: float = 10.0) -> str:
    """Último parche publicado (siempre se pregunta a Valve: es una petición pequeña)."""
    r = requests.get(PATCH_LIST_URL, params={"language": "english"}, timeout=timeout)
    r.raise_for_status()
    patches = sorted(r.json().get("patches") or [], key=lambda p: p.get("patch_timestamp", 0))
    if not patches:
        raise ValueError("lista de parches vacía")
    return str(patches[-1]["patch_number"])


def clear_patch_cache() -> int:
    folder = config.CACHE_DIR
    if not folder.exists():
        return 0
    n = 0
    for f in folder.glob("*.json"):
        if f.stem.startswith(PATCH_DEPENDENT):
            try:
                f.unlink()
                n += 1
            except OSError:
                log.warning("no se pudo borrar %s", f)
    return n


def heroes_without_traits(gd) -> list[str]:
    from ..engine.counters import TRAITS
    return sorted(h.loc for h in gd.heroes.values() if h.loc not in TRAITS)


def check(fetch=latest_patch) -> UpdateResult:
    """Comprueba el parche y, si es nuevo, invalida la caché. Nunca lanza: sin red se sigue con lo guardado."""
    res = UpdateResult()
    if os.environ.get("COACH_OFFLINE"):
        res.error = "modo sin red"
        return res
    hit = read_cached(MARKER)
    res.previous = (hit[1] or {}).get("patch", "") if hit else ""
    try:
        res.latest = fetch()
    except Exception as e:
        res.error, res.latest = str(e)[:120], res.previous
        log.warning("no se pudo comprobar el parche: %s", e)
        return res
    if res.latest != res.previous:
        res.new_patch = bool(res.previous)
        if res.previous:  # la primera vez solo se apunta (la caché ya es de este parche)
            res.cleared = clear_patch_cache()
            log.info("nuevo parche %s (antes %s): %d archivos de caché borrados", res.latest, res.previous, res.cleared)
        write_cached(MARKER, {"patch": res.latest, "checked": time.time()})
    return res


__all__ = ["UpdateResult", "check", "clear_patch_cache", "heroes_without_traits", "latest_patch"]
