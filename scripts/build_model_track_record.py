"""How often the model was right when it disagreed with the market.

    python3 scripts/build_model_track_record.py
    python3 scripts/build_model_track_record.py --api https://football-prediction.fly.dev

The page's ★ tip is the model's view where it departs most from the market.
Whether to follow it needs a measure, and the model's own confidence is not
one: it rated bets 60% that won 50%. This builds the measure from outcomes -
for each size of disagreement, how often such a bet actually won, set
against what the market and the model expected.

Two sources, kept apart in the output:
  archive  every Bundesliga 1X2 outcome 2021-22 to 2025-26 (except 2024-25,
           which has no archive), the model's point-in-time forecast against
           Pinnacle's pre-closing margin-free price
  nations  Nations League 2020-21 and 2024-25, national models trained
           before each season against the average German-licensed price
           (scripts/nl_backtest.py)
  live     every bet the site logged (data/bet_log.jsonl) with a model and a
           market probability, graded against the real result

Only outcomes the model rates ABOVE the market are counted - those are the
ones it would suggest. Writes data/model_track_record.json, which the API
serves and the ★ box reads.
"""
from __future__ import annotations

import argparse
import json
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

OUT = ROOT / "data" / "model_track_record.json"
# Points by which the model rates a bet above the market.
BUCKETS = [(0.0, 0.05), (0.05, 0.10), (0.10, 0.20), (0.20, 1.0)]


def bucket_of(gap: float):
    return next((b for b in BUCKETS if b[0] <= gap < b[1]), None)


# A verdict needs this many cases; fewer are reported as "too few".
MIN_CASES = 30


def verdict(cases: list) -> str:
    """'better', 'worse' or 'same' than the market expected, or 'too_few'.

    The number of wins is compared with the market's own expectation for
    exactly these bets (a sum of different probabilities, so its spread is
    the sum of p(1-p)); a difference counts beyond two standard deviations,
    about 95%.
    """
    if len(cases) < MIN_CASES:
        return "too_few"
    wins = sum(x["won"] for x in cases)
    expected = sum(x["market"] for x in cases)
    sd = sum(x["market"] * (1 - x["market"]) for x in cases) ** 0.5
    z = (wins - expected) / sd if sd else 0.0
    return "better" if z > 2 else "worse" if z < -2 else "same"


def summarise(cases: list) -> list:
    out = []
    for lo, hi in BUCKETS:
        c = [x for x in cases if lo <= x["gap"] < hi]
        n = len(c)
        out.append({"from": lo, "to": hi, "n": n, "verdict": verdict(c),
                    "hit_rate": round(sum(x["won"] for x in c) / n, 4) if n else None,
                    "market_expected": round(sum(x["market"] for x in c) / n, 4) if n else None,
                    "model_expected": round(sum(x["model"] for x in c) / n, 4) if n else None})
    return out


def archive_cases() -> list:
    from does_the_model_add_anything import load
    cases = []
    for r in load():
        for i in range(3):
            gap = r["model"][i] - r["pre"][i]
            if gap > 0:
                cases.append({"gap": gap, "won": r["result"] == i, "market": r["pre"][i], "model": r["model"][i]})
    return cases


def nations_league_cases() -> list:
    """Nations League 2020-21 and 2024-25: point-in-time national models
    against the average German-licensed price (scripts/nl_backtest.py)."""
    path = ROOT / "data" / "model_reports" / "nl_backtest_20260927" / "cases.jsonl"
    if not path.exists():
        return []
    cases = []
    for line in path.read_text(encoding="utf-8").splitlines():
        r = json.loads(line)
        if r["model"] > r["market"]:
            cases.append({"gap": r["model"] - r["market"], "won": r["won"], "market": r["market"],
                          "model": r["model"], "competition": "soccer_uefa_nations_league"})
    return cases


# The committed log, and the server's own (src/scheduler.py) - on the server
# the second is newer than the copy baked into the image.
LOG_PATHS = [ROOT / "data" / "bet_log.jsonl", ROOT / "data" / "logs" / "bet_log.jsonl"]


def live_cases(api: str | None) -> list:
    if not api:
        return []
    results = json.load(urllib.request.urlopen(f"{api}/real-results", timeout=60))["results"]
    return grade_live(LOG_PATHS, results)


def _logged_entries(paths: list) -> list:
    """One entry per match (teams + kickoff date); a later file overrides."""
    from grade_bets import _norm
    from log_bets import has_bets
    entries = {}
    for path in paths:
        if not path.exists():
            continue
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                e = json.loads(line)
                key = (_norm(e["home_team"]), _norm(e["away_team"]), str(e.get("commence_time"))[:10])
                # An entry logged without odds never replaces one with bets.
                if key not in entries or has_bets(e):
                    entries[key] = e
    return list(entries.values())


def grade_live(paths: list, results: list) -> list:
    """Logged bets with a model and a market probability, graded against
    results matched on teams AND kickoff date - the same pairing can meet
    twice in a season."""
    from grade_bets import _norm, grade
    finished = {(_norm(r["home_team"]), _norm(r["away_team"]), str(r.get("commence_time"))[:10]): r
                for r in results if r.get("completed") and r.get("home_score") is not None}
    cases = []
    for entry in _logged_entries(paths):
        res = finished.get((_norm(entry["home_team"]), _norm(entry["away_team"]),
                            str(entry.get("commence_time"))[:10]))
        if not res:
            continue
        for b in entry.get("bets") or (entry.get("green_bets", []) + entry.get("red_bets", [])):
            model, market = b.get("model_probability_raw"), b.get("market_probability")
            if model is None or market is None or model <= market:
                continue
            g = grade(b, entry["home_team"], entry["away_team"], res["home_score"], res["away_score"])
            if g in ("win", "loss"):
                cases.append({"gap": model - market, "won": g == "win", "market": market, "model": model,
                              "competition": entry.get("sport_key")})
    return cases


def build(live: list) -> dict:
    """The report for the given live cases, written to data/model_track_record.json."""
    archive = archive_cases()
    # Per competition: a Nations League tip is a different model and a
    # different market from the Bundesliga, so its record is its own. The
    # archive is Bundesliga only.
    by_competition = {"soccer_germany_bundesliga": summarise(
        archive + [c for c in live if c.get("competition") == "soccer_germany_bundesliga"])}
    nl_archive = nations_league_cases()
    for comp in ({c.get("competition") for c in live} | {"soccer_uefa_nations_league"}) - {"soccer_germany_bundesliga", None}:
        extra = nl_archive if comp == "soccer_uefa_nations_league" else []
        by_competition[comp] = summarise(extra + [c for c in live if c.get("competition") == comp])
    report = {"buckets": [[lo, hi] for lo, hi in BUCKETS], "min_cases": MIN_CASES,
              "archive": summarise(archive), "live": summarise(live),
              "combined": summarise(archive + live), "by_competition": by_competition,
              "sources": {"archive": "Bundesliga 1X2, model vs Pinnacle pre-closing, 2021-22..2025-26",
                          "live": "data/bet_log.jsonl, graded against /real-results"}}
    OUT.write_text(json.dumps(report, indent=1) + "\n")
    return report


def refresh(results: list) -> dict:
    """The server's daily update: every log it has, graded against ESPN."""
    return build(grade_live(LOG_PATHS, results))


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--api", default=None, help="to grade the live log against real results")
    args = parser.parse_args()
    report = build(live_cases(args.api))
    for label in ("archive", "live"):
        print(label)
        for b in report[label]:
            if b["n"]:
                print(f"  Modell {b['from']:.0%}-{b['to']:.0%} ueber Markt: n={b['n']:5}  getroffen {b['hit_rate']:.1%}  "
                      f"Markt erwartet {b['market_expected']:.1%}  Modell erwartet {b['model_expected']:.1%}  -> {b['verdict']}")
    print(f"geschrieben: {OUT.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
