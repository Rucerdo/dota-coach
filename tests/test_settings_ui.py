"""Ventana de ajustes: dos ventanas abiertas no se pisan la configuración (usa el COACH_HOME temporal)."""
import pytest

from coach import config
from coach.ai import provider_label, stored_key

ctk = pytest.importorskip("customtkinter")


@pytest.fixture
def make_app():
    from coach.ui.settings import SettingsApp
    apps = []

    def make():
        try:
            app = SettingsApp(config.load())
        except Exception as ex:  # sin pantalla (CI)
            pytest.skip(f"sin Tk: {ex}")
        app.withdraw()
        apps.append(app)
        return app
    yield make
    for a in apps:
        try:
            a.destroy()
        except Exception:  # ya cerrada en el test
            pass


def test_stale_window_does_not_overwrite_ai(make_app):
    old = make_app()                      # abierta antes de configurar la IA
    new = make_app()
    new._on_provider(provider_label("gemini"))
    new.ai_fields["key"][1].insert(0, "AIza-test")
    new._save_ai_fields()

    old.set("role", "carry")              # tocar otro ajuste en la ventana vieja...
    old.on_close()                        # ...y cerrarla
    saved = config.load()
    assert saved["role"] == "carry"
    assert saved["ai"]["provider"] == "gemini" and stored_key(saved, "gemini") == "AIza-test"


def test_unedited_fields_are_not_saved(make_app):
    app = make_app()
    app._on_provider(provider_label("groq"))
    app.ai_fields["key"][1].insert(0, "gsk-1")
    app._save_ai_fields()
    assert stored_key(config.load(), "groq") == "gsk-1"
    app.ai_fields["key"][1].delete(0, "end")  # borrar a mano sí cuenta como edición
    app._save_ai_fields()
    assert stored_key(config.load(), "groq") == ""
