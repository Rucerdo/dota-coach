"""Elección de modelo y cambio de modelo cuando el elegido está saturado (sin red: sesión simulada)."""
import pytest

from coach.ai.base import LLMError
from coach.ai.openai_compat import OpenAICompat

MODELS = ["gemini-2.5-flash", "gemini-3.8-flash", "gemini-3.7-flash", "gemini-3.5-flash-lite",
          "gemini-3-flash-preview", "gemini-3.8-live", "gemma-4-31b-it"]


class Resp:
    def __init__(self, status, data=None, text=""):
        self.status_code, self._data, self.text = status, data or {}, text

    def json(self):
        return self._data

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(self.status_code)


class FakeSession:
    def __init__(self, busy: set[str]):
        self.busy, self.posted = busy, []

    def get(self, url, **kw):
        return Resp(200, {"data": [{"id": f"models/{m}"} for m in MODELS]})

    def post(self, url, json=None, **kw):
        self.posted.append(json["model"])
        if json["model"] in self.busy:
            return Resp(503, text='{"error": {"code": 503, "status": "UNAVAILABLE"}}')
        return Resp(200, {"choices": [{"message": {"content": f"hola desde {json['model']}"}}]})


def _gemini(busy=(), model=""):
    p = OpenAICompat("gemini", key="k", model=model)
    p._session = FakeSession(set(busy))
    return p


def test_prefers_newest_stable_flash():
    p = _gemini()
    assert p.resolved_model() == "gemini-3.8-flash"
    assert p._candidates[:3] == ["gemini-3.8-flash", "gemini-3.7-flash", "gemini-2.5-flash"]
    assert "gemini-3.5-flash-lite" in p._candidates  # Lite, como último recurso


def test_overloaded_model_switches_to_next():
    p = _gemini(busy={"gemini-3.8-flash"})
    assert p.complete("s", "u") == "hola desde gemini-3.7-flash"
    assert p._session.posted == ["gemini-3.8-flash", "gemini-3.7-flash"]
    assert p.resolved_model() == "gemini-3.7-flash"  # se queda con el que funciona


def test_fixed_model_does_not_switch():
    p = _gemini(busy={"gemini-3.8-flash"}, model="gemini-3.8-flash")
    with pytest.raises(LLMError, match="503"):
        p.complete("s", "u")
    assert p._session.posted == ["gemini-3.8-flash"]
