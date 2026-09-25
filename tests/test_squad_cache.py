import json
from datetime import datetime, timedelta, timezone

from src import squad_data


def test_squads_are_fetched_once_until_they_go_stale(tmp_path, monkeypatch):
    monkeypatch.setattr(squad_data, "SQUAD_CACHE_DIR", tmp_path)
    calls = []

    def fake_fetch(ids, with_injuries=True, token=None):
        calls.append(list(ids))
        return {i: [{"id": 1, "name": "X", "marketValueEur": 5, "positionName": "Goalkeeper",
                     "extra": "dropped"}] for i in ids}

    monkeypatch.setattr(squad_data, "fetch_squads", fake_fetch)
    now = datetime(2026, 9, 25, tzinfo=timezone.utc)
    ttl = timedelta(days=7)
    first = squad_data.cached_squads(["27", "16"], ttl, now=now)
    again = squad_data.cached_squads(["27", "16"], ttl, now=now + timedelta(days=6))
    assert calls == [["27", "16"]]
    assert first == again and "extra" not in first["27"][0]
    squad_data.cached_squads(["27", "5"], ttl, now=now + timedelta(days=8))
    assert calls[-1] == ["27", "5"]
    assert json.loads((tmp_path / "5.json").read_text())["players"][0]["marketValueEur"] == 5
