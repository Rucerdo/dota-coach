"""Proveedores de IA (opcionales). Sin IA, el coach funciona con reglas y estadísticas."""
import os

from .base import LLMError, Provider
from .openai_compat import PRESETS, OpenAICompat
from .secrets import decrypt_key, encrypt_key

PROVIDER_IDS = ["claude", *PRESETS]
# Dónde se consigue la clave de cada proveedor (botón "Conseguir clave" de los ajustes)
KEY_PAGES = {"claude": "https://console.anthropic.com/settings/keys", "openai": "https://platform.openai.com/api-keys",
             "gemini": "https://aistudio.google.com/apikey", "groq": "https://console.groq.com/keys",
             "openrouter": "https://openrouter.ai/keys", "deepseek": "https://platform.deepseek.com/api_keys"}
ENV_KEYS = {"claude": "ANTHROPIC_API_KEY", "openai": "OPENAI_API_KEY", "gemini": "GEMINI_API_KEY",
            "groq": "GROQ_API_KEY", "openrouter": "OPENROUTER_API_KEY", "deepseek": "DEEPSEEK_API_KEY"}


def provider_label(pid: str) -> str:
    if pid == "claude":
        return "Claude (Anthropic)"
    return PRESETS[pid]["label"] if pid in PRESETS else "Sin IA (solo reglas)"


def needs_key(pid: str) -> bool:
    return pid in PROVIDER_IDS and PRESETS.get(pid, {}).get("needs_key", True)


def stored_key(cfg: dict, pid: str) -> str:
    """Clave guardada (descifrada) del proveedor; "" si no hay."""
    return decrypt_key(((cfg.get("ai") or {}).get("keys_enc") or {}).get(pid, ""))


def set_ai(cfg: dict, provider: str, key: str | None = None, model: str | None = None,
           base_url: str | None = None) -> dict:
    """Cambia el proveedor (y, si se dan, su clave, modelo y URL) en cfg. No guarda en disco.
    Cada proveedor conserva su clave; el modelo y la URL son los del proveedor activo."""
    ai = cfg.setdefault("ai", {})
    if provider != ai.get("provider") and model is None:
        model = ""  # el modelo de otro proveedor no sirve: vuelve al de por defecto
    ai["provider"] = provider
    if key is not None:
        keys = ai.setdefault("keys_enc", {})
        if key.strip():
            keys[provider] = encrypt_key(key.strip())
        else:
            keys.pop(provider, None)
    if model is not None:
        ai["model"] = model.strip()
    if base_url is not None:
        ai["base_url"] = base_url.strip()
    return cfg


def make_provider(cfg: dict) -> Provider | None:
    """Proveedor configurado en cfg['ai'], o None si no hay IA."""
    ai = cfg.get("ai") or {}
    pid = ai.get("provider") or "none"
    if pid not in PROVIDER_IDS:
        return None
    key = decrypt_key((ai.get("keys_enc") or {}).get(pid, "")) or os.environ.get(ENV_KEYS.get(pid, ""), "")
    if pid == "claude":
        from .claude import Claude  # importa el SDK solo si hace falta
        return Claude(key, ai.get("model", ""))
    p = OpenAICompat(pid, key, ai.get("model", ""), ai.get("base_url", "") if pid == "custom" else "")
    return p if (key or not p.needs_key) else None


__all__ = ["KEY_PAGES", "LLMError", "PROVIDER_IDS", "Provider", "decrypt_key", "encrypt_key", "make_provider",
           "needs_key", "provider_label", "set_ai", "stored_key"]
