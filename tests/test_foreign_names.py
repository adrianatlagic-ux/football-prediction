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
