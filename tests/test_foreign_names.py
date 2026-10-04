from src.foreign_team_names import to_english
from src.price_tip import match_fixture


def test_polish_and_german_names_become_english():
    assert to_english("Grecja") == "Greece" and to_english("Niemcy") == "Germany"
    assert to_english("Azerbejdżan") == "Azerbaijan" and to_english("Wyspy Owcze") == "Faroe Islands"
    assert to_english("Österreich") == "Austria"
    assert to_english("Bayern München") == "Bayern München"     # unknown names pass through


def test_a_fixture_stored_in_polish_still_pairs_with_the_english_event():
    fixture = {"sport_key": "soccer_uefa_nations_league", "home_team": "Grecja", "away_team": "Niemcy",
               "commence_time": "2026-10-04T18:45:00.000Z"}
    other = {**fixture, "home_team": "Walia", "away_team": "Dania"}
    event = {"sport_key": "soccer_uefa_nations_league", "home_team": "Greece", "away_team": "Germany",
             "commence_time": "2026-10-04T18:45:00Z"}
    assert match_fixture(event, [other, fixture]) is fixture


def test_the_same_match_read_twice_under_two_languages_takes_the_newer_read():
    old = {"sport_key": "soccer_uefa_nations_league", "home_team": "Walia", "away_team": "Dania",
           "commence_time": "2026-10-04T18:45:00.000Z", "fetched_at": "2026-10-04T06:01:00+00:00"}
    new = {**old, "home_team": "Wales", "away_team": "Denmark", "fetched_at": "2026-10-04T17:52:00+00:00"}
    event = {"sport_key": "soccer_uefa_nations_league", "home_team": "Wales", "away_team": "Denmark",
             "commence_time": "2026-10-04T18:45:00Z"}
    assert match_fixture(event, [old, new]) is new
