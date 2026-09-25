import pytest


@pytest.fixture(autouse=True)
def _isolated_runtime_files(tmp_path, monkeypatch):
    """Tests must never read or write the app's real odds snapshot or book files."""
    from api import app as api
    monkeypatch.setattr(api, "ODDS_SNAPSHOT_PATH", tmp_path / "odds_snapshot.json")
    monkeypatch.setenv("BOOK_ODDS_PATH", str(tmp_path / "book_odds.json"))
    # No real Apify reads from inside a test.
    monkeypatch.setattr(api, "_refresh_book_daily", lambda events: None)
