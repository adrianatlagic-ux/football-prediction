"""Who may replace the predictions every visitor sees.

The endpoint writes whatever it is given straight into the cache the site
serves. Unprotected, anyone who knows the URL can decide what the model
appears to have predicted. It had no check at all until the scheduled squad
refresh started relying on it, which made the exposure worth closing rather
than merely noting.

Driven through the HTTP layer rather than by calling the function: the header
default only becomes a string once FastAPI resolves it, so a direct call
tests a path no request ever takes.
"""
import importlib

import pytest
from fastapi.testclient import TestClient

PAYLOAD = {"probability_home_win": 1.0}


@pytest.fixture
def client(monkeypatch, tmp_path):
    def build(token):
        monkeypatch.setenv("PREDICTIONS_WRITE_TOKEN", token)
        import api.app as module
        module = importlib.reload(module)
        module.PREDICTIONS_CACHE_DIR = tmp_path
        module._cache_path = lambda match_id: tmp_path / f"{match_id}.json"
        return TestClient(module.app), tmp_path
    yield build
    # Leave the module as the rest of the suite expects to find it.
    monkeypatch.delenv("PREDICTIONS_WRITE_TOKEN", raising=False)
    import api.app
    importlib.reload(api.app)


def test_a_missing_token_is_refused(client):
    http, cache = client("correct-horse")
    assert http.post("/predictions/m1", json=PAYLOAD).status_code == 401
    assert not list(cache.glob("*.json")), "a refused write must leave no file"


def test_a_wrong_token_is_refused(client):
    http, cache = client("correct-horse")
    response = http.post("/predictions/m1", json=PAYLOAD,
                         headers={"X-Prediction-Token": "guess"})
    assert response.status_code == 401
    assert not list(cache.glob("*.json"))


def test_the_right_token_writes(client):
    http, cache = client("correct-horse")
    response = http.post("/predictions/m1", json=PAYLOAD,
                         headers={"X-Prediction-Token": "correct-horse"})
    assert response.status_code == 200
    assert (cache / "m1.json").exists()


def test_without_a_configured_token_writes_stay_open(client):
    """Local use keeps working; the deployment is what sets the variable."""
    http, cache = client("")
    assert http.post("/predictions/m1", json=PAYLOAD).status_code == 200
    assert (cache / "m1.json").exists()
