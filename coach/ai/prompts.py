"""Instrucciones para la IA: análisis del parche, resumen del meta y consejos en partida.

Los esquemas JSON cumplen las reglas de salida estricta de Claude y OpenAI: additionalProperties false y
todas las propiedades en 'required'.
"""
LANG_NAMES = {"es": "Spanish (Spain)", "es-419": "Latin American Spanish", "en": "English"}


def _lang(lang: str) -> str:
    return LANG_NAMES.get(lang, lang)


# ---------- análisis de notas de parche ----------
PATCH_REVIEW_SCHEMA = {
    "type": "object",
    "properties": {
        "entries": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "target": {"type": "string"},
                    "kind": {"type": "string", "enum": ["hero", "item"]},
                    "verdict": {"type": "string", "enum": ["buff", "nerf", "mixed", "rework", "neutral"]},
                    "impact": {"type": "integer", "enum": [1, 2, 3]},
                    "summary": {"type": "string"},
                },
                "required": ["target", "kind", "verdict", "impact", "summary"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["entries"],
    "additionalProperties": False,
}


def patch_review_prompt(patch: str, blocks: str, lang: str) -> tuple[str, str]:
    system = f"""You are a Dota 2 analyst reading the official patch notes of patch {patch}.
For every hero or item section you receive, judge the overall effect of its changes on its strength in public matches:
- verdict: buff, nerf, mixed (clear ups and downs), rework (the way it is played changes) or neutral (no real impact).
- impact: 1 minor, 2 noticeable, 3 big.
- summary: one short sentence in {_lang(lang)} for a player, naming the change that matters most and how it affects the way the hero/item is played or countered. Keep hero, item and ability names in English.
Base your judgement only on the notes given. Do not invent numbers or changes. Use the exact target name from the section header."""
    user = f"Patch notes, grouped by hero/item:\n\n{blocks}"
    return system, user


# ---------- resumen del meta ----------
def meta_brief_prompt(stats_brief: str, general_changes: list, lang: str) -> tuple[str, str]:
    general = "\n".join(f"- {c.detail}: {c.text}" for c in general_changes)
    system = f"""You are a Dota 2 coach explaining the current meta to a low/mid-rank player, in {_lang(lang)}.
Use only the data given: hero win rates from public matches, their recent trend, and the patch notes analysis.
Write at most 10 short bullet points:
- which heroes are strong right now and why (link a buff in the notes to a rising win rate when both appear),
- which popular heroes got weaker,
- the general mechanic changes that change how to play (gold, experience, map, items),
- 2-3 practical tips for climbing this patch.
Say when something is uncertain (for example a small sample or a trend without patch changes behind it). Keep hero and item names in English."""
    user = f"Current meta data:\n{stats_brief}\n\nGeneral patch changes:\n{general or '(none)'}"
    return system, user


# ---------- consejos en partida ----------
TIPS_SCHEMA = {
    "type": "object",
    "properties": {
        "tips": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "kind": {"type": "string", "enum": ["item", "counter", "play", "warning"]},
                    "text": {"type": "string"},
                },
                "required": ["kind", "text"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["tips"],
    "additionalProperties": False,
}


def tips_prompt(context: str, lang: str, max_tips: int) -> tuple[str, str]:
    system = f"""You are a Dota 2 coach speaking to the player during a live match, in {_lang(lang)}.
Give at most {max_tips} tips, each under 20 words, that the player can act on in the next minute or two.
Priorities: what to buy next with the current gold, items that counter the enemy heroes, how this patch's changes affect the matchup, and simple play advice for the current game time.
Prefer the candidate items listed in the context; you may suggest another item only if it clearly fits better. Never suggest an item the player already owns.
Use only the information given. If the game state is unclear, give fewer tips. Keep hero, item and ability names in English. Never repeat a tip listed under "recent tips"."""
    return system, context


def draft_prompt(context: str, lang: str) -> tuple[str, str]:
    system = f"""You are a Dota 2 draft coach, writing in {_lang(lang)} for a low/mid-rank player.
From the candidate heroes (already scored by matchup data and current meta), recommend the best 3 for the player's role, explaining for each in one or two sentences why it works against the enemy heroes and how the current patch affects it. Then give a short starting-items and first-items plan for your top pick.
Use only the data given. Keep hero, item and ability names in English. Be concise."""
    return system, context


REVIEW_SCHEMA = {
    "type": "object",
    "properties": {
        "notes": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["notes"],
    "additionalProperties": False,
}


def review_prompt(report: str, lang: str) -> tuple[str, str]:
    """Resumen después de la partida: los 3 errores o mejoras más importantes."""
    system = f"""You are a Dota 2 coach reviewing a match the player just finished, writing in {_lang(lang)}.
Give exactly 3 short, concrete notes (under 30 words each): the most important mistakes or things to improve next game, using only the data given (deaths with time, map zone and visible enemies; item timings; percentiles against other players of the same hero; lane and game info). Mention one thing that went well only if the data clearly shows it. Keep hero and item names in English."""
    return system, report


def lane_prompt(context: str, lang: str) -> tuple[str, str]:
    """Consejos para la fase de líneas de una combinación concreta (tú + compañero contra sus rivales)."""
    system = f"""You are a Dota 2 laning coach, writing in {_lang(lang)} for a low/mid-rank player during the laning stage.
Give exactly 3 short, concrete tips (under 22 words each) for this exact lane: how the player and their lane partner should trade, when they can try a kill (e.g. at level 2/3/6), what to fear from each opponent and when to back off. Use the matchup data given. Keep hero, ability and item names in English."""
    return system, context
