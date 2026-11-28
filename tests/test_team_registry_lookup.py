from scripts import refresh_squad_predictions as rsp


def test_the_registry_finds_clubs_under_other_spellings():
    reg = rsp.Registry({"FC Augsburg": "167", "1.FSV Mainz 05": "39", "Bayer 04 Leverkusen": "15",
                        "1.FC Union Berlin": "89", "Borussia Dortmund": "16", "Borussia Mönchengladbach": "18"})
    assert reg.get("Augsburg") == "167"
    assert reg.get("1. FSV Mainz 05") == "39"
    assert reg.get("Bayer Leverkusen") == "15"
    assert reg.get("Union Berlin") == "89"
    assert reg.get("Borussia Monchengladbach") == "18"
    assert reg.get("Borussia") is None           # two clubs contain it: no guess
    assert reg.get("Lille") is None


def test_every_bundesliga_and_champions_league_fixture_team_is_in_the_registry():
    import json
    from pathlib import Path
    src = Path(__file__).resolve().parents[1] / "frontend" / "src"
    for file, comp in (("bl_fixtures.json", "bundesliga"), ("cl_fixtures.json", "champions_league")):
        reg = rsp.load_registry(comp)
        teams = {t for f in json.loads((src / file).read_text(encoding="utf-8")) for t in (f["home_team"], f["away_team"])}
        assert not [t for t in teams if not reg.get(t)], comp
