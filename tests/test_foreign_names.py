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


def _event(home, away, h, d, a, kickoff="2026-10-04T18:45:00Z", eid=None):
    return {"id": eid or home, "sport_key": "soccer_uefa_champs_league", "home_team": home, "away_team": away,
            "commence_time": kickoff, "bookmakers": [{"key": "pinnacle", "markets": [{"key": "h2h", "outcomes": [
                {"name": home, "price": h}, {"name": "Draw", "price": d}, {"name": away, "price": a}]}]}]}


def _listing(home, away, h, d, a, kickoff="2026-10-04T18:45:00.000Z"):
    return {"sport_key": "soccer_uefa_champs_league", "home_team": home, "away_team": away,
            "commence_time": kickoff, "odds": {"home": h, "draw": d, "away": a}}


def test_a_listing_with_unreadable_names_is_found_by_kickoff_and_prices():
    bayern = _event("Bayern Munich", "Inter Milan", 1.55, 4.4, 5.8)
    psg = _event("Paris Saint Germain", "Arsenal", 2.4, 3.4, 2.9)
    listings = [_listing("Бавария", "Интер", 1.53, 4.5, 6.0),
                _listing("Paris Saint Germain", "Arsenal", 2.45, 3.4, 2.85)]
    assert match_fixture(bayern, listings, [bayern, psg]) is listings[0]
    # Without the other events no guess is made.
    assert match_fixture(bayern, listings) is None


def test_no_guess_when_two_listings_price_alike_or_the_match_is_missing():
    a = _event("Alpha", "Bravo", 2.0, 3.4, 3.8)
    b = _event("Charlie", "Delta", 2.05, 3.4, 3.7)
    alike = [_listing("Альфа", "Браво", 2.0, 3.4, 3.8), _listing("Чарли", "Дельта", 2.02, 3.4, 3.75)]
    assert match_fixture(a, alike, [a, b]) is None
    # A's listing missing; B's is named and belongs to B, so it is never taken for A.
    assert match_fixture(a, [_listing("Charlie", "Delta", 2.0, 3.4, 3.8)], [a, b]) is None
