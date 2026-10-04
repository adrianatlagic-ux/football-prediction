"""Do handicaps on the underdog lose more often than the market says?

    python3 scripts/underdog_handicap_test.py

The 🎯 pick and the market combo rule kept choosing big handicaps on the
weaker side (San Marino +3.5, Croatia +1.5, North Macedonia +1.5) at 70-75%
by the market's price, and they kept losing. Two looks:

  live      every logged bet (data/bet_log.jsonl, Nations League) graded
            against the result, grouped by kind of bet: hits against what
            bet-at-home's margin-free price expected
  history   Nations League 2020-21, 2022-23, 2024-25 (OddsPortal average
            1X2 prices, margin removed): for favourites of each strength,
            how often they won by two or more - the share an underdog +1.5
            loses - set against what a Poisson goal model with those 1X2
            chances expects. If favourites run up scores more often than the
            1X2 price implies, +1.5 on the underdog is priced too short.

Writes data/model_reports/underdog_handicap_20261004.json.
"""
from __future__ import annotations

import json
import math
import sys
import urllib.request
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from grade_bets import _game_pick, _norm, competition_of, grade  # noqa: E402

OUT = ROOT / "data" / "model_reports" / "underdog_handicap_20261004.json"
ARCHIVE = ROOT / "data" / "odds_archive" / "oddsportal_nl_20260927"


def kind(bet, underdog):
    m, team = bet["market"], bet.get("team")
    if m.startswith("Handicap ") and team:
        line = float(m.split()[-1])
        side = "Außenseiter" if team == underdog else "Favorit"
        if line == 0:
            return f"{side} DNB"
        return f"{side} {line:+.1f}".replace(".", ",")
    if m.startswith("Over/Under"):
        return f"Tore {bet['outcome'].lower()}"
    if m == "BTTS":
        return "Beide treffen"
    if m == "1X2":
        return "1X2 Remis" if bet["outcome"] == "draw" else ("1X2 Außenseiter" if team == underdog else "1X2 Favorit")
    return m


def live(api: str) -> dict:
    results = json.load(urllib.request.urlopen(f"{api}/real-results", timeout=60))["results"]
    finished = {(_norm(r["home_team"]), _norm(r["away_team"]), str(r.get("commence_time"))[:10]): r
                for r in results if r.get("completed") and r.get("home_score") is not None}
    groups = defaultdict(lambda: {"n": 0, "won": 0, "expected": 0.0, "units": 0.0})
    for line in (ROOT / "data" / "bet_log.jsonl").read_text(encoding="utf-8").splitlines():
        e = json.loads(line)
        if competition_of(e) != "Nations League":
            continue
        r = finished.get((_norm(e["home_team"]), _norm(e["away_team"]), str(e.get("commence_time"))[:10]))
        if not r:
            continue
        bets = e.get("green_bets", []) + e.get("red_bets", [])
        # The underdog by the market: the other side of the Game Pick (the
        # market favourite's 1X2 win); not every entry logs both 1X2 prices.
        fav = (_game_pick(e) or {}).get("team")
        if fav not in (e["home_team"], e["away_team"]):
            continue
        underdog = e["away_team"] if fav == e["home_team"] else e["home_team"]
        for b in bets:
            p = b.get("market_probability")
            if p is None:
                continue
            g = grade(b, e["home_team"], e["away_team"], r["home_score"], r["away_score"])
            if g not in ("win", "loss"):
                continue
            s = groups[kind(b, underdog)]
            s["n"] += 1
            s["won"] += g == "win"
            s["expected"] += p
            s["units"] += (b["best_odds"] - 1) if g == "win" else -1
    out = {}
    for k, s in sorted(groups.items(), key=lambda kv: -kv[1]["n"]):
        n = s["n"]
        sd = math.sqrt(n * (s["expected"] / n) * (1 - s["expected"] / n)) if n else 0
        out[k] = {"n": n, "hit": round(s["won"] / n, 3), "market_expected": round(s["expected"] / n, 3),
                  "roi": round(s["units"] / n, 3),
                  "z": round((s["won"] - s["expected"]) / sd, 2) if sd else None}
    return out


def _poisson_margin2(p_home, p_draw, p_away):
    """P(favourite wins by 2+) for the goal rates that reproduce these 1X2
    chances (independent Poisson, total goals fitted to the draw chance)."""
    best = None
    fav_home = p_home >= p_away
    target = (max(p_home, p_away), p_draw)
    for total in [x / 10 for x in range(15, 45)]:
        for share in [x / 100 for x in range(50, 96)]:
            lf, lu = total * share, total * (1 - share)
            pf = [math.exp(-lf) * lf ** k / math.factorial(k) for k in range(12)]
            pu = [math.exp(-lu) * lu ** k / math.factorial(k) for k in range(12)]
            win = sum(pf[i] * pu[j] for i in range(12) for j in range(12) if i > j)
            draw = sum(pf[i] * pu[i] for i in range(12))
            err = (win - target[0]) ** 2 + (draw - target[1]) ** 2
            if best is None or err < best[0]:
                by2 = sum(pf[i] * pu[j] for i in range(12) for j in range(12) if i - j >= 2)
                best = (err, by2)
    return best[1]


def history() -> dict:
    buckets = [(0.45, 0.55), (0.55, 0.65), (0.65, 0.75), (0.75, 0.85), (0.85, 1.0)]
    groups = {b: {"n": 0, "by2": 0, "poisson": 0.0} for b in buckets}
    for path in sorted(ARCHIVE.glob("nl_*.json")):
        for m in json.load(path.open()):
            o = m.get("odds") or {}
            try:
                avg = [float(o[k]["average"]) for k in ("home", "draw", "away")]
                hs, as_ = (int(x) for x in str(m["result"]).split(":")[:2])
            except (KeyError, TypeError, ValueError):
                continue
            inv = [1 / x for x in avg]
            ph, pd, pa = (x / sum(inv) for x in inv)
            fav_p = max(ph, pa)
            margin = (hs - as_) if ph >= pa else (as_ - hs)
            b = next((b for b in buckets if b[0] <= fav_p < b[1]), None)
            if not b:
                continue
            g = groups[b]
            g["n"] += 1
            g["by2"] += margin >= 2
            g["poisson"] += _poisson_margin2(ph, pd, pa)
    return {f"{lo:.0%}-{hi:.0%}": {"n": g["n"], "fav_won_by_2plus": round(g["by2"] / g["n"], 3) if g["n"] else None,
                                   "poisson_expected": round(g["poisson"] / g["n"], 3) if g["n"] else None}
            for (lo, hi), g in groups.items()}


def main():
    report = {"live": live("https://football-prediction.fly.dev"), "history": history()}
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(report, indent=1, ensure_ascii=False) + "\n")
    print("LIVE (Nations League, alle geloggten Wetten)")
    for k, v in report["live"].items():
        print(f"  {k:22} n={v['n']:4}  getroffen {v['hit']:.0%}  Markt erwartet {v['market_expected']:.0%}  "
              f"ROI {v['roi']:+.0%}  z={v['z']}")
    print("\nGESCHICHTE (Nations League 2020-21, 2022-23, 2024-25): Favorit gewinnt mit 2+ Toren")
    for k, v in report["history"].items():
        print(f"  Favorit {k:8} n={v['n']:4}  tatsächlich {v['fav_won_by_2plus']:.0%}  "
              f"Poisson aus 1X2 erwartet {v['poisson_expected']:.0%}")
    print(f"geschrieben: {OUT.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
