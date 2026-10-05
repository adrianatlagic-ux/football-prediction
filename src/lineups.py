"""How strong the eleven that actually starts is, against the best eleven the
squad could field - and what that does to the prediction.

The models barely react to squad value: the national one was trained with a
single, current value per nation and never saw a weaker squad lose more, so
a third of Germany's value moved its win chance by four points. Germany then
started against Greece with 47% of its best eleven's value (Wirtz on the
bench) and lost. This measures that gap an hour before kickoff and applies
it explicitly.

  line-up   ESPN's match summary lists the starters about an hour before
            kickoff (public JSON, the same source as results and fixtures)
  values    the season's squad from Transfermarkt via Apify, cached a week
            (src/squad_data.cached_squads)
  share     value of the starting eleven / value of the best eleven the squad
            could field (best goalkeeper + ten best outfield players)
  effect    how a ratio of squad values moves results, fitted on 9,012 club
            matches with season values (fit_value_effect): the win chances
            shift by BETA per unit of log value ratio. The prediction is moved
            by the change from full strength to the actual line-ups:
            delta = BETA * (log share_home - log share_away)

Transferring a club relationship to national teams, and squad value to
line-up value, are assumptions; every adjusted prediction keeps its numbers
before the line-up so the effect can be checked against results.
"""
from __future__ import annotations

import json
import math
import unicodedata
import urllib.request
from datetime import datetime
from typing import Optional

# Fitted by fit_value_effect() on club matches 2011-12..2026-27 with season
# squad values: log-odds of a win per unit of log(home value / away value).
BETA = 0.492
# A side whose starters cannot mostly be found in the squad is left alone.
MIN_MATCHED = 8
# The bench counts too, by playing time: up to five substitutes come on, for
# about 25 of 90 minutes each, so each of the five most valuable substitutes
# counts at 25/90 of a starter. Players not in the matchday squad count zero.
BENCH_PLAYERS = 5
BENCH_WEIGHT = 25 / 90
ESPN_LEAGUE = {"nations_league": "uefa.nations", "bundesliga": "ger.1", "champions_league": "uefa.champions"}


# Letters NFKD does not break into base letter + accent; dropping them would
# turn "Færø" into "Fr" and miss the player.
_TRANSLIT = str.maketrans({"ø": "o", "Ø": "O", "æ": "ae", "Æ": "Ae", "ß": "ss", "đ": "d", "Đ": "D",
                           "ł": "l", "Ł": "L", "ı": "i", "œ": "oe", "Œ": "Oe", "ð": "d", "Ð": "D",
                           "þ": "th", "Þ": "Th"})
# ESPN's names for nations that share no word with ours.
ESPN_ALIASES = {"turkiye": "turkey", "czechia": "czech republic"}


def _norm(name: str) -> str:
    name = (name or "").translate(_TRANSLIT)
    return unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode().lower().replace("-", " ").strip()


def _team_words(name: str) -> set:
    n = _norm(name)
    return {w for w in ESPN_ALIASES.get(n, n).split() if len(w) > 2}


def _get(url: str) -> dict:
    # No User-Agent: ESPN refuses a spoofed browser one (see api/app.py).
    with urllib.request.urlopen(url, timeout=15) as response:
        return json.loads(response.read())


def fetch_starters(competition: str, home: str, away: str, kickoff: datetime,
                   why: Optional[dict] = None) -> Optional[dict]:
    """{"home": [starters], "away": [...], "bench": {"home": [...], "away": [...]}}
    once ESPN lists both elevens, else None - and then, if `why` is given,
    why["reason"] says whether ESPN has no such match or no line-ups yet."""
    why = why if why is not None else {}
    league = ESPN_LEAGUE.get(competition)
    if not league:
        why["reason"] = "no ESPN league"
        return None
    board = _get(f"https://site.api.espn.com/apis/site/v2/sports/soccer/{league}/scoreboard"
                 f"?dates={kickoff.strftime('%Y%m%d')}")
    event = None
    for e in board.get("events", []):
        sides = {c["homeAway"]: c["team"]["displayName"] for c in e["competitions"][0]["competitors"]}
        if _team_words(home) & _team_words(sides.get("home", "")) and \
                _team_words(away) & _team_words(sides.get("away", "")):
            event = e
            break
    if not event:
        why["reason"] = "match not found at ESPN"
        return None
    summary = _get(f"https://site.api.espn.com/apis/site/v2/sports/soccer/{league}/summary?event={event['id']}")
    out, bench = {}, {}
    for roster in summary.get("rosters", []):
        players = roster.get("roster", [])
        starters = [p["athlete"]["displayName"] for p in players if p.get("starter")]
        if len(starters) >= 11:
            out[roster.get("homeAway")] = starters
            bench[roster.get("homeAway")] = [p["athlete"]["displayName"] for p in players if not p.get("starter")]
    if "home" not in out or "away" not in out:
        why["reason"] = "no line-ups at ESPN yet"
        return None
    return {**out, "bench": bench}


def _matcher(squad: list):
    by_name = {_norm(p.get("name")): p for p in squad}
    by_last = {}
    for p in squad:
        by_last.setdefault(_norm(p.get("name")).split()[-1] if p.get("name") else "", []).append(p)

    def find(name):
        n = _norm(name)
        p = by_name.get(n)
        if p is None:
            same = by_last.get(n.split()[-1] if n else "", [])
            p = same[0] if len(same) == 1 else None
        return p
    return find


def matched_count(starters: list, squad: list) -> int:
    find = _matcher(squad)
    return sum(find(n) is not None for n in starters)


def lineup_share(starters: list, squad: list, bench: Optional[list] = None) -> Optional[dict]:
    """Strength of the matchday squad against the squad's best possible one,
    or None when too few starters could be matched to the squad.

    Both sides of the ratio are counted the same way: the eleven in full,
    plus the BENCH_PLAYERS most valuable substitutes at BENCH_WEIGHT.
    """
    find = _matcher(squad)
    value = lambda p: float(p.get("marketValueEur") or 0)
    found = [p for p in (find(n) for n in starters) if p is not None]
    if len(found) < MIN_MATCHED:
        return None
    keepers = sorted((p for p in squad if "Goalkeeper" in (p.get("positionName") or "")), key=value, reverse=True)
    outfield = sorted((p for p in squad if "Goalkeeper" not in (p.get("positionName") or "")), key=value, reverse=True)
    best_eleven = keepers[:1] + outfield[:10]
    rest = sorted((p for p in squad if p not in best_eleven), key=value, reverse=True)
    best = sum(value(p) for p in best_eleven) + BENCH_WEIGHT * sum(value(p) for p in rest[:BENCH_PLAYERS])
    # Unmatched starters are counted at the squad's median value, so a missed
    # name neither inflates nor sinks the share. An unmatched substitute
    # counts nothing: a name the squad does not know is rarely a strong one.
    median = sorted(value(p) for p in squad)[len(squad) // 2] if squad else 0.0
    xi = sum(value(p) for p in found) + median * (len(starters[:11]) - len(found[:11]))
    subs = sorted((value(p) for p in (find(n) for n in (bench or [])) if p is not None), reverse=True)
    bench_value = BENCH_WEIGHT * sum(subs[:BENCH_PLAYERS])
    if best <= 0:
        return None
    return {"share": min((xi + bench_value) / best, 1.5), "xi_value": xi, "bench_value": bench_value,
            "best_value": best, "matched": len(found), "starters": starters[:11]}


RESULT_LABELS = {"H": "Home Win", "D": "Draw", "A": "Away Win"}


def adjust(prediction: dict, share_home: float, share_away: float) -> dict:
    """The prediction moved from full strength to the actual line-ups.

    Win chances shift by exp(+/-delta), the draw keeps its weight, then all
    three are renormalised. Everything derived from them is rebuilt the way
    the model builds it - the predicted result, the score matrix (rescaled to
    the new result chances), the most likely and top scores, every betting
    market, the expected goals and the game flow - so the page never shows a
    home win next to a 47% away chance.
    """
    delta = BETA * (math.log(share_home) - math.log(share_away))
    up, down = math.exp(delta), math.exp(-delta)
    h, d, a = (prediction["probability_home_win"] * up, prediction["probability_draw"],
               prediction["probability_away_win"] * down)
    total = h + d + a
    h, d, a = h / total, d / total, a / total
    result = max((("H", h), ("D", d), ("A", a)), key=lambda t: t[1])[0]
    out = {**prediction, "probability_home_win": round(h, 4), "probability_draw": round(d, 4),
           "probability_away_win": round(a, 4), "prediction": result, "prediction_label": RESULT_LABELS[result],
           "lineup_delta": round(delta, 4)}
    sp = prediction.get("score_prediction") or {}
    if sp.get("score_matrix"):
        out["score_prediction"] = _rebuild_scores(sp, prediction.get("home_team", "Home"), prediction.get("away_team", "Away"),
                                                  h, d, a, result,
                                                  keep_scenario=result == prediction.get("prediction"))
        try:
            from src.game_flow import predict_game_flow
            new = out["score_prediction"]
            out["game_flow"] = predict_game_flow(new["home_xg"], new["away_xg"], prediction.get("home_team", "Home"),
                                                 prediction.get("away_team", "Away"), final_score=new["most_likely_score"])
        except Exception:
            pass
    return out


def _rebuild_scores(sp: dict, home: str, away: str, h: float, d: float, a: float, result: str,
                    keep_scenario: bool, top_n: int = 5) -> dict:
    """The score prediction for new result chances, built as the model builds it."""
    import numpy as np

    from src.poisson_model import _rescale_to_target_result_probs, compute_betting_markets
    matrix = _rescale_to_target_result_probs(np.array(sp["score_matrix"], dtype=float), h, d, a)
    rows, cols = matrix.shape
    flat = sorted(((float(matrix[i, j]), i, j) for i in range(rows) for j in range(cols)), reverse=True)
    all_scorelines = [{"score": f"{i}:{j}", "probability": round(p, 4),
                       "result": "H" if i > j else "A" if j > i else "D"} for p, i, j in flat]
    markets = compute_betting_markets(all_scorelines, home, away, h, d, a)
    old_markets = sp.get("betting_markets") or {}
    # The written scenario stays when the predicted result did not change;
    # otherwise it would describe the other team winning.
    if keep_scenario and old_markets.get("scenario") and old_markets.get("scenario_lang") == markets.get("scenario_lang"):
        markets["scenario"] = old_markets["scenario"]
    matching = [s for s in all_scorelines if s["result"] == result] or all_scorelines
    return {**sp,
            "home_xg": round(float((matrix.sum(axis=1) * np.arange(rows)).sum()), 2),
            "away_xg": round(float((matrix.sum(axis=0) * np.arange(cols)).sum()), 2),
            "most_likely_score": matching[0]["score"], "result": result,
            "probability_home_win": round(h, 4), "probability_draw": round(d, 4), "probability_away_win": round(a, 4),
            "top_scorelines": [{"score": s["score"], "probability": s["probability"]} for s in matching[:top_n]],
            "betting_markets": markets, "score_matrix": matrix.tolist()}


def fit_value_effect() -> float:
    """Refit BETA on club matches with season squad values (for reference)."""
    import csv
    from pathlib import Path

    import numpy as np
    from scipy.optimize import minimize

    from scripts.build_club_training_data import _canon
    from src.club_data_loader import load_completed_matches
    root = Path(__file__).resolve().parents[1]
    values = {}
    with (root / "data" / "club_market_values_history.csv").open(encoding="utf-8") as fh:
        for r in csv.DictReader(fh):
            values[(int(r["season_start_year"]), _canon(r["team"]))] = float(r["market_value"])
    xs, ys = [], []
    for r in load_completed_matches().itertuples():
        season = r.date.year if r.date.month >= 7 else r.date.year - 1
        a, b = values.get((season, r.home_team)), values.get((season, r.away_team))
        if a and b:
            xs.append(math.log(a / b))
            ys.append(0 if r.home_goals > r.away_goals else 1 if r.home_goals == r.away_goals else 2)
    x, y = np.array(xs), np.array(ys)

    def nll(t):
        lh, la = t[0] + t[2] * x, t[1] - t[2] * x
        z = np.log(np.exp(lh) + 1 + np.exp(la))
        return -(np.where(y == 0, lh, np.where(y == 1, 0, la)) - z).sum()

    return float(minimize(nll, [0.3, -0.2, 0.5]).x[2])
