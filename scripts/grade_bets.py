"""Grade every logged bet (not just the curated top pick) against the actual
result - the honest, complete bilanz.

    python3 scripts/grade_bets.py
    python3 scripts/grade_bets.py --api https://football-prediction.fly.dev

Reads data/bet_log.jsonl. New-format entries (logged via the current
log_bets.py) carry the FULL breakdown for a match - every green and red
candidate bet, the curated top recommendation, and the agent evaluation - so
every single one of them gets graded here, not just the one that was
highlighted as "the tip". Older, flat single-tip entries are still supported
for continuity with earlier logs.

A push (Asian Handicap / Draw-No-Bet landing exactly on the line) returns the
stake - neither win nor loss.
"""
import argparse
import json
import re
import sys
import urllib.request
from pathlib import Path

LOG_PATH = Path(__file__).parent.parent / "data" / "bet_log.jsonl"

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from log_bets import COMPETITIONS  # noqa: E402

# Within five points of the market the model counts as agreeing with 🎯, as
# on the page (LikelyTipBox, src/price_tip.MODEL_TOLERANCE).
MODEL_TOLERANCE = 0.05
LIKELY_GROUPS = ("Modell ✓ / KI ✓", "Modell ✓ / KI ✗", "Modell ✗ / KI ✓", "Modell ✗ / KI ✗",
                 "Modell ✓ / keine KI", "Modell ✗ / keine KI")
DEFAULT_API = "https://football-prediction.fly.dev"


def _norm(name: str) -> str:
    n = re.sub(r"\band\b", " ", name.lower()).replace("&", " ")
    n = re.sub(r"[^a-z]", "", n)
    return {"usa": "unitedstates"}.get(n, n)


def _team_margin(team, home, away, hs, as_):
    """Goal margin from the perspective of `team` (positive = team ahead). None if unmatched."""
    if _norm(team) == _norm(home):
        return hs - as_
    if _norm(team) == _norm(away):
        return as_ - hs
    return None


def grade(bet, home, away, hs, as_):
    """Return 'win' | 'loss' | 'push' | None (can't grade)."""
    market, outcome, team = bet["market"], bet["outcome"], bet.get("team")
    total = hs + as_

    if market == "1X2":
        winner = "H" if hs > as_ else ("A" if as_ > hs else "D")
        if outcome == "draw":
            return "win" if winner == "D" else "loss"
        m = _team_margin(team, home, away, hs, as_)
        if m is None:
            return None
        return "win" if m > 0 else "loss"

    if market.startswith("Over/Under"):
        line = float(market.split()[-1])
        if outcome == "Over":
            return "win" if total > line else "loss"
        return "win" if total < line else "loss"

    if market == "Handicap +0.5":  # double chance: team wins or draws
        m = _team_margin(team, home, away, hs, as_)
        return None if m is None else ("win" if m >= 0 else "loss")

    if market == "Handicap 0.0":  # draw no bet
        m = _team_margin(team, home, away, hs, as_)
        if m is None:
            return None
        return "push" if m == 0 else ("win" if m > 0 else "loss")

    if market == "BTTS":
        both = hs > 0 and as_ > 0
        return "win" if both == (outcome.lower() == "yes") else "loss"

    if market.startswith("Handicap"):  # asian handicap, e.g. -1.5 / +2.0
        point = float(market.split()[-1])
        m = _team_margin(team, home, away, hs, as_)
        if m is None:
            return None
        adj = m + point
        return "push" if adj == 0 else ("win" if adj > 0 else "loss")

    return None


class Bucket:
    """Tracks win/loss/push counts and unit profit for one slice of bets."""

    def __init__(self, label):
        self.label = label
        self.wins = self.losses = self.pushes = 0
        self.units = 0.0

    def add(self, outcome, odds):
        if outcome == "win":
            self.wins += 1
            self.units += odds - 1
        elif outcome == "loss":
            self.losses += 1
            self.units -= 1
        elif outcome == "push":
            self.pushes += 1

    @property
    def decided(self):
        return self.wins + self.losses

    def report(self):
        if not self.decided:
            return f"  {self.label}: keine ausgewerteten Tipps"
        hit = self.wins / self.decided
        roi = self.units / self.decided
        push = f"  Push: {self.pushes}" if self.pushes else ""
        return (f"  {self.label}: {self.wins}W/{self.losses}L{push}  "
                f"Trefferquote {hit:.0%}  ROI {roi:+.1%}  ({self.units:+.2f} Einheiten)")


def _same_bet(a, b):
    return a is not None and b is not None and a["market"] == b["market"] \
        and a["outcome"] == b["outcome"] and a.get("team") == b.get("team")


# The price range both market picks are compared in: the same matches, the
# same odds, only the choice of market differs.
FAIR_MIN_ODDS, FAIR_MAX_ODDS = 1.30, 2.00


def competition_of(entry) -> str:
    return entry.get("competition") or COMPETITIONS.get(entry.get("sport_key"), "ohne Wettbewerb (alte Einträge)")


def _game_pick(entry):
    """The Game Pick with its odds: the market favourite's 1X2 bet."""
    pick = (entry.get("combined") or {}).get("consensus_pick")
    for b in entry.get("green_bets", []) + entry.get("red_bets", []):
        if _same_bet(b, pick):
            return b
    return None


def grade_entries(entries, finished):
    """Every bucket for one group of entries, plus the per-match rows."""
    buckets = {k: Bucket(label) for k, label in (
        ("all_green", "Alle grünen Wetten"), ("clean_green", "...davon saubere (nicht ⚠)"),
        ("suspicious_green", "...davon verdächtige (⚠)"), ("all_red", "Alle roten Wetten (zur Kontrolle)"),
        ("top_rec", "Nur Top-Empfehlung pro Spiel"), ("consensus", "Game Pick (Markt-Favorit, jede Quote)"),
        ("agent_pick", "KIs eigener Pick"), ("agent_agrees", "Top-Tipp, KI stimmt zu"),
        ("agent_disagrees", "Top-Tipp, KI widerspricht"),
        ("price_tip", "💰 Preistipp (bet-at-home über Pinnacle fair)"),
        ("likely", "🎯 Wahrscheinlichster Tipp (Markt, Quote 1.30-2.00)"),
        ("fair_game", f"Game Pick, nur Quote {FAIR_MIN_ODDS:.2f}-{FAIR_MAX_ODDS:.2f}"),
        ("fair_likely", "🎯 auf denselben Spielen"),
        ("bet_tip", "Wett-Tipp (Modell und KI stimmen zu)"))}
    for g in LIKELY_GROUPS:
        buckets["likely " + g] = Bucket(f"🎯 bei {g}")
    out = {"buckets": buckets, "edges": [], "no_tip": 0, "pending": 0, "rows": [], "fair_matches": 0,
           "versus_ai": {}}
    for entry in entries:
        home, away = entry["home_team"], entry["away_team"]
        res = finished.get((_norm(home), _norm(away), str(entry.get("commence_time"))[:10]))
        if res is None:
            out["pending"] += 1
            continue
        hs, as_ = res["home_score"], res["away_score"]
        if "green_bets" not in entry:
            # Legacy flat single-tip format.
            g = grade(entry, home, away, hs, as_)
            if g is None:
                continue
            buckets["all_green"].add(g, entry["best_odds"])
            buckets["top_rec"].add(g, entry["best_odds"])
            tip = f"{entry['market']} {entry.get('team') or entry['outcome']}"
            out["rows"].append(f"  {home} {hs}-{as_} {away:18} | {tip:28} @ {entry['best_odds']:.2f} | {g.upper()} [legacy]")
            continue
        rec = entry.get("recommendation")
        agent = entry.get("agent_eval")
        a_pick = agent.get("pick") if agent else None
        consensus_pick = (entry.get("combined") or {}).get("consensus_pick")
        for b in entry.get("green_bets", []):
            g = grade(b, home, away, hs, as_)
            if g is None:
                continue
            buckets["all_green"].add(g, b["best_odds"])
            buckets["suspicious_green" if b.get("suspicious") else "clean_green"].add(g, b["best_odds"])
            if _same_bet(b, rec):
                buckets["top_rec"].add(g, b["best_odds"])
            if _same_bet(b, a_pick):
                buckets["agent_agrees" if agent.get("agrees_with_model") else "agent_disagrees"].add(g, b["best_odds"])
            if _same_bet(b, consensus_pick):
                buckets["consensus"].add(g, b["best_odds"])
        for b in entry.get("red_bets", []):
            g = grade(b, home, away, hs, as_)
            if g is not None:
                buckets["all_red"].add(g, b["best_odds"])
                if _same_bet(b, consensus_pick):
                    buckets["consensus"].add(g, b["best_odds"])
        # The price tip is graded at bet-at-home's odds, the ones it was
        # given at. Its expected edge is kept to set against the result.
        pt = entry.get("price_tip") or {}
        tip = pt.get("tip")
        if tip:
            g = grade(tip, home, away, hs, as_)
            if g is not None:
                buckets["price_tip"].add(g, tip["book_odds"])
                out["edges"].append(tip["edge"])
        elif pt:
            out["no_tip"] += 1
        # The AI's own pick, every one of them - not only those that were also
        # one of the model's green bets.
        if a_pick and a_pick.get("best_odds"):
            g_ai = grade(a_pick, home, away, hs, as_)
            if g_ai is not None:
                buckets["agent_pick"].add(g_ai, a_pick["best_odds"])
        bt = (entry.get("bet_tip") or {}).get("tip")
        if bt:
            g_bt = grade(bt, home, away, hs, as_)
            if g_bt is not None:
                buckets["bet_tip"].add(g_bt, bt["best_odds"])
        lp = entry.get("likely_pick")
        g_lp = grade(lp, home, away, hs, as_) if lp else None
        if g_lp is not None:
            buckets["likely"].add(g_lp, lp["best_odds"])
            # 🎯 split by whether the model and the AI side with it, as the
            # page shows it; and how 🎯 and the AI's own pick did together.
            from src.price_tip import implies
            mp = lp.get("model_probability_raw")
            model_ok = mp is not None and mp >= lp["market_probability"] - MODEL_TOLERANCE
            ai_ok = implies(a_pick, lp, home, away) if a_pick else None
            group = ("Modell ✓" if model_ok else "Modell ✗") + " / " + (
                "keine KI" if ai_ok is None else "KI ✓" if ai_ok else "KI ✗")
            buckets["likely " + group].add(g_lp, lp["best_odds"])
            g_ai = grade(a_pick, home, away, hs, as_) if a_pick and a_pick.get("best_odds") else None
            if g_ai in ("win", "loss") and g_lp in ("win", "loss"):
                cell = ("🎯 ✅" if g_lp == "win" else "🎯 ❌") + " · " + ("KI ✅" if g_ai == "win" else "KI ❌")
                out["versus_ai"][cell] = out["versus_ai"].get(cell, 0) + 1
        # Fair comparison: only matches where both picks exist and the Game
        # Pick's odds lie in 🎯's range - same matches, same prices.
        gp = _game_pick(entry)
        g_gp = grade(gp, home, away, hs, as_) if gp else None
        if (g_gp is not None and g_lp is not None
                and FAIR_MIN_ODDS <= gp["best_odds"] <= FAIR_MAX_ODDS):
            buckets["fair_game"].add(g_gp, gp["best_odds"])
            buckets["fair_likely"].add(g_lp, lp["best_odds"])
            out["fair_matches"] += 1
        rec_desc = f"{rec['market']} {rec.get('team') or rec['outcome']}" if rec else "-"
        out["rows"].append(f"  {home} {hs}-{as_} {away:18} | {len(entry.get('green_bets', [])):2} grüne Tipps | Top: {rec_desc}")
    return out


def print_report(name, r):
    b = r["buckets"]
    print("\n" + "=" * 60)
    print(f"{name}: {len(r['rows'])} Spiele ausgewertet (noch offen: {r['pending']})")
    print("=" * 60)
    for row in r["rows"]:
        print(row)
    print()
    for key in ("all_green", "clean_green", "suspicious_green", "all_red", "top_rec", "consensus"):
        print(b[key].report())
    if b["price_tip"].decided or r["no_tip"]:
        print("\n  -- Preistipp --")
        print(b["price_tip"].report())
        if r["edges"]:
            print(f"  erwarteter Edge im Schnitt {sum(r['edges']) / len(r['edges']):+.1%} "
                  f"- einzelne Ergebnisse schwanken weit mehr; erst viele Tipps sagen etwas.")
        print(f"  Spiele ohne Preistipp: {r['no_tip']}")
    if b["bet_tip"].decided:
        print(b["bet_tip"].report())
    if b["likely"].decided:
        print(b["likely"].report())
    if any(b["likely " + g].decided for g in LIKELY_GROUPS):
        print("\n  -- 🎯 je nachdem, ob Modell und KI zustimmen --")
        for g in LIKELY_GROUPS:
            if b["likely " + g].decided:
                print(b["likely " + g].report())
    if r["versus_ai"]:
        print("  🎯 und KI-Tipp im selben Spiel: " + ", ".join(f"{k} {v}x" for k, v in sorted(r["versus_ai"].items())))
    if r["fair_matches"]:
        print(f"\n  -- Fairer Vergleich: {r['fair_matches']} Spiele mit beiden Tipps, Game Pick "
              f"zu Quote {FAIR_MIN_ODDS:.2f}-{FAIR_MAX_ODDS:.2f} --")
        print(b["fair_game"].report())
        print(b["fair_likely"].report())
    if b["agent_pick"].decided or b["agent_agrees"].decided or b["agent_disagrees"].decided:
        print("\n  -- KI-Agent --")
        for key in ("agent_pick", "agent_agrees", "agent_disagrees"):
            print(b[key].report())


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--api", default=DEFAULT_API)
    parser.add_argument("--competition", default=None,
                        help="nur diesen Wettbewerb, z.B. 'Nations League' (Standard: jeder getrennt)")
    args = parser.parse_args()

    if not LOG_PATH.exists():
        print("Noch kein Bet-Log vorhanden. Erst scripts/log_bets.py laufen lassen.")
        return

    results = json.load(urllib.request.urlopen(f"{args.api}/real-results", timeout=30))["results"]
    # Teams AND date: the same pairing can meet twice in a season.
    finished = {(_norm(r["home_team"]), _norm(r["away_team"]), str(r.get("commence_time"))[:10]): r
                for r in results if r.get("completed") and r.get("home_score") is not None}
    groups = {}
    for line in LOG_PATH.read_text(encoding="utf-8").splitlines():
        if line.strip():
            entry = json.loads(line)
            groups.setdefault(competition_of(entry), []).append(entry)
    for name in sorted(groups):
        if args.competition and name != args.competition:
            continue
        print_report(name, grade_entries(groups[name], finished))


if __name__ == "__main__":
    main()
