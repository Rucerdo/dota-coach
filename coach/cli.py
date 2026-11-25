"""Línea de comandos de Dota Coach.

  coach meta [--ai] [--review]       el meta del parche actual (winrates + tendencia + notas)
  coach patch [--hero X|--item X]    cambios del parche actual, clasificados buff/nerf
  coach draft --enemies "pa, lion"   qué héroe elegir
  coach items --hero jugg --enemies "pa, lion" [--owned "bkb"]
  coach run [--enemies ...]          modo en directo: overlay sobre Dota con consejos
  coach install | uninstall          integración GSI en Dota
  coach ai set claude --key ...      configurar la IA (opcional); coach ai test
  coach vision strip|unknown|label   comprobar y entrenar el reconocimiento de la barra superior
"""
import argparse
import logging
import sys
from pathlib import Path

from . import config, dota
from .ai import PROVIDER_IDS, LLMError, encrypt_key, make_provider
from .data import opendota
from .data.gamedata import GameData
from .data.meta import Meta
from .data.patches import load_cycle

log = logging.getLogger("coach")


def _setup_logging(verbose: bool):
    config.APP_DIR.mkdir(parents=True, exist_ok=True)
    handlers = [logging.FileHandler(config.LOG_PATH, encoding="utf-8")]
    if verbose:
        handlers.append(logging.StreamHandler())
    logging.basicConfig(level=logging.INFO, handlers=handlers,
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")


def _provider_or_exit(cfg):
    p = make_provider(cfg)
    if p is None:
        sys.exit("No hay IA configurada. Ejemplo: coach ai set claude --key sk-ant-...  (o ANTHROPIC_API_KEY)")
    return p


def _heroes(gd: GameData, text: str | None, label: str):
    heroes, unknown = gd.parse_heroes(text or "")
    if unknown:
        print(f"⚠ {label}: no reconozco {', '.join(unknown)}")
    return heroes


# ---------- comandos ----------
def cmd_meta(args, cfg, gd):
    meta = Meta.build(gd, cfg.get("rank_bracket", 0))
    if args.review:
        p = _provider_or_exit(cfg)
        print(f"Analizando las notas de {' + '.join(meta.versions)} con {p.label} (una vez por parche)...")
        n = meta.ai_review(p, cfg.get("lang", "es"), progress=lambda d, t: print(f"  {d}/{t}", end="\r"))
        print(f"\n{n} héroes/objetos analizados.")
    print(meta.brief(args.top))
    if args.ai:
        p = _provider_or_exit(cfg)
        print("\n— Resumen del meta (IA) —")
        print(meta.ai_brief(p, cfg.get("lang", "es")))


def cmd_patch(args, cfg, gd):
    versions, changes = load_cycle(gd)
    if args.hero:
        h = gd.hero(args.hero)
        if not h:
            sys.exit(f"No reconozco el héroe '{args.hero}'")
        changes = [c for c in changes if c.kind == "hero" and c.target_id == h.id]
    elif args.item:
        it = gd.item(args.item)
        if not it:
            sys.exit(f"No reconozco el objeto '{args.item}'")
        changes = [c for c in changes if c.target == it.loc]
    elif args.general:
        changes = [c for c in changes if c.kind == "general"]
    print(f"Parche {' + '.join(versions)}: {len(changes)} cambios")
    last = None
    for c in changes:
        head = (c.version, c.target, c.detail)
        if head != last:
            print(f"\n[{c.version}] {c.target or 'General'} · {c.detail}")
            last = head
        print(f"  {c.tag:6} {c.text}")


def cmd_draft(args, cfg, gd):
    from .engine.draft import suggest_picks
    enemies = _heroes(gd, args.enemies, "enemigos")
    allies = _heroes(gd, args.allies, "aliados")
    if not enemies:
        sys.exit("Indica al menos un enemigo: --enemies \"pa, lion\"")
    meta = Meta.build(gd, cfg.get("rank_bracket", 0))
    role = args.role or cfg.get("role", "auto")
    picks = suggest_picks(gd, enemies, allies, role, meta, opendota.matchups, limit=args.top)
    print(f"Contra {', '.join(h.loc for h in enemies)} · rol {role} · parche {meta.patch}")
    for i, s in enumerate(picks, 1):
        print(f"{i:2}. {s.line()}")
    if args.ai:
        from .ai.prompts import draft_prompt
        p = _provider_or_exit(cfg)
        ctx = [f"Enemy heroes: {', '.join(h.loc for h in enemies)}",
               f"Allied heroes: {', '.join(h.loc for h in allies) or 'none yet'}", f"Player role: {role}",
               "Candidates (score = matchup advantage + current meta):", *[f"- {s.line()}" for s in picks],
               f"Patch {meta.patch} context:", meta.context_for(enemies + [s.hero for s in picks[:5]])]
        system, user = draft_prompt("\n".join(ctx), cfg.get("lang", "es"))
        print("\n— Recomendación (IA) —")
        print(p.complete(system, user, effort="medium", max_tokens=8000))


def cmd_items(args, cfg, gd):
    from .engine.counters import enemy_traits, suggest_items, TRAIT_LABELS
    hero = gd.hero(args.hero) if args.hero else None
    if args.hero and not hero:
        sys.exit(f"No reconozco el héroe '{args.hero}'")
    enemies = _heroes(gd, args.enemies, "enemigos")
    owned = [it.name for it in (gd.item(x.strip()) for x in (args.owned or "").split(",")) if it]
    meta = Meta.build(gd, cfg.get("rank_bracket", 0))
    pop = opendota.item_popularity(hero.id) if hero else None
    sugg = suggest_items(gd, hero, enemies, owned, args.role or cfg.get("role", "auto"), meta, pop, limit=args.top)
    traits = enemy_traits(enemies)
    if traits:
        print("Rasgos enemigos: " + "; ".join(f"{TRAIT_LABELS.get(t, t)}: {', '.join(h)}" for t, h in traits.items()))
    for i, s in enumerate(sugg, 1):
        print(f"{i}. {s.line()}")
    if args.ai:
        from .engine.advisor import Advisor
        from .gsi import GameState
        p = _provider_or_exit(cfg)
        adv = Advisor(gd, meta, cfg, p, popularity=opendota.item_popularity, sync=True)
        adv.set_enemies(enemies)
        st = GameState(game_state="DOTA_GAMERULES_STATE_GAME_IN_PROGRESS", hero=hero.name if hero else "",
                       hero_id=hero.id if hero else 0, items=owned, gold=args.gold, clock=args.minute * 60)
        print("\n— Consejo (IA) —")
        for t in adv.ai_tips(st, ["manual"]):
            print(f"[{t.kind}] {t.text}")


def cmd_install(args, cfg, gd=None):
    d = dota.normalize(cfg.get("dota_dir")) or dota.find_dota_dir()
    if not d:
        sys.exit("No encuentro Dota 2. Indica la carpeta: coach install --dota-dir \"...\\dota 2 beta\"")
    if args.cmd == "uninstall":
        print("Quitado." if dota.uninstall(d) else "No estaba instalado.")
        return
    print(f"Instalado: {dota.install(d, cfg['gsi_port'])}\nReinicia Dota 2 una vez para que lo cargue.")


def cmd_ai(args, cfg, gd=None):
    if args.action == "set":
        ai = cfg["ai"]
        ai["provider"] = args.provider
        if args.key:
            ai.setdefault("keys_enc", {})[args.provider] = encrypt_key(args.key)
        if args.model is not None:
            ai["model"] = args.model
        if args.base_url is not None:
            ai["base_url"] = args.base_url
        config.save(cfg)
        print(f"IA: {args.provider}" + (f" · modelo {args.model}" if args.model else "") + " (clave cifrada con tu usuario de Windows)")
    elif args.action == "off":
        cfg["ai"]["provider"] = "none"
        config.save(cfg)
        print("IA desactivada: el coach usa solo reglas y estadísticas.")
    else:
        p = _provider_or_exit(cfg)
        try:
            print(f"{p.label} · {p.resolved_model()}: " + p.complete("Reply in one short sentence.", "Say hi to a Dota player."))
        except LLMError as e:
            sys.exit(f"Error: {e}")


def cmd_vision(args, cfg, gd):
    from .vision import topbar
    if args.action == "strip":
        out = topbar.save_debug_strip(Path(args.out), cfg.get("topbar"))
        print(f"Guardado {out}" if out else "No encuentro la ventana de Dota 2.")
    elif args.action == "unknown":
        files = sorted(topbar.unknown_dir().glob("*.png"))
        print(f"{len(files)} retratos sin reconocer en {topbar.unknown_dir()}")
        for f in files:
            print(f"  {f.name}")
        print('Etiquétalos con: coach vision label <archivo> "<héroe>"')
    elif args.action == "label":
        h = gd.hero(args.hero or "")
        path = Path(args.file)
        if not path.exists():
            path = topbar.unknown_dir() / args.file
        if not h or not path.exists():
            sys.exit("Uso: coach vision label <archivo> \"<héroe>\"")
        print(f"Plantilla de {h.loc}: {topbar.label_tile(path, h)}")


def cmd_run(args, cfg, gd):
    from .live import run_live
    meta = Meta.build(gd, cfg.get("rank_bracket", 0))
    run_live(cfg, gd, meta, _heroes(gd, args.enemies, "enemigos"))


def main(argv=None):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except (AttributeError, ValueError):
        pass
    ap = argparse.ArgumentParser(prog="coach", description="Dota Coach: asistente de Dota 2 con el meta del parche actual")
    ap.add_argument("-v", "--verbose", action="store_true")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("meta", help="el meta del parche actual")
    p.add_argument("--top", type=int, default=8)
    p.add_argument("--ai", action="store_true", help="añadir un resumen escrito por la IA")
    p.add_argument("--review", action="store_true", help="analizar las notas del parche con IA (una vez por parche)")
    p.add_argument("--bracket", type=int, choices=range(0, 9), help="rango: 0 todos, 1 Herald ... 8 Immortal")

    p = sub.add_parser("patch", help="cambios del parche actual")
    g = p.add_mutually_exclusive_group()
    g.add_argument("--hero")
    g.add_argument("--item")
    g.add_argument("--general", action="store_true")

    p = sub.add_parser("draft", help="qué héroe elegir")
    p.add_argument("--enemies", required=True)
    p.add_argument("--allies")
    p.add_argument("--role", choices=["auto", "carry", "core", "support"])
    p.add_argument("--top", type=int, default=8)
    p.add_argument("--ai", action="store_true")

    p = sub.add_parser("items", help="qué comprar")
    p.add_argument("--hero")
    p.add_argument("--enemies")
    p.add_argument("--owned", help="objetos que ya tienes, separados por comas")
    p.add_argument("--role", choices=["auto", "carry", "core", "support"])
    p.add_argument("--gold", type=int, default=0)
    p.add_argument("--minute", type=int, default=10)
    p.add_argument("--top", type=int, default=6)
    p.add_argument("--ai", action="store_true")

    p = sub.add_parser("run", help="modo en directo con overlay")
    p.add_argument("--enemies", help="enemigos conocidos (si la visión no los detecta)")

    for name in ("install", "uninstall"):
        p = sub.add_parser(name, help=f"{name} la integración GSI en Dota")
        p.add_argument("--dota-dir")

    p = sub.add_parser("ai", help="configurar la IA")
    p.add_argument("action", choices=["set", "test", "off"])
    p.add_argument("provider", nargs="?", choices=PROVIDER_IDS)
    p.add_argument("--key")
    p.add_argument("--model")
    p.add_argument("--base-url")

    p = sub.add_parser("vision", help="reconocimiento de la barra superior")
    p.add_argument("action", choices=["strip", "unknown", "label"])
    p.add_argument("file", nargs="?")
    p.add_argument("hero", nargs="?")
    p.add_argument("--out", default="topbar.png")

    args = ap.parse_args(argv)
    _setup_logging(args.verbose)
    cfg = config.load()
    if getattr(args, "bracket", None) is not None:
        cfg["rank_bracket"] = args.bracket
    if getattr(args, "dota_dir", None):
        cfg["dota_dir"] = args.dota_dir
        config.save(cfg)
    if args.cmd == "ai" and args.action == "set" and not args.provider:
        ap.error("indica el proveedor: " + ", ".join(PROVIDER_IDS))

    if args.cmd in ("install", "uninstall"):
        return cmd_install(args, cfg)
    if args.cmd == "ai":
        return cmd_ai(args, cfg)
    gd = GameData.load()
    {"meta": cmd_meta, "patch": cmd_patch, "draft": cmd_draft, "items": cmd_items, "run": cmd_run,
     "vision": cmd_vision}[args.cmd](args, cfg, gd)


if __name__ == "__main__":
    main()
