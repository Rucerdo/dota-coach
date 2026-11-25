"""Actualizador de la aplicación (GitHub Releases), sin red: la respuesta de GitHub se simula."""
from coach import selfupdate


class Resp:
    def __init__(self, status, data=None):
        self.status_code, self._data = status, data or {}

    def json(self):
        return self._data

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(self.status_code)


def test_versions():
    assert selfupdate.is_newer("v1.0.1", "1.0.0") and not selfupdate.is_newer("v1.0.0", "1.0.0")
    assert selfupdate.parse_version("v2.3") == (2, 3, 0)


def test_check_latest(monkeypatch):
    release = {"tag_name": "v9.0.0", "body": "Novedades", "html_url": "https://github.com/x/y/releases/v9.0.0",
               "assets": [{"name": "DotaCoach.exe", "browser_download_url": "https://x/DotaCoach.exe", "size": 10},
                          {"name": "SHA256SUMS.txt", "browser_download_url": "https://x/SHA256SUMS.txt"}]}
    monkeypatch.setattr(selfupdate.requests, "get", lambda *a, **k: Resp(200, release))
    info = selfupdate.check_latest()
    assert info.version == "9.0.0" and info.exe_url.endswith("DotaCoach.exe") and info.sha_url
    monkeypatch.setattr(selfupdate.requests, "get", lambda *a, **k: Resp(404))
    assert selfupdate.check_latest() is None                      # todavía no hay releases
    old = dict(release, tag_name="v0.0.1")
    monkeypatch.setattr(selfupdate.requests, "get", lambda *a, **k: Resp(200, old))
    assert selfupdate.check_latest() is None                      # no es más nueva
