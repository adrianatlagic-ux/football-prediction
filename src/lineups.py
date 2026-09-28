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
ESPN_LEAGUE = {"nations_league": "uefa.nations", "bundesliga": "ger.1", "champions_league": "uefa.champions"}


def _norm(name: str) -> str:
    return unicodedata.normalize("NFKD", name or "").encode("ascii", "ignore").decode().lower().replace("-", " ").strip()


def _get(url: str) -> dict:
    # No User-Agent: ESPN refuses a spoofed browser one (see api/app.py).
    with urllib.request.urlopen(url, timeout=15) as response:
        return json.loads(response.read())


def fetch_starters(competition: str, home: str, away: str, kickoff: datetime) -> Optional[dict]:
    """{"home": [names], "away": [names]} once ESPN lists both elevens, else None."""
    league = ESPN_LEAGUE.get(competition)
    if not league:
        return None
    board = _get(f"https://site.api.espn.com/apis/site/v2/sports/soccer/{league}/scoreboard"
                 f"?dates={kickoff.strftime('%Y%m%d')}")
    words = lambda n: {w for w in _norm(n).split() if len(w) > 2}
    event = None
    for e in board.get("events", []):
        sides = {c["homeAway"]: c["team"]["displayName"] for c in e["competitions"][0]["competitors"]}
        if words(home) & words(sides.get("home", "")) and words(away) & words(sides.get("away", "")):
            event = e
            break
    if not event:
        return None
    summary = _get(f"https://site.api.espn.com/apis/site/v2/sports/soccer/{league}/summary?event={event['id']}")
    out = {}
    for roster in summary.get("rosters", []):
        starters = [p["athlete"]["displayName"] for p in roster.get("roster", []) if p.get("starter")]
        if len(starters) >= 11:
            out[roster.get("homeAway")] = starters
    return out if "home" in out and "away" in out else None


def lineup_share(starters: list, squad: list) -> Optional[dict]:
    """Value of the starters against the squad's best eleven, or None when too
    few starters could be matched to the squad."""
    by_name = {_norm(p.get("name")): p for p in squad}
    by_last = {}
    for p in squad:
        by_last.setdefault(_norm(p.get("name")).split()[-1] if p.get("name") else "", []).append(p)
    found = []
    for name in starters:
        n = _norm(name)
        p = by_name.get(n)
        if p is None:
            same = by_last.get(n.split()[-1] if n else "", [])
            p = same[0] if len(same) == 1 else None
        if p is not None:
            found.append(p)
    if len(found) < MIN_MATCHED:
        return None
    value = lambda p: float(p.get("marketValueEur") or 0)
    keepers = sorted((p for p in squad if "Goalkeeper" in (p.get("positionName") or "")), key=value, reverse=True)
    outfield = sorted((p for p in squad if "Goalkeeper" not in (p.get("positionName") or "")), key=value, reverse=True)
    best = sum(value(p) for p in keepers[:1] + outfield[:10])
    # Unmatched starters are counted at the squad's median value, so a missed
    # name neither inflates nor sinks the share.
    median = sorted(value(p) for p in squad)[len(squad) // 2] if squad else 0.0
    xi = sum(value(p) for p in found) + median * (len(starters[:11]) - len(found[:11]))
    if best <= 0:
        return None
    return {"share": min(xi / best, 1.5), "xi_value": xi, "best_xi_value": best,
            "matched": len(found), "starters": starters[:11]}


def adjust(prediction: dict, share_home: float, share_away: float) -> dict:
    """The prediction moved from full strength to the actual line-ups.

    Win chances shift by exp(+/-delta), the draw keeps its weight, then all
    three are renormalised; the score matrix is shifted the same way so the
    goals markets stay consistent with the result markets.
    """
    delta = BETA * (math.log(share_home) - math.log(share_away))
    up, down = math.exp(delta), math.exp(-delta)
    h, d, a = (prediction["probability_home_win"] * up, prediction["probability_draw"],
               prediction["probability_away_win"] * down)
    total = h + d + a
    out = {**prediction, "probability_home_win": round(h / total, 4), "probability_draw": round(d / total, 4),
           "probability_away_win": round(a / total, 4)}
    sp = prediction.get("score_prediction") or {}
    matrix = sp.get("score_matrix")
    if matrix:
        scaled = [[p * (up if i > j else down if j > i else 1.0) for j, p in enumerate(row)]
                  for i, row in enumerate(matrix)]
        s = sum(map(sum, scaled))
        out["score_prediction"] = {**sp, "score_matrix": [[p / s for p in row] for row in scaled]}
    out["lineup_delta"] = round(delta, 4)
    return out


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
