"""Configuración de la IA (la usan la CLI y la ventana de ajustes). Sin red."""
import copy

from coach.ai import needs_key, provider_label, set_ai, stored_key
from coach.config import DEFAULTS


def test_set_ai_keeps_key_per_provider():
    cfg = copy.deepcopy(DEFAULTS)
    set_ai(cfg, "claude", key="sk-ant-123", model="claude-sonnet-5-5")
    set_ai(cfg, "groq", key="gsk-456")
    assert cfg["ai"]["provider"] == "groq"
    assert cfg["ai"]["model"] == ""  # el modelo de Claude no vale para Groq
    assert stored_key(cfg, "claude") == "sk-ant-123" and stored_key(cfg, "groq") == "gsk-456"
    assert "sk-ant-123" not in str(cfg)  # se guarda cifrada


def test_set_ai_empty_key_removes_it_and_none_keeps_it():
    cfg = copy.deepcopy(DEFAULTS)
    set_ai(cfg, "openai", key="sk-1")
    set_ai(cfg, "openai", model="gpt-5-mini")  # sin key: se conserva
    assert stored_key(cfg, "openai") == "sk-1" and cfg["ai"]["model"] == "gpt-5-mini"
    set_ai(cfg, "openai", key="  ")
    assert stored_key(cfg, "openai") == ""


def test_labels_and_key_requirements():
    assert provider_label("claude").startswith("Claude")
    assert provider_label("none").startswith("Sin IA")
    assert needs_key("openai") and not needs_key("custom") and not needs_key("none")
