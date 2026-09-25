"""Do the bookmakers a German bettor can legally use ever beat Pinnacle?

The line-shopping result rested on the best price across roughly forty
bookmakers, most of which a customer in Germany cannot use, and much of its
edge came from outlier quotes. This asks the practical question instead: at
kickoff, how often did a German-licensed book quote more than Pinnacle's
margin-free closing price - and by how much?

    python3 scripts/german_books_vs_pinnacle.py

Both prices are closing prices, compared at the same moment, so there is no
timing gap and no stale-quote problem: Pinnacle's close is the best available
estimate of the true probability, and a quote above its fair value at that
point is positive expected value by construction. The measure is that
expected value, not the result of the bet.

Sources: German-licensed closing odds from OddsPortal via Apify (German
proxy, 2023-24 and 2025-26), Pinnacle's closing 1X2 from the football-data
archive. 2025-26 has Pinnacle closing prices only for its first 149 matches.
The OddsPortal "closing" price is the last one it collected, which can be a
few minutes before kickoff; Pinnacle's is at kickoff.
"""
from __future__ import annotations

import csv
import json
import unicodedata
from collections import defaultdict
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
OP = ROOT / "data/odds_archive/oddsportal_de_20260925/bundesliga_2324_2526_closing.json"
FD = [ROOT / "data/odds_archive/football_data_20260923/D1_2324.csv",
      ROOT / "data/odds_archive/football_data_20260923/D1_2526.csv"]
SIDES = ("home", "draw", "away")
STOP = {"fc", "sc", "vfl", "vfb", "tsg", "sv", "1", "04", "05", "1899", "borussia", "bayer", "rb", "eintracht", "munich", "munchen"}


def tokens(name: str) -> set:
    s = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode().lower()
    return {w for w in s.replace(".", " ").replace("-", " ").split() if w not in STOP and len(w) > 1}


def pinnacle():
    out = {}
    for path in FD:
        for r in csv.DictReader(path.open(encoding="utf-8-sig", errors="ignore")):
            try:
                close = [float(r[k]) for k in ("PSCH", "PSCD", "PSCA")]
            except (KeyError, ValueError):
                continue
            inv = [1 / x for x in close]
            d, m, y = r["Date"].split("/")
            y = y if len(y) == 4 else "20" + y
            out.setdefault(f"{y}-{m}-{d}", []).append({
                "home": r["HomeTeam"], "away": r["AwayTeam"],
                "fair": [x / sum(inv) for x in inv],
                "result": {"H": 0, "D": 1, "A": 2}[r["FTR"]]})
    return out


def main():
    pin = pinnacle()
    matches = json.load(OP.open())
    rows, joined = [], 0
    for m in matches:
        day = m["startTime"][:10]
        cands = [p for p in pin.get(day, [])
                 if tokens(p["home"]) & tokens(m["homeTeam"]) and tokens(p["away"]) & tokens(m["awayTeam"])]
        if len(cands) != 1:
            continue
        p = cands[0]; joined += 1
        for b in m.get("bookmakerOdds", []):
            for i, side in enumerate(SIDES):
                price = b.get(side)
                if not price or price <= 1:
                    continue
                rows.append({"book": b["bookmaker"], "odds": price, "ev": price * p["fair"][i] - 1,
                             "profit": price - 1 if p["result"] == i else -1.0})

    print(f"{joined} Spiele mit Pinnacle-Schlussquote abgeglichen\n")
    rng = np.random.default_rng(0)
    by_book = defaultdict(list)
    for r in rows:
        by_book[r["book"]].append(r)
    print(f"  {'Buchmacher':16} {'Preise':>6} {'Ø gegen fair':>13} {'ueber fair':>11} {'>2% ueber':>10}  "
          f"{'EV dieser Wetten':>17} {'ROI':>8}")
    for book, rs in sorted(by_book.items(), key=lambda kv: -np.mean([r["ev"] for r in kv[1]])):
        ev = np.array([r["ev"] for r in rs])
        sel = [r for r in rs if r["ev"] > 0.02]
        if sel:
            e = np.array([r["ev"] for r in sel]); p = np.array([r["profit"] for r in sel])
            tail = f"{e.mean():+16.2%} {p.mean():+7.1%}"
        else:
            tail = f"{'—':>16} {'—':>7}"
        print(f"  {book:16} {len(rs):6} {ev.mean():+12.2%} {(ev > 0).mean():10.1%} {len(sel):10}  {tail}")

    print("\n  Neobet und Interwetten, Faelle >2% ueber Pinnacle, nach Quotenhoehe:")
    for book in ("Neobet", "Interwetten.de"):
        sel = [r for r in by_book.get(book, []) if r["ev"] > 0.02]
        for lo, hi, label in ((1, 2.5, "unter 2,5"), (2.5, 5, "2,5 - 5"), (5, 10, "5 - 10"), (10, 999, "ueber 10")):
            g = [r for r in sel if lo <= r["odds"] < hi]
            if not g:
                continue
            e = np.array([r["ev"] for r in g])
            print(f"    {book:16} {label:10} {len(g):4} Wetten  Ø EV {e.mean():+6.2%}")

    per_season = len([1 for m in matches])  # informational only
    out = ROOT / "data/model_reports/german_books_vs_pinnacle_20260925.json"
    out.write_text(json.dumps({
        "matches_joined": joined,
        "books": {b: {"prices": len(rs), "mean_ev": float(np.mean([r["ev"] for r in rs])),
                      "share_above_fair": float(np.mean([r["ev"] > 0 for r in rs])),
                      "bets_over_2pct": len([r for r in rs if r["ev"] > 0.02])}
                  for b, rs in by_book.items()}}, indent=2) + "\n")
    print(f"\ngeschrieben: {out.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
