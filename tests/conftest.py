import pytest


@pytest.fixture(autouse=True)
def _isolated_runtime_files(tmp_path, monkeypatch):
    """Tests must never read or write the app's real odds snapshot or book files."""
    from api import app as api
    monkeypatch.setattr(api, "ODDS_SNAPSHOT_PATH", tmp_path / "odds_snapshot.json")
    monkeypatch.setenv("BOOK_ODDS_PATH", str(tmp_path / "book_odds.json"))
    # No real Apify reads from inside a test.
    monkeypatch.setattr(api, "_refresh_book_daily", lambda events: None)
    # Nor a real question to Apify about the account's spend.
    from src import apify_budget
    monkeypatch.setattr(apify_budget, "usage", lambda token=None: None)
    # The agent's cached picks go to a temporary file, never the real one.
    monkeypatch.setattr(api, "AGENT_CACHE_PATH", tmp_path / "agent_picks.json")
