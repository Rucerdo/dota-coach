"""Partidas turbo: detección por el oro pasivo, fases al doble de rápido y orden de compra por fase."""
from coach.engine.counters import ItemSuggestion, phase_for, purchase_order
from coach.gsi import is_turbo, parse_state


def test_turbo_detected_from_passive_gold():
    # valores reales de las grabaciones: normal ≈ 88/min, turbo ≈ 176/min
    assert not is_turbo(296, 431) and not is_turbo(539, 785)
    assert is_turbo(61, 180) and is_turbo(610, 1784)
    assert not is_turbo(10, 50)  # demasiado pronto para saberlo
    st = parse_state({"map": {"clock_time": 610, "game_state": "DOTA_GAMERULES_STATE_GAME_IN_PROGRESS"},
                      "player": {"gold_from_income": 1784}})
    assert st.turbo


def test_turbo_phases_go_twice_as_fast():
    assert phase_for(8 * 60) == "early" and phase_for(8 * 60, turbo=True) == "mid"
    assert phase_for(15 * 60) == "mid" and phase_for(15 * 60, turbo=True) == "late"
    assert phase_for(-30, turbo=True) == "start"


def test_purchase_order_follows_typical_minute():
    bkb = ItemSuggestion("item_black_king_bar", "Black King Bar", 4050, 9.0, minute=18)
    phase = ItemSuggestion("item_phase_boots", "Phase Boots", 1500, 1.0, minute=7)
    dust = ItemSuggestion("item_dust", "Dust of Appearance", 80, 3.0)        # sin datos: por precio
    half = ItemSuggestion("item_maelstrom", "Maelstrom", 2700, 2.0, minute=13, remaining=300)  # casi hecho
    assert [s.item for s in purchase_order([bkb, phase, dust, half])] == \
        ["item_dust", "item_maelstrom", "item_phase_boots", "item_black_king_bar"]
