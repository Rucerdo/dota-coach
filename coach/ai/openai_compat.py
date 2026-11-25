"""Servicios con API compatible con OpenAI (/v1/chat/completions): ChatGPT, Gemini, Groq, OpenRouter,
DeepSeek y servidores locales (Ollama, LM Studio...).

Si no se indica modelo, se elige uno de /models según las preferencias de cada servicio.
Si un servicio no admite la salida JSON o el esfuerzo de razonamiento, se quita el parámetro y se recuerda.
"""
import logging
import re
import threading

import requests

from .base import LLMError, Provider

log = logging.getLogger(__name__)

PRESETS = {
    "openai": dict(label="ChatGPT (OpenAI)", base="https://api.openai.com/v1",
                   prefer=[r"^gpt-\d+(\.\d+)?-mini$", r"^gpt-\d+(\.\d+)?$"], reasoning=r"^(gpt-[5-9]|o\d)"),
    "gemini": dict(label="Gemini (Google)", base="https://generativelanguage.googleapis.com/v1beta/openai",
                   prefer=[r"gemini-[\d.]+-flash$", r"gemini.*flash", r"gemini"], reasoning=r"gemini-[2-9]"),
    "groq": dict(label="Groq", base="https://api.groq.com/openai/v1",
                 prefer=[r"^openai/gpt-oss-120b$", r"gpt-oss", r"^llama"], reasoning=r"gpt-oss|qwen3"),
    "openrouter": dict(label="OpenRouter", base="https://openrouter.ai/api/v1", prefer=[],
                       default="openrouter/auto", reasoning=None),
    "deepseek": dict(label="DeepSeek", base="https://api.deepseek.com/v1", prefer=[r"^deepseek-chat$"],
                     reasoning=None),
    "custom": dict(label="Servidor local (Ollama, LM Studio…)", base="http://127.0.0.1:11434/v1", prefer=[],
                   reasoning=None, needs_key=False),
}
_SKIP = re.compile(r"audio|realtime|transcribe|tts|whisper|embed|image|moderation|search|guard|vision|codex", re.I)
_EFFORT = {"low": "low", "medium": "medium", "high": "high", "xhigh": "high", "max": "high"}


class OpenAICompat(Provider):
    def __init__(self, preset_id: str, key="", model="", base_url=""):
        p = PRESETS[preset_id]
        super().__init__(key, model, base_url or p["base"])
        self.id, self.label = preset_id, p["label"]
        self.needs_key = p.get("needs_key", True)
        self._prefer, self._default = p["prefer"], p.get("default", "")
        self._reasoning = re.compile(p["reasoning"]) if p.get("reasoning") else None
        self._session = requests.Session()
        self._lock = threading.Lock()
        self._chosen = ""
        self._unsupported: set[str] = set()

    def _headers(self):
        h = {"Content-Type": "application/json"}
        if self.key:
            h["Authorization"] = f"Bearer {self.key}"
        return h

    def resolved_model(self) -> str:
        if self.model:
            return self.model
        with self._lock:
            if self._chosen:
                return self._chosen
        chosen = self._default
        if not chosen:
            try:
                r = self._session.get(f"{self.base_url}/models", headers=self._headers(), timeout=10)
                r.raise_for_status()
                ids = [m.get("id", "") for m in r.json().get("data", [])]
            except (requests.RequestException, ValueError) as e:
                raise LLMError(f"{self.label}: no se pudo listar los modelos ({e})") from e
            ids = [i.removeprefix("models/") for i in ids if i and not _SKIP.search(i)]
            for pat in self._prefer:
                matches = sorted((i for i in ids if re.search(pat, i)), reverse=True)
                if matches:
                    chosen = matches[0]
                    break
            chosen = chosen or (ids[0] if ids else "")
        if not chosen:
            raise LLMError(f"{self.label}: no hay modelos disponibles; indica uno en la configuración")
        with self._lock:
            self._chosen = chosen
        log.info("%s: modelo %s", self.label, chosen)
        return chosen

    def complete(self, system, user, schema=None, effort="low", max_tokens=4000, timeout=60.0):
        model = self.resolved_model()
        body = {"model": model, "max_completion_tokens": max_tokens,
                "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}]}
        if schema and "response_format" not in self._unsupported:
            body["response_format"] = {"type": "json_schema",
                                       "json_schema": {"name": "reply", "schema": schema, "strict": True}}
        if self._reasoning and self._reasoning.search(model) and "reasoning_effort" not in self._unsupported:
            body["reasoning_effort"] = _EFFORT.get(effort, "low")
        for _ in range(3):
            try:
                r = self._session.post(f"{self.base_url}/chat/completions", headers=self._headers(), json=body,
                                       timeout=timeout)
            except requests.RequestException as e:
                self.pause(30)
                raise LLMError(f"sin conexión con {self.label}") from e
            if r.status_code == 400:
                msg = r.text.lower()
                dropped = next((p for p in ("response_format", "reasoning_effort", "max_completion_tokens")
                                if p in msg and p in body), None)
                if dropped:
                    log.info("%s no admite %s; se quita", self.label, dropped)
                    self._unsupported.add(dropped)
                    value = body.pop(dropped)
                    if dropped == "max_completion_tokens":
                        body["max_tokens"] = value
                    continue
            break
        if r.status_code in (401, 403):
            self.pause(600)
            raise LLMError(f"clave de {self.label} no válida")
        if r.status_code == 429:
            self.pause(60)
            raise LLMError(f"{self.label}: límite de uso alcanzado")
        if r.status_code >= 400:
            raise LLMError(f"error de {self.label} ({r.status_code}): {r.text[:200]}")
        try:
            return r.json()["choices"][0]["message"]["content"] or ""
        except (ValueError, KeyError, IndexError, TypeError) as e:
            raise LLMError(f"respuesta de {self.label} no válida") from e
