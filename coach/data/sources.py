"""Elección de fuente de estadísticas: STRATZ primero (partidas públicas de tu rango), OpenDota de respaldo.

Las funciones devuelven el formato que espera engine/draft.py:
  matchups(hero_id) → [{hero_id, games_played, wins}]  (wins = victorias de hero_id contra cada rival)
  synergy(hero_id)  → [{hero_id, games, wins}]          (wins = victorias jugando juntos)
"""
import logging

from . import opendota, stratz

log = logging.getLogger(__name__)

MIN_STRATZ_ROWS = 20   # si STRATZ devuelve muy poco, mejor OpenDota


class Sources:
    def __init__(self, bracket: int = 0, use_stratz: bool = True):
        self.bracket, self.use_stratz = bracket, use_stratz and bool(stratz.token())
        self.last_source: dict[str, str] = {}   # "matchups"/"synergy" → "STRATZ" | "OpenDota"

    def _stratz(self, hero_id: int, kind: str) -> list[dict] | None:
        if not self.use_stratz:
            return None
        try:
            rows = stratz.matchup(hero_id, self.bracket)[kind]
        except Exception as e:  # cualquier fallo de STRATZ: respaldo
            log.warning("STRATZ (%s de %s) no disponible: %s; uso OpenDota", kind, hero_id, e)
            return None
        return rows if len(rows) >= MIN_STRATZ_ROWS else None

    def matchups(self, hero_id: int) -> list[dict]:
        rows = self._stratz(hero_id, "vs")
        if rows is not None:
            self.last_source["matchups"] = "STRATZ"
            return [{"hero_id": r["hero_id"], "games_played": r["games"], "wins": r["wins"]} for r in rows]
        self.last_source["matchups"] = "OpenDota"
        return opendota.matchups(hero_id)

    def popularity(self, hero_id: int) -> dict:
        """Lo que se compra con el héroe (STRATZ: tu rango, con minuto medio y winrate; si no, OpenDota)."""
        if self.use_stratz:
            try:
                data = stratz.item_popularity(hero_id, self.bracket)
                if data.get("_total", 0) >= 200:
                    self.last_source["items"] = "STRATZ"
                    return data
            except Exception as e:
                log.warning("STRATZ (objetos de %s) no disponible: %s; uso OpenDota", hero_id, e)
        self.last_source["items"] = "OpenDota"
        return opendota.item_popularity(hero_id)

    def synergy(self, hero_id: int) -> list[dict]:
        rows = self._stratz(hero_id, "with")
        if rows is not None:
            self.last_source["synergy"] = "STRATZ"
            return rows
        self.last_source["synergy"] = "OpenDota"
        return opendota.synergy(hero_id)
