"""Proveedores de IA (opcionales). Sin IA, el coach funciona con reglas y estadísticas."""
import os

from .base import LLMError, Provider
from .openai_compat import PRESETS, OpenAICompat
from .secrets import decrypt_key, encrypt_key

PROVIDER_IDS = ["claude", *PRESETS]
ENV_KEYS = {"claude": "ANTHROPIC_API_KEY", "openai": "OPENAI_API_KEY", "gemini": "GEMINI_API_KEY",
            "groq": "GROQ_API_KEY", "openrouter": "OPENROUTER_API_KEY", "deepseek": "DEEPSEEK_API_KEY"}


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


__all__ = ["LLMError", "PROVIDER_IDS", "Provider", "decrypt_key", "encrypt_key", "make_provider"]
