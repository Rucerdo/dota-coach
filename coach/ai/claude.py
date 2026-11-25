"""Claude (Anthropic) con el SDK oficial. Clave: https://console.anthropic.com/settings/keys

- Modelo por defecto: claude-opus-5-5. En Opus 5.5 el razonamiento no se desactiva: el esfuerzo
  (output_config.effort) controla profundidad y latencia. Consejos en partida: 'low' (rápido);
  análisis del parche: 'medium'.
- Salida JSON garantizada con output_config.format (json_schema).
- Si un filtro rechaza la petición (stop_reason 'refusal'), se usa el respaldo del servidor
  ('fallbacks': 'default'); si la cuenta no lo admite, se envía sin él.
"""
import logging
import threading

import anthropic

from .base import LLMError, Provider

log = logging.getLogger(__name__)

DEFAULT_MODEL = "claude-opus-5-5"
_EFFORT_MODELS = ("claude-opus-5-5", "claude-sonnet-5-5", "claude-haiku-5-5", "claude-fable-5-2")
_SERVER_FALLBACK = {"claude-opus-5-5", "claude-sonnet-5-5", "claude-fable-5-2"}
_FALLBACK_BETA = "server-side-fallback-2026-07-01"


class Claude(Provider):
    id = "claude"
    label = "Claude (Anthropic)"

    def __init__(self, key="", model="", base_url=""):
        super().__init__(key, model, base_url)
        self._client: anthropic.Anthropic | None = None
        self._lock = threading.Lock()
        self._no_fallback_param = False

    @property
    def available(self) -> bool:
        # sin clave en la config, el SDK también la busca en ANTHROPIC_API_KEY / 'ant auth login'
        import time
        return time.time() >= self.cooldown_until

    def resolved_model(self) -> str:
        return self.model or DEFAULT_MODEL

    def _get_client(self) -> anthropic.Anthropic:
        with self._lock:
            if self._client is None:
                kwargs = {"max_retries": 1}
                if self.key:
                    kwargs["api_key"] = self.key
                self._client = anthropic.Anthropic(**kwargs)
            return self._client

    def complete(self, system, user, schema=None, effort="low", max_tokens=4000, timeout=60.0):
        client = self._get_client().with_options(timeout=timeout)
        model = self.resolved_model()
        output_config: dict = {}
        if schema:
            output_config["format"] = {"type": "json_schema", "schema": schema}
        if model in _EFFORT_MODELS:
            output_config["effort"] = effort
        params = dict(model=model, max_tokens=max_tokens, system=system,
                      messages=[{"role": "user", "content": user}])
        if output_config:
            params["output_config"] = output_config
        try:
            if model in _SERVER_FALLBACK and not self._no_fallback_param:
                try:
                    response = client.beta.messages.create(betas=[_FALLBACK_BETA], fallbacks="default", **params)
                except anthropic.BadRequestError as e:
                    if "fallback" not in str(e).lower():
                        raise
                    log.info("la cuenta no admite 'fallbacks'; se envía sin él")
                    self._no_fallback_param = True
                    response = client.messages.create(**params)
            else:
                response = client.messages.create(**params)
        except (anthropic.AuthenticationError, anthropic.PermissionDeniedError) as e:
            self.pause(600)
            raise LLMError("clave de Claude no válida o sin permiso") from e
        except anthropic.NotFoundError as e:
            raise LLMError(f"modelo de Claude no encontrado: {model}") from e
        except anthropic.RateLimitError as e:
            self.pause(60)
            raise LLMError("Claude: límite de uso alcanzado") from e
        except anthropic.BadRequestError as e:
            raise LLMError(f"Claude rechazó la petición: {e.message}") from e
        except anthropic.APIStatusError as e:
            raise LLMError(f"error de Claude ({e.status_code})") from e
        except anthropic.APIConnectionError as e:
            self.pause(30)
            raise LLMError("sin conexión con Claude") from e
        if response.stop_reason == "refusal":
            raise LLMError("Claude rechazó la petición")
        if response.stop_reason == "max_tokens":
            log.warning("respuesta de Claude cortada por max_tokens=%d", max_tokens)
        return next((b.text for b in response.content if b.type == "text"), "")
