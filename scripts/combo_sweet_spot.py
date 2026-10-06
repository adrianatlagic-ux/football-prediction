"""Which leg floor and target odds suit the "agree" combo best?

    python3 scripts/combo_sweet_spot.py

Rebuilds the day's combos with the real ticket search (build_tickets) for a
grid of minimum leg probabilities (the market's, margin-free) and minimum
combined odds, then settles them. One ticket per day and size (2-, 3-,
4-fold) over all of the day's matches - the live page also rebuilds as
matches start, which this ignores.

  live     the logged Nations League bets since 28 September
           (data/logs bet_log on the server: ~9 bets a match, every market,
           bet-at-home's price, the model's view and the AI agent's pick)
  history  Nations League 2020-21 and 2024-25, 1X2 only: the national model
           trained before each season (nl_backtest cases) against
           bet-at-home's archived 1X2 price; no AI pick

Writes data/model_reports/combo_sweet_spot_20261006.json.
"""
from __future__ import annotations

import json
import sys
import urllib.request
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))
from grade_bets import _norm, grade  # noqa: E402
from src.combo_ticket import MIN_LEG_ODDS, MODEL_TOLERANCE, binary_market, build_tickets  # noqa: E402
from src.price_tip import implies  # noqa: E402

API = "https://football-prediction.fly.dev"
OUT = ROOT / "data" / "model_reports" / "combo_sweet_spot_20261006.json"
FLOORS = [0.45, 0.50, 0.55, 0.60, 0.65]
TARGETS = [2.0, 2.5, 3.0]
SIZES = [2, 3, 4]


def live_days():
    results = json.load(urllib.request.urlopen(f"{API}/real-results", timeout=60))["results"]
    finished = {(_norm(r["home_team"]), _norm(r["away_team"]), str(r.get("commence_time"))[:10]): r
                for r in results if r.get("completed") and r.get("home_score") is not None}
    text = urllib.request.urlopen(f"{API}/logs/bet_log", timeout=60).read().decode()
    legs = []
    for line in text.splitlines():
        e = json.loads(line)
        if e.get("sport_key") != "soccer_uefa_nations_league":
            continue
        r = finished.get((_norm(e["home_team"]), _norm(e["away_team"]), str(e.get("commence_time"))[:10]))
        if not r:
            continue
        pick = (e.get("agent_eval") or {}).get("pick")
        seen = set()
        for b in e.get("green_bets", []) + e.get("red_bets", []):
            key = (b["market"], b["outcome"], b.get("team"))
            if b.get("bookmaker_key") != "betathome" or key in seen or not binary_market(b["market"]):
                continue
            seen.add(key)
            g = grade(b, e["home_team"], e["away_team"], r["home_score"], r["away_score"])
            if g not in ("win", "loss") or b.get("market_probability") is None:
                continue
            legs.append({**{k: b.get(k) for k in ("market", "outcome", "team", "best_odds", "market_probability")},
                         "bookmaker": "bet-at-home", "bookmaker_key": "betathome",
                         "home_team": e["home_team"], "away_team": e["away_team"],
                         "commence_time": e["commence_time"], "sport_key": e["sport_key"],
                         "model": b.get("model_probability_raw"),
                         "ki_agrees": bool(pick and implies(pick, b, e["home_team"], e["away_team"])),
                         "won": g == "win"})
    return legs


def history_days():
    odds = {}
    for path in sorted((ROOT / "data" / "odds_archive" / "oddsportal_nl_20260927").glob("nl_*.json")):
        for m in json.load(path.open()):
            bah = next((b for b in m.get("bookmakerOdds") or [] if b.get("bookmaker") == "bet-at-home.de"), None)
            if bah:
                odds[(_norm(m["homeTeam"]), _norm(m["awayTeam"]))] = (str(m["startTime"])[:10], bah)
    legs = []
    cases = ROOT / "data" / "model_reports" / "nl_backtest_20260927" / "cases.jsonl"
    for c in map(json.loads, cases.read_text(encoding="utf-8").splitlines()):
        found = odds.get((_norm(c["home"]), _norm(c["away"])))
        if not found:
            continue
        date, bah = found
        price = bah.get(("home", "draw", "away")[c["outcome"]])
        if not price:
            continue
        team = c["home"] if c["outcome"] == 0 else c["away"] if c["outcome"] == 2 else None
        legs.append({"market": "1X2", "outcome": ("home_win", "draw", "away_win")[c["outcome"]], "team": team,
                     "best_odds": float(price), "market_probability": c["market"],
                     "bookmaker": "bet-at-home", "bookmaker_key": "betathome",
                     "home_team": c["home"], "away_team": c["away"], "commence_time": f"{date}T18:45:00Z",
                     "sport_key": "nl", "model": c["model"], "ki_agrees": False, "won": c["won"]})
    return legs


def simulate(legs, floor, target):
    pool = [{**l, "probability": l["model"], "conservative_probability": l["market_probability"]}
            for l in legs
            if l["best_odds"] >= MIN_LEG_ODDS and l["market_probability"] >= floor
            and l["model"] is not None and l["model"] >= l["market_probability"] - MODEL_TOLERANCE]
    by_day = defaultdict(list)
    for l in pool:
        by_day[l["commence_time"][:10]].append(l)
    out = {s: {"tickets": 0, "won": 0, "units": 0.0, "expected": 0.0} for s in SIZES}
    for day_legs in by_day.values():
        tickets = build_tickets(day_legs, max_legs=max(SIZES), min_odds=target)
        for size in SIZES:
            t = next((t for t in tickets if t["leg_count"] == size), None)
            if not t:
                continue
            won = all(l["won"] for l in t["legs"])
            o = out[size]
            o["tickets"] += 1
            o["won"] += won
            o["units"] += (t["combined_odds"] - 1) if won else -1
            o["expected"] += t["market_probability"] or 0
    return out


def main():
    report = {}
    for name, legs in (("live", live_days()), ("history", history_days())):
        days = len({l["commence_time"][:10] for l in legs})
        report[name] = {"days": days, "legs": len(legs), "grid": []}
        print(f"\n{name.upper()}: {days} Spieltage, {len(legs)} mögliche Tipps")
        print(f"{'min. Wahrsch.':>13} {'Ziel':>5} | " + " | ".join(f"{s}er: n  Treffer  erw.   ROI " for s in SIZES)
              + " | gesamt ROI")
        for floor in FLOORS:
            for target in TARGETS:
                r = simulate(legs, floor, target)
                report[name]["grid"].append({"floor": floor, "target": target, "by_size": r})
                cells = []
                for s in SIZES:
                    o = r[s]
                    n = o["tickets"]
                    cells.append(f"{s}er: {n:2} {o['won'] / n:6.0%} {o['expected'] / n:5.0%} {o['units'] / n:+6.0%}"
                                 if n else f"{s}er:  0      -     -      - ")
                n = sum(r[s]["tickets"] for s in SIZES)
                total = sum(r[s]["units"] for s in SIZES) / n if n else 0
                print(f"{floor:13.0%} {target:5.1f} | " + " | ".join(cells) + f" | {total:+6.0%} ({n})")
    OUT.write_text(json.dumps(report, indent=1, ensure_ascii=False) + "\n")
    print(f"\ngeschrieben: {OUT.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
