from fastapi.testclient import TestClient

from sensebench import __version__
from sensebench.api import create_app
from sensebench.config import Settings


def _client(data_dir) -> TestClient:
    return TestClient(create_app(Settings(data_dir=data_dir, _env_file=None)))


def test_healthz_ok_when_data_dir_exists(tmp_path):
    resp = _client(tmp_path).get("/healthz")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok", "version": __version__}


def test_healthz_returns_503_when_data_dir_missing(tmp_path):
    resp = _client(tmp_path / "missing").get("/healthz")
    assert resp.status_code == 503
    assert resp.json()["status"] == "unhealthy"


def test_settings_default_to_localhost(monkeypatch):
    monkeypatch.delenv("SENSEBENCH_HOST", raising=False)
    assert Settings(_env_file=None).host == "127.0.0.1"
