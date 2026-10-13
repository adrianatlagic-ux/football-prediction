"""Where does the AI agent's pick beat the market, and where not?

    python3 scripts/agent_pick_analysis.py

Reads the server's bet log (the entry logged shortly before kickoff, so the
agent's final pick after its pre-kickoff re-check) and the results. Every
group shows hits against the market's own expectation (bet-at-home's
margin-free price of the pick, or the logged reference book where the pick's
best price came from elsewhere), z beyond 2 being unlikely to be chance, and
the return per unit at the logged odds. Groups of a dozen picks say little.

Also checks the idea of a double safety for the 🎯 pick: only where our
model rates it above the market.
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
from grade_bets import _norm, grade  # noqa: E402

API = "https://football-prediction.fly.dev"


def load():
    results = json.load(urllib.request.urlopen(f"{API}/real-results", timeout=60))["results"]
    finished = {(_norm(r["home_team"]), _norm(r["away_team"]), str(r.get("commence_time"))[:10]): r
                for r in results if r.get("completed") and r.get("home_score") is not None}
    entries = []
    for line in urllib.request.urlopen(f"{API}/logs/bet_log", timeout=60).read().decode().splitlines():
        e = json.loads(line)
        r = finished.get((_norm(e["home_team"]), _norm(e["away_team"]), str(e.get("commence_time"))[:10]))
        if r:
            entries.append((e, r))
    return entries


def kind(b, e):
    """Kind of bet; favourite or underdog by the market's 1X2 prices of the
    match (the side bet-at-home rates likelier to win)."""
    m, team = b["market"], b.get("team")
    win = {}
    for x in e.get("green_bets", []) + e.get("red_bets", []) + [e.get("likely_pick") or {}, b]:
        if x.get("market") == "1X2" and x.get("outcome") in ("home_win", "away_win") and x.get("market_probability"):
            win[x["team"]] = x["market_probability"]
    other = e["away_team"] if team == e["home_team"] else e["home_team"]
    side = None
    if team and team in win and other in win:
        side = "Favorit" if win[team] >= win[other] else "Außenseiter"
    elif team and team in win:
        side = "Favorit" if win[team] >= 0.4 else "Außenseiter"
    if m == "1X2":
        return "1X2 Remis" if b["outcome"] == "draw" else f"1X2 {side or '?'}"
    if m == "Handicap 0.0":
        return f"Remis=Einsatz zurück {side or '?'}"
    if m == "Handicap +0.5":
        return f"Doppelte Chance {side or '?'}"
    if m.startswith("Handicap"):
        line = float(m.split()[-1])
        return f"Handicap {'+' if line > 0 else '−'} {side or '?'}"
    if m.startswith("Over/Under"):
        return f"Tore {b['outcome']}"
    return m


def bucket_odds(o):
    return "< 1,50" if o < 1.5 else "1,50–1,99" if o < 2 else "2,00–2,99" if o < 3 else "≥ 3,00"


class Group:
    def __init__(self):
        self.n = self.won = 0
        self.exp = self.var = self.units = 0.0

    def add(self, won, p, odds):
        self.n += 1
        self.won += won
        self.exp += p
        self.var += p * (1 - p)
        self.units += (odds - 1) if won else -1

    def line(self, name):
        if not self.n:
            return f"  {name:38s} –"
        z = (self.won - self.exp) / math.sqrt(self.var) if self.var else 0
        return (f"  {name:38s} n={self.n:3d}  getroffen {self.won / self.n:4.0%}  Markt erwartet "
                f"{self.exp / self.n:4.0%}  z={z:+.1f}  Rendite {self.units / self.n:+5.0%}")


def table(title, groups, order=None):
    print(f"\n{title}")
    for k in (order or sorted(groups, key=lambda k: -groups[k].n)):
        if k in groups:
            print(groups[k].line(k))


def main():
    entries = load()
    total, by_kind, by_odds, by_book, by_recheck = Group(), defaultdict(Group), defaultdict(Group), defaultdict(Group), defaultdict(Group)
    by_likely, by_model, by_day, by_comp = defaultdict(Group), defaultdict(Group), defaultdict(Group), defaultdict(Group)
    likely_model = defaultdict(Group)
    for e, r in entries:
        hs, as_ = r["home_score"], r["away_score"]
        a = e.get("agent_eval") or {}
        p = a.get("pick")
        lp = e.get("likely_pick")
        if lp and lp.get("market_probability") is not None:
            g = grade(lp, e["home_team"], e["away_team"], hs, as_)
            if g in ("win", "loss"):
                mp, model = lp["market_probability"], lp.get("model_probability_raw")
                if model is None:
                    label = "kein Modellwert"
                elif model > mp:
                    label = "Modell über Markt"
                elif model >= mp - 0.05:
                    label = "Modell bis 5 Punkte darunter"
                else:
                    label = "Modell mehr als 5 Punkte darunter"
                likely_model[label].add(g == "win", mp, lp["best_odds"])
        if not p or p.get("market_probability") is None:
            continue
        g = grade(p, e["home_team"], e["away_team"], hs, as_)
        if g not in ("win", "loss"):
            continue
        won, mp, odds = g == "win", p["market_probability"], p["best_odds"]
        for grp in (total, by_kind[kind(p, e)], by_odds[bucket_odds(odds)],
                    by_comp[{"soccer_uefa_nations_league": "Nations League", "soccer_germany_bundesliga": "Bundesliga"}.get(e.get("sport_key"), e.get("competition") or e.get("sport_key"))],
                    by_day[str(e.get("commence_time"))[:10]]):
            grp.add(won, mp, odds)
        by_book["bet-at-home" if p.get("bookmaker_key") == "betathome" else f"anderer ({p.get('bookmaker')})"].add(won, mp, odds)
        rev = a.get("revised_from_previous")
        by_recheck["vor Anpfiff geändert" if rev else "beibehalten" if rev is False else "keine zweite Prüfung"].add(won, mp, odds)
        same = lp and (lp.get("market"), lp.get("outcome"), lp.get("team")) == (p["market"], p["outcome"], p.get("team"))
        by_likely["KI = 🎯 wahrscheinlichster" if same else "KI ≠ 🎯 (eigene Wahl)"].add(won, mp, odds)
        model = p.get("model_probability_raw")
        by_model["kein Modellwert" if model is None else "Modell über Markt" if model > mp
                 else "Modell bis 5 Punkte darunter" if model >= mp - 0.05 else "Modell mehr als 5 Punkte darunter"].add(won, mp, odds)
    print(total.line("KI-Tipp gesamt"))
    table("Nach Wettbewerb", by_comp)
    table("Nach Wettart", by_kind)
    table("Nach Quote", by_odds, ["< 1,50", "1,50–1,99", "2,00–2,99", "≥ 3,00"])
    table("Nach Buchmacher der geloggten Quote", by_book)
    table("Zweite Prüfung eine Stunde vor Anpfiff", by_recheck)
    table("KI-Tipp gegenüber 🎯", by_likely)
    table("KI-Tipp nach Modell-Einschätzung", by_model)
    table("Nach Spieltag", by_day, sorted(by_day))
    table("Zum Vergleich: 🎯 nach Modell-Einschätzung (deine Idee: nur wenn Modell über Markt)", likely_model,
          ["Modell über Markt", "Modell bis 5 Punkte darunter", "Modell mehr als 5 Punkte darunter", "kein Modellwert"])


if __name__ == "__main__":
    main()
