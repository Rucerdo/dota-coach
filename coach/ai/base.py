"""Interfaz común de los proveedores de IA: una sola operación, complete()."""
import time


class LLMError(Exception):
    """El proveedor no pudo responder; el coach sigue con las reglas sin IA."""


class Provider:
    id = ""
    label = ""
    needs_key = True

    def __init__(self, key: str = "", model: str = "", base_url: str = ""):
        self.key, self.model, self.base_url = key.strip(), model.strip(), base_url.strip().rstrip("/")
        self.cooldown_until = 0.0

    @property
    def available(self) -> bool:
        return (bool(self.key) or not self.needs_key) and time.time() >= self.cooldown_until

    def pause(self, seconds: float):
        self.cooldown_until = time.time() + seconds

    def resolved_model(self) -> str:
        return self.model

    def complete(self, system: str, user: str, schema: dict | None = None, effort: str = "low",
                 max_tokens: int = 4000, timeout: float = 60.0) -> str:
        """Texto de respuesta. Con 'schema', la respuesta es JSON que cumple ese esquema."""
        raise NotImplementedError
