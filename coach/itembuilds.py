"""Lleva la guía elegida a la tienda de Dota: escribe los objetos recomendados del héroe en
`game/dota/itembuilds/default_<héroe>.txt` (el formato de Valve: iniciales, early, mid, late y otros).

No compra nada: Dota solo los enseña en la tienda para comprarlos con un clic (o meterlos en la Compra rápida).
COMPROBADO (26-11-2026, Sniper): la tienda enseña lo escrito en lugar de los recomendados de Valve.

Antes de escribir la primera guía se copian TODAS las builds originales a `itembuilds_coach_backup/` (una vez; la
copia suelta `default_X.txt.coach_backup` de la primera prueba también va ahí, como original) y `restore` deja el
original de un héroe. Una actualización de Dota (o "verificar archivos" en Steam) las sobrescribe: el coach las
vuelve a escribir al elegir la guía.

El formato de Valve solo tiene grupos de objetos. El orden de habilidades y los talentos van como grupos cuyo título
es el texto (y un bloque AbilityBuild como el de las guías antiguas, por si Dota lo usa).
"""
import logging
import shutil
from pathlib import Path

log = logging.getLogger(__name__)

BACKUP_SUFFIX = ".coach_backup"   # copia suelta de la primera prueba (se pasa a la carpeta de copia)
BACKUP_DIR = "itembuilds_coach_backup"
GROUPS = [("start", "#DOTA_Item_Build_Starting_Items"), ("early", "#DOTA_Item_Build_Early_Game"),
          ("mid", "#DOTA_Item_Build_Mid_Items"), ("late", "#DOTA_Item_Build_Late_Items"),
          ("other", "#DOTA_Item_Build_Other_Items")]


def builds_dir(dota_dir: str | Path) -> Path:
    """dota_dir: la carpeta game/dota (la de los cfg de GSI)."""
    return Path(dota_dir) / "itembuilds"


def build_file(dota_dir, hero_name: str) -> Path:
    return builds_dir(dota_dir) / f"default_{hero_name.removeprefix('npc_dota_hero_')}.txt"


def _q(text: str) -> str:
    return str(text).replace('"', "'").replace("·", "|")


def render(hero_name: str, title: str, groups: dict[str, list[str]], skills: list[str] = (),
           ability_order: list[str] = ()) -> str:
    """skills: líneas de texto (orden de habilidades, talentos) que van como títulos de grupos sin objetos.
    ability_order: nombres internos de las habilidades, nivel a nivel (bloque AbilityBuild)."""
    lines = ['"itembuilds"', "{", '\t"author"\t\t"Dota Coach"', f'\t"hero"\t\t\t"{hero_name}"',
             f'\t"Title"\t\t\t"{_q(title)}"', "", '\t"Items"', "\t{"]
    for line in skills:
        lines += [f'\t\t"{_q(line)}"', "\t\t{", "\t\t}", ""]
    for key, label in GROUPS:
        items = [i for i in dict.fromkeys(groups.get(key) or []) if i]
        if not items:
            continue
        lines += [f'\t\t"{label}"', "\t\t{"] + [f'\t\t\t"item"\t\t"{i}"' for i in items] + ["\t\t}", ""]
    lines += ["\t}"]
    if ability_order:
        lines += ["", '\t"AbilityBuild"', "\t{", '\t\t"AbilityOrder"', "\t\t{"]
        lines += [f'\t\t\t"{i}"\t\t"{name}"' for i, name in enumerate(ability_order, start=1)]
        lines += ["\t\t}", "\t}"]
    lines += ["}", ""]
    return "\n".join(lines)


def ensure_backup(dota_dir) -> Path:
    """Copia de TODAS las builds originales (una sola vez), antes de que el coach escriba ninguna."""
    src = builds_dir(dota_dir)
    dst = Path(dota_dir) / BACKUP_DIR
    if dst.exists():
        return dst
    dst.mkdir(parents=True)
    for f in src.glob("default_*.txt"):
        legacy = f.with_name(f.name + BACKUP_SUFFIX)
        if legacy.exists():
            shutil.copy2(legacy, dst / f.name)        # el original de verdad (este ya lo había cambiado el coach)
            shutil.move(str(legacy), str(dst / legacy.name))
        elif not is_ours(dota_dir, f.name[len("default_"):-4]):
            shutil.copy2(f, dst / f.name)
    log.info("copia de las builds originales de Dota en %s", dst)
    return dst


def export(dota_dir, hero_name: str, title: str, groups: dict[str, list[str]], skills: list[str] = (),
           ability_order: list[str] = ()) -> Path:
    """Escribe la build (antes, la copia de todas las originales si aún no existe). Devuelve el archivo escrito."""
    ensure_backup(dota_dir)
    path = build_file(dota_dir, hero_name)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(render(hero_name, title, groups, skills, ability_order), encoding="utf-8")
    log.info("guía llevada a la tienda de Dota: %s", path)
    return path


def restore(dota_dir, hero_name: str) -> bool:
    """Deja el archivo original de Valve de ese héroe (de la carpeta de copia)."""
    path = build_file(dota_dir, hero_name)
    original = Path(dota_dir) / BACKUP_DIR / path.name
    if not original.exists():
        return False
    shutil.copy2(original, path)
    return True


def exported_guide(dota_dir, hero_name: str) -> str | None:
    """Si la build del héroe la escribió el coach, el id de la guía (lo lleva el título: "… [guía 123]")."""
    import re
    path = build_file(dota_dir, hero_name)
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return None
    if '"author"		"Dota Coach"' not in text:
        return None
    m = re.search(r'\[guía ([^\]]+)\]', text)
    return m.group(1) if m else ""


def is_ours(dota_dir, hero_name: str) -> bool:
    path = build_file(dota_dir, hero_name)
    try:
        return '"author"\t\t"Dota Coach"' in path.read_text(encoding="utf-8")
    except OSError:
        return False


def groups_for_guide(guide, start_items: list[str], counters: list[str] = (), turbo: bool = False) -> dict:
    """Reparte los objetos de la guía en early/mid/late por el minuto en que se compraron en la partida original
    (sin minuto, por orden) y añade los iniciales y los counters de tu partida como "otros"."""
    early, mid, late = [], [], []
    n = len(guide.core)
    for i, (name, minute) in enumerate(guide.core):
        m = minute if minute else (i + 1) * 40 / max(1, n)
        (early if m < 12 else mid if m < 28 else late).append(name)
    return {"start": list(start_items), "early": early, "mid": mid, "late": late,
            "other": [c for c in counters if c not in guide.items]}


def skill_lines(plan, hero: dict, max_level: int = 18) -> tuple[list[str], list[str]]:
    """Del plan de habilidades (engine/skillbuild): (líneas de texto para la tienda, orden nivel a nivel).
    Las letras son las de las teclas por defecto: Q W E para las normales y R para la definitiva."""
    from .engine.skillbuild import suggested_sequence
    if plan is None:
        return [], []
    normal = [a for a in hero.get("abilities") or [] if a.get("type") != 1 and int(a.get("max_level") or 0) >= 3
              and not a.get("ability_is_granted_by_shard") and not a.get("ability_is_granted_by_scepter")][:3]
    keys = {a["name"]: k for a, k in zip(normal, "QWE")}
    if plan.ultimate:
        keys[plan.ultimate.name] = "R"
    names = {a["name"]: a.get("name_loc") or a["name"] for a in hero.get("abilities") or []}
    seq = suggested_sequence(plan, max_level)
    letters = [("T" if n == "talent" else "+" if n == "attr" else keys.get(n, "?")) for _, n in seq]
    lines = ["Habilidades: " + " | ".join(f"{k} {names.get(n, n)}" for n, k in keys.items())]
    for lo in range(0, len(letters), 6):
        lines.append(f"Niveles {lo + 1}-{min(lo + 6, len(letters))}: " + " ".join(letters[lo:lo + 6]))
    for t in sorted(plan.talents, key=lambda t: t.level):
        lines.append(f"Talento {t.level}: {t.pick} ({t.share:.0%})")
    order = [n for _, n in seq if n not in ("talent", "attr")]
    return lines, order


__all__ = ["build_file", "ensure_backup", "export", "groups_for_guide", "is_ours", "render", "restore",
           "skill_lines"]
