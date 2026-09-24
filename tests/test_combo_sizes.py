from src.combo_ticket import day_reports
from tests.test_combo_ticket import leg


def legs(count, odds=1.6, book="Book"):
    return [leg(f"Home{i}", f"Away{i}", .8 - i*.02, odds, .7-i*.02,
                bookmaker=book) for i in range(count)]


def test_best_ticket_is_reported_for_every_size():
    day = day_reports(legs(5))[0]
    assert day["recommended"]["leg_count"] == 2
    assert [o["leg_count"] for o in day["by_size"]] == [2, 3, 4]
    for option in day["by_size"]:
        size = option["leg_count"]
        assert option["ticket"]["leg_count"] == size
        assert {l["home_team"] for l in option["ticket"]["legs"]} == {f"Home{i}" for i in range(size)}
        assert option["reason"] is None


def test_missing_size_has_an_explanation_not_a_shorter_ticket():
    day = day_reports(legs(2))[0]
    assert day["by_size"][0]["ticket"] is not None
    for option in day["by_size"][1:]:
        assert option["ticket"] is None
        assert f'{option["leg_count"]}-fold' in option["reason"]


def test_three_fold_is_visible_even_when_two_fold_misses_minimum_odds():
    day = day_reports(legs(3, odds=1.3))[0]
    assert day["by_size"][0]["ticket"] is None
    assert day["by_size"][1]["ticket"]["combined_odds"] == 2.2
    assert day["by_size"][2]["ticket"] is None


def test_size_options_do_not_mix_bookmakers_to_fill_slots():
    pool = legs(2, book="X") + [dict(l, home_team="Other"+l["home_team"], away_team="Other"+l["away_team"])
                                 for l in legs(2, book="Y")]
    day = day_reports(pool)[0]
    assert day["eligible_legs"] == 4
    assert day["by_size"][0]["ticket"] is not None
    assert day["by_size"][1]["ticket"] is None
    assert day["by_size"][2]["ticket"] is None


def test_options_respect_requested_maximum_and_empty_matchdays():
    assert len(day_reports(legs(4), max_legs=3)[0]["by_size"]) == 2
    empty = day_reports([], all_days=["2026-09-24"])[0]
    assert [o["leg_count"] for o in empty["by_size"]] == [2,3,4]
    assert all(o["ticket"] is None and o["reason"] for o in empty["by_size"])
