"""Squad reading, and which absences actually keep a player off the pitch.

The competition-scope test exists because the first rehearsal got it wrong:
it marked four Dortmund players out of a Bundesliga fixture over a DFB-Pokal
red card and three Champions League registration gaps, none of which stops
anyone playing in the league. That is 6.2% of a squad's value invented, and
it would have gone into the log looking authoritative.
"""
from datetime import date

import pytest

from src.competitions import COMPETITIONS, get
from src.squad_data import (
    active_absences, covers, is_competition_bound, resolve_names, summarise)

MATCHDAY = date(2026, 9, 26)
DFB_BAN = {"name": "Red card suspension", "competitionId": "DFB",
           "start": "2026-08-23", "end": "2026-10-29"}
CL_GAP = {"name": "No eligibility", "competitionId": "CL",
          "start": "2026-09-03", "end": "2027-01-28"}
LEAGUE_BAN = {"name": "Yellow card suspension", "competitionId": "L1",
              "start": "2026-09-20", "end": "2026-09-30"}
INJURY = {"name": "Muscle injury", "competitionId": None,
          "start": "2026-09-01", "end": None}


def player(pid, name, value, records=()):
    return {"id": pid, "name": name, "marketValueEur": value,
            "positionName": "Centre-Forward", "injuries": list(records)}


def test_open_ended_record_is_current():
    assert covers(INJURY, MATCHDAY)


def test_record_that_has_ended_is_not_current():
    assert not covers({"start": "2026-05-10", "end": "2026-08-25"}, MATCHDAY)


def test_record_without_a_start_is_ignored_not_assumed():
    assert not covers({"name": "x", "start": None, "end": None}, MATCHDAY)


def test_eligibility_gap_counts_as_competition_bound():
    """Not being registered for a squad is as competition-specific as a ban."""
    assert is_competition_bound(CL_GAP)
    assert is_competition_bound(DFB_BAN)
    assert not is_competition_bound(INJURY)


@pytest.mark.parametrize("competition,expected", [
    ("bundesliga", {"Yellow card suspension", "Muscle injury"}),
    ("champions_league", {"No eligibility", "Muscle injury"}),
    ("nations_league", {"Muscle injury"}),
])
def test_absences_only_count_in_the_competition_that_issued_them(competition, expected):
    subject = player("1", "A", 1, [DFB_BAN, CL_GAP, LEAGUE_BAN, INJURY])
    found = {r["name"] for r in active_absences(subject, MATCHDAY, get(competition))}
    assert found == expected


def test_injury_travels_to_every_competition():
    subject = player("1", "A", 1, [INJURY])
    for competition in COMPETITIONS.values():
        assert active_absences(subject, MATCHDAY, competition), competition.key


def test_names_resolve_by_full_name_and_by_surname():
    squad = [player("1", "Rasmus Højlund", 60), player("2", "Morten Hjulmand", 45)]
    matched, unmatched = resolve_names(squad, ["Rasmus Højlund", "Hjulmand"])
    assert [p["name"] for p in matched] == ["Rasmus Højlund", "Morten Hjulmand"]
    assert unmatched == []


def test_a_name_not_in_the_squad_is_reported_not_silently_dropped():
    """The signal that catches an agent inventing players."""
    squad = [player("1", "Rasmus Højlund", 60)]
    matched, unmatched = resolve_names(squad, ["Erik Nonexistent"])
    assert matched == []
    assert unmatched == ["Erik Nonexistent"]


def test_ambiguous_surname_does_not_guess():
    squad = [player("1", "Karim Adeyemi", 30), player("2", "Jamal Adeyemi", 5)]
    _, unmatched = resolve_names(squad, ["Adeyemi"])
    assert unmatched == ["Adeyemi"]


def test_absent_value_share_prices_the_reported_withdrawals():
    squad = [player("1", "Star", 60_000_000), player("2", "Rest", 40_000_000)]
    result = summarise(squad, get("nations_league"), absent_names=["Star"], as_of=MATCHDAY)
    assert result["squad_value_eur"] == 100_000_000
    assert result["available_value_eur"] == 40_000_000
    assert result["absent_value_share"] == 0.6


def test_club_absences_need_no_research_agent():
    """Club leagues have an injury page, so the log survives a failed AI call."""
    squad = [player("1", "Injured", 50_000_000, [INJURY]),
             player("2", "Fit", 50_000_000)]
    result = summarise(squad, get("bundesliga"), absent_names=(), as_of=MATCHDAY)
    assert result["absent_value_share"] == 0.5
    assert result["absent_players"][0]["reason"] == "Muscle injury"


def test_national_squads_ignore_club_bans_entirely():
    squad = [player("1", "Banned at his club", 50_000_000, [LEAGUE_BAN]),
             player("2", "Fit", 50_000_000)]
    result = summarise(squad, get("nations_league"), as_of=MATCHDAY)
    assert result["absent_value_share"] == 0.0


def test_oversized_national_list_is_flagged_as_a_pool():
    """Germany lists 43 - the wider pool, not the 25-29 actually called up."""
    pool = [player(str(i), f"P{i}", 1_000_000) for i in range(40)]
    assert summarise(pool, get("nations_league"), as_of=MATCHDAY)["is_pool_not_callup"]
    assert not summarise(pool, get("bundesliga"), as_of=MATCHDAY)["is_pool_not_callup"]


def test_every_club_competition_declares_its_transfermarkt_code():
    for competition in COMPETITIONS.values():
        if competition.has_injury_page:
            assert competition.transfermarkt_code, competition.key
        else:
            # Without a code, no competition-bound record can ever match.
            assert competition.transfermarkt_code is None


PAGE_INJURY = {"name": "Adductor pain", "competitionId": None,
               "start": "2026-09-18", "end": None}
PAGE_BAN = {"name": "Red card suspension", "competitionId": None,
            "start": "2026-09-20", "end": "2026-10-05"}


def test_an_injury_read_from_the_club_page_counts_everywhere():
    """These records carry no competition, and an injury needs none."""
    subject = player("1", "A", 1, [PAGE_INJURY])
    for key in ("bundesliga", "champions_league", "nations_league"):
        assert active_absences(subject, MATCHDAY, get(key)), key


def test_a_ban_without_a_competition_rules_nobody_out():
    """We cannot read which competition issued it, so we do not guess.

    Guessing wrong in this direction removes a player who will be on the
    pitch - the mistake that put four Dortmund men out of a league fixture.
    """
    subject = player("1", "A", 1, [PAGE_BAN])
    for key in ("bundesliga", "champions_league"):
        assert active_absences(subject, MATCHDAY, get(key)) == [], key


def test_an_injured_player_is_subtracted_from_a_club_squad_value():
    """What the whole club path exists to do: Bayern minus its injured man."""
    squad = [player("1", "Fit", 200_000_000), player("2", "Hurt", 34_000_000, [PAGE_INJURY])]
    result = summarise(squad, get("bundesliga"), as_of=MATCHDAY)
    assert result["available_value_eur"] == 200_000_000
    assert result["absent_players"][0]["reason"] == "Adductor pain"


def test_every_competition_with_an_injury_page_can_be_asked_for_one():
    """A club competition must carry the id its absence page is fetched by."""
    for competition in COMPETITIONS.values():
        if competition.has_injury_page:
            assert competition.odds_sport_key, competition.key
