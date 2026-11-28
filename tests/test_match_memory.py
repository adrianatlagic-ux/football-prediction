"""The AI's memory of its own tips and the shadow agent that reads it."""
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

from src import match_memory

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

NL = "soccer_uefa_nations_league"


def _entry(home, away, day, score=(2, 1), market="1X2", outcome="home_win", team=None, sport=NL):
    pick = {"market": market, "outcome": outcome, "team": team or home, "best_odds": 1.8}
    return {"home_team": home, "away_team": away, "commence_time": f"{day}T19:45:00Z", "sport_key": sport,
            "competition": "Nations League", "result": {"home_score": score[0], "away_score": score[1]},
            "agent_eval": {"pick": pick, "bet_reasoning": "Alpha ist stärker.", "research": {"form": "gut"}}}


def _case(entry, **extra):
    return {"id": match_memory.case_id(entry), "sport_key": entry["sport_key"], "competition": entry["competition"],
            "commence_time": entry["commence_time"], "home_team": entry["home_team"],
            "away_team": entry["away_team"], "score": "2:1", "tip": "1X2 Alpha @1.8", "tip_market": "1X2",
            "outcome": "win", "arguments": [{"argument": "Alpha stärker", "came_true": "yes", "why": "2:1"}],
            "luck_or_reasoning": "reasoning", "luck_explanation": "verdient", "what_decided": "Standards",
            "how_it_went": "Alpha dominierte.", **extra}


def test_each_team_gets_its_own_earlier_cases():
    cases = [_case(_entry("Alpha", "Bravo", "2026-10-01")), _case(_entry("Charlie", "Alpha", "2026-10-04")),
             _case(_entry("Delta", "Echo", "2026-10-04")), _case(_entry("Alpha", "Delta", "2026-11-20"))]
    alpha = match_memory.team_cases("Alpha", "2026-11-14T19:45:00Z", cases)
    assert [c["away_team"] for c in alpha] == ["Bravo", "Alpha"]          # not the later match, not Delta-Echo
    block, ids = match_memory.prompt_block("Alpha", "Foxtrot", "2026-11-14T19:45:00Z", cases)
    assert len(ids) == 2 and "Foxtrot (oldest first):\n(no earlier tips)" in block
    assert "Alpha stärker -> yes: 2:1" in block and "list it in memory_used" in block


def test_no_block_when_neither_team_has_a_case():
    cases = [_case(_entry("Alpha", "Bravo", "2026-10-01"))]
    assert match_memory.prompt_block("Golf", "Hotel", "2026-11-14", cases) == ("", [])


def test_update_reviews_each_finished_tip_once(tmp_path):
    entries = [_entry("Alpha", "Bravo", "2026-10-01"), _entry("Charlie", "Delta", "2026-10-02"),
               {**_entry("Echo", "Foxtrot", "2026-10-03"), "result": None},           # not finished
               {**_entry("Golf", "Hotel", "2026-10-03"), "agent_eval": {"pick": None}}]  # no AI pick
    seen = []

    def fake_review(e):
        seen.append(e["home_team"])
        return _case(e)

    report = match_memory.update(entries, folder=tmp_path, review_one=fake_review, workers=1)
    assert report["added"] == 2 and sorted(seen) == ["Alpha", "Charlie"]
    assert (tmp_path / "nations-league.jsonl").exists()
    assert match_memory.update(entries, folder=tmp_path, review_one=fake_review)["due"] == 0


def test_espn_facts_reads_stats_and_goals():
    pages = {
        "scoreboard": {"events": [{"id": "9", "competitions": [{"competitors": [
            {"homeAway": "home", "team": {"displayName": "Alpha"}},
            {"homeAway": "away", "team": {"displayName": "Bravo"}}]}]}]},
        "summary": {"boxscore": {"teams": [
            {"team": {"displayName": "Alpha"}, "statistics": [{"name": "totalShots", "displayValue": "14"}]},
            {"team": {"displayName": "Bravo"}, "statistics": [{"name": "totalShots", "displayValue": "6"}]}]},
            "keyEvents": [{"type": {"text": "Goal"}, "clock": {"displayValue": "12'"}, "text": "Goal! Alpha 1"},
                          {"type": {"text": "Substitution"}, "clock": {"displayValue": "60'"}, "text": "sub"}]}}
    facts = match_memory.espn_facts(_entry("Alpha", "Bravo", "2026-10-01"),
                                    get=lambda url: pages["summary" if "summary" in url else "scoreboard"])
    assert "Alpha: Schüsse 14" in facts and "12' Goal! Alpha 1" in facts and "sub" not in facts


def test_review_drops_an_answer_that_never_searched():
    calls = []

    class Models:
        def generate_content(self, model, contents, config):
            calls.append(contents)
            return SimpleNamespace(text="{}", usage_metadata=None,
                                   candidates=[SimpleNamespace(grounding_metadata=None)])

    case = match_memory.review(_entry("Alpha", "Bravo", "2026-10-01"), client=SimpleNamespace(models=Models()),
                               facts=lambda e: "")
    assert case is None and len(calls) == 3 and "MUST call Google Search" in calls[-1]


def test_the_shadow_prompt_carries_the_memory(monkeypatch):
    from api import app as api
    import google.genai as genai
    from tests.test_agent_prompt import ANSWER, PREDICTION, VB

    prompts = []

    class Models:
        def generate_content(self, model, contents, config):
            prompts.append(contents)
            answer = {**ANSWER, "memory_used": [{"case": "c1", "how": "Hinspiel"}]}
            return SimpleNamespace(text=json.dumps(answer), candidates=[], usage_metadata=None)

    monkeypatch.setattr(api, "GEMINI_API_KEY", "test")
    monkeypatch.setattr(genai, "Client", lambda api_key: SimpleNamespace(models=Models()))
    result = api._call_gemini_agent_pick(PREDICTION, VB, "Alpha", "Bravo", memory_block="\n\nYOUR MEMORY x",
                                         memory_cases=["c1"])
    assert prompts[0].index("YOUR MEMORY x") < prompts[0].index("STEP 1 - RESEARCH")    # read before researching
    assert '"memory_used": [' in prompts[0]
    assert result["memory_cases"] == ["c1"] and result["memory_used"][0]["case"] == "c1"
    plain = api._call_gemini_agent_pick(PREDICTION, VB, "Alpha", "Bravo")
    assert "memory_cases" not in plain and "YOUR MEMORY" not in prompts[1]


def test_the_log_takes_the_shadow_tip_only_before_kickoff():
    import log_bets
    match = {"home_team": "Alpha", "away_team": "Bravo", "commence_time": "2026-11-14T19:45:00Z",
             "sport_key": NL, "event_id": "e1", "bets": [{"market": "1X2"}], "agent_eval": {"pick": None}}
    entries = []
    log_bets.apply([match], entries, datetime(2026, 11, 14, 19, 20, tzinfo=timezone.utc))
    assert "agent_eval_shadow" not in entries[0]
    shadow = {"pick": {"market": "1X2", "outcome": "home_win", "team": "Alpha", "best_odds": 1.8}}
    log_bets.apply([{**match, "agent_eval_shadow": shadow}], entries,
                   datetime(2026, 11, 14, 19, 30, tzinfo=timezone.utc))
    assert entries[0]["agent_eval_shadow"] == shadow
    late = [{**match, "event_id": "e2", "agent_eval_shadow": shadow}]
    other = [{**late[0], "agent_eval_shadow": None}]
    log_bets.apply(other, entries, datetime(2026, 11, 14, 19, 30, tzinfo=timezone.utc))
    log_bets.apply(late, entries, datetime(2026, 11, 14, 19, 50, tzinfo=timezone.utc))
    assert "agent_eval_shadow" not in entries[1]


def test_grading_compares_the_shadow_with_the_real_tip():
    import grade_bets
    real = {"market": "1X2", "outcome": "home_win", "team": "Alpha", "best_odds": 1.5}
    other = {"market": "Over/Under 2.5", "outcome": "Over", "team": None, "best_odds": 2.0}
    entries = [{"home_team": "Alpha", "away_team": "Bravo", "commence_time": "2026-11-14T19:45:00Z", "bets": [],
                "agent_eval": {"pick": real}, "agent_eval_shadow": {"pick": shadow}}
               for shadow in (real, other)]
    entries[1]["home_team"] = "Charlie"
    real2 = {**real, "team": "Charlie"}
    entries[1]["agent_eval"]["pick"] = real2
    finished = {("alpha", "bravo", "2026-11-14"): {"home_score": 1, "away_score": 0},
                ("charlie", "bravo", "2026-11-14"): {"home_score": 3, "away_score": 1}}
    b = grade_bets.grade_entries(entries, finished)["buckets"]
    assert (b["shadow"].wins, b["shadow_real"].wins) == (2, 2)
    assert (b["shadow_diff"].decided, round(b["shadow_diff"].units, 2)) == (1, 1.0)


def test_the_memory_ships_in_the_image_and_reaches_the_volume():
    """data/logs is kept out of the image; the memory must not be."""
    root = Path(__file__).resolve().parents[1]
    ignored = [l.strip() for l in (root / ".dockerignore").read_text().splitlines()]
    assert match_memory.MEMORY.relative_to(root).as_posix() + "/" not in ignored
    assert not any(match_memory.MEMORY.relative_to(root).as_posix().startswith(i.rstrip("/") + "/") for i in ignored
                   if i and not i.startswith("#"))
    assert "data/memory" in (root / "start.sh").read_text()


def test_the_shadows_candidates_are_graded_into_the_case_and_shown_later():
    entry = _entry("Alpha", "Bravo", "2026-11-16", score=(2, 0))
    over = {"market": "Over/Under 2.5", "outcome": "Over", "team": None, "best_odds": 1.8}
    win = {"market": "1X2", "outcome": "home_win", "team": "Alpha", "best_odds": 1.5}
    entry["bets"] = [over, win]
    entry["agent_eval_shadow"] = {"pick": win, "candidates_considered": [
        {"market": "1X2", "outcome": "Alpha", "probability": 70, "reason": "stärker"},
        {"market": "Over/Under 2.5", "outcome": "Over", "probability": 60, "reason": "Tore"},
        {"market": "BTTS", "outcome": "Yes", "probability": 50, "reason": "nicht angeboten"}]}
    graded = match_memory.graded_candidates(entry)
    assert [(c["outcome"], c["result"], c["picked"]) for c in graded] == [
        ("Alpha", "win", True), ("Over", "loss", False), ("Yes", None, False)]
    case = _case(entry, candidates=graded)
    block, _ = match_memory.prompt_block("Alpha", "Charlie", "2026-11-20", [case])
    assert "1X2 Alpha (your estimate 70%) -> win" in block and "Over/Under 2.5 Over (your estimate 60%) -> loss" in block
    assert "your pick" not in block and "BTTS" not in block      # the shadow's pick is not "the tip"; unpriced bets stay out


def test_the_shadow_runs_prompt_v10_while_the_real_tip_stays_v9(monkeypatch):
    from api import app as api
    import google.genai as genai
    from tests.test_agent_prompt import ANSWER, PREDICTION, VB

    prompts = []
    answer = {**ANSWER, "candidates": [{"market": "1X2", "outcome": "Alpha", "probability": 72, "reason": "x"}]}

    class Models:
        def generate_content(self, model, contents, config):
            prompts.append(contents)
            return SimpleNamespace(text=json.dumps(answer), candidates=[], usage_metadata=None)

    monkeypatch.setattr(api, "GEMINI_API_KEY", "test")
    monkeypatch.setattr(genai, "Client", lambda api_key: SimpleNamespace(models=Models()))
    real = api._call_gemini_agent_pick(PREDICTION, VB, "Alpha", "Bravo")
    shadow = api._call_gemini_agent_pick(PREDICTION, VB, "Alpha", "Bravo", memory_block="\n\nYOUR MEMORY",
                                         memory_cases=[], prompt_version="v10")
    assert "how many goals are realistic" in prompts[0] and '"candidates"' not in prompts[0]
    assert "memory_used" not in prompts[0]
    assert "most predictable" in prompts[1] and '"candidates"' in prompts[1]
    # The favourite question sits only in the shadow's verdict, the real tip is untouched.
    assert "can score on its own" in prompts[1] and "can score on its own" not in prompts[0]
    assert real["research_version"] == "football_research_model_v9" and "candidates_considered" not in real
    assert shadow["research_version"] == "football_research_model_v10_2" and shadow["pick_probability"] == 72


def _shadow_entry(day, hs, as_, pick, own, fav=0.5):
    return {"commence_time": f"{day}T18:00:00Z", "home_team": "Alpha", "away_team": "Bravo",
            "result": {"home_score": hs, "away_score": as_},
            "agent_eval_shadow": {"pick": pick, "pick_probability": own,
                                  "research_input": {"model_context": {"probability_home_win": fav,
                                                                       "probability_away_win": 0.2}}}}


def test_the_track_record_counts_the_shadows_own_settled_picks():
    under = {"market": "Over/Under 2.5", "outcome": "Under", "best_odds": 2.0, "market_probability": 0.5}
    home = {"market": "1X2", "outcome": "home_win", "team": "Alpha", "best_odds": 1.8, "market_probability": 0.55}
    entries = [
        _shadow_entry("2026-11-20", 3, 0, under, 70, fav=0.7),   # Under with a clear favourite: lost
        _shadow_entry("2026-11-21", 2, 1, under, 60, fav=0.7),   # lost
        _shadow_entry("2026-11-22", 1, 0, under, 65, fav=0.7),   # won
        _shadow_entry("2026-11-23", 1, 0, home, 60),             # won
        _shadow_entry("2026-11-30", 0, 0, home, 60),             # after the match being tipped: left out
    ]
    block = match_memory.track_record_block("2026-11-29T00:00:00Z", entries)
    assert "- all your picks: 4 picks, 2 came in (50%); your estimate 64%; odds implied 51%" in block
    assert "- Under (goal line): 3 picks, 1 came in (33%); your estimate 65%; odds implied 50%" in block
    assert "Under when one side was a clear favourite (model win chance 60%+): 3 picks, 1 came in" in block
    assert "result (1X2)" not in block                        # fewer than three picks of that kind
    assert match_memory.track_record_block("2026-11-21T00:00:00Z", entries) == ""   # too few yet


def test_the_shadow_prompt_carries_its_track_record(monkeypatch):
    from api import app as api
    from src import match_memory as mm
    monkeypatch.setattr(mm, "prompt_block", lambda home, away, before: ("\n\nYOUR MEMORY ...", ["c1"]))
    monkeypatch.setattr(mm, "track_record_block", lambda before: "\n\nYOUR TRACK RECORD ...")
    seen = {}
    monkeypatch.setattr(api, "_call_gemini_agent_pick", lambda *a, **kw: seen.update(kw) or None)
    api._run_shadow_agent({}, {"commence_time": "2026-11-29T18:00:00Z"}, "Alpha", "Bravo", ("k",))
    assert seen["memory_block"] == "\n\nYOUR MEMORY ...\n\nYOUR TRACK RECORD ..." and seen["prompt_version"] == "v10"
