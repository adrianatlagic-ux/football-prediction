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
import urllib.request
from pathlib import Path

LOG_PATH = Path(__file__).parent.parent / "data" / "bet_log.jsonl"
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


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--api", default=DEFAULT_API)
    args = parser.parse_args()

    if not LOG_PATH.exists():
        print("Noch kein Bet-Log vorhanden. Erst scripts/log_bets.py laufen lassen.")
        return

    results = json.load(urllib.request.urlopen(f"{args.api}/real-results", timeout=30))["results"]
    finished = {}
    for r in results:
        if r.get("completed") and r.get("home_score") is not None:
            finished[(_norm(r["home_team"]), _norm(r["away_team"]))] = r

    all_green = Bucket("Alle grünen Wetten")
    clean_green = Bucket("...davon saubere (nicht ⚠)")
    suspicious_green = Bucket("...davon verdächtige (⚠)")
    all_red = Bucket("Alle roten Wetten (zur Kontrolle)")
    top_rec = Bucket("Nur Top-Empfehlung pro Spiel")
    consensus = Bucket("Konsens-Empfehlung (Modell+Value+KI kombiniert)")
    agent_pick = Bucket("KIs eigener Pick")
    agent_agrees = Bucket("Top-Tipp, KI stimmt zu")
    agent_disagrees = Bucket("Top-Tipp, KI widerspricht")

    pending = 0
    match_rows = []

    for line in LOG_PATH.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        entry = json.loads(line)
        home, away = entry["home_team"], entry["away_team"]
        res = finished.get((_norm(home), _norm(away)))
        if res is None:
            pending += 1
            continue
        hs, as_ = res["home_score"], res["away_score"]

        if "green_bets" in entry:
            # New full-breakdown format.
            rec = entry.get("recommendation")
            agent = entry.get("agent_eval")
            a_pick = agent.get("pick") if agent else None

            combined = entry.get("combined") or {}
            consensus_pick = combined.get("consensus_pick")

            for b in entry.get("green_bets", []):
                g = grade(b, home, away, hs, as_)
                if g is None:
                    continue
                all_green.add(g, b["best_odds"])
                (suspicious_green if b.get("suspicious") else clean_green).add(g, b["best_odds"])
                if _same_bet(b, rec):
                    top_rec.add(g, b["best_odds"])
                if _same_bet(b, a_pick):
                    agent_pick.add(g, b["best_odds"])
                    if agent.get("agrees_with_model"):
                        agent_agrees.add(g, b["best_odds"])
                    else:
                        agent_disagrees.add(g, b["best_odds"])
                if _same_bet(b, consensus_pick):
                    consensus.add(g, b["best_odds"])

            for b in entry.get("red_bets", []):
                g = grade(b, home, away, hs, as_)
                if g is not None:
                    all_red.add(g, b["best_odds"])
                    if _same_bet(b, consensus_pick):
                        consensus.add(g, b["best_odds"])

            rec_desc = f"{rec['market']} {rec.get('team') or rec['outcome']}" if rec else "-"
            match_rows.append(f"  {home} {hs}-{as_} {away:18} | {len(entry.get('green_bets', [])):2} grüne Tipps | Top: {rec_desc}")
        else:
            # Legacy flat single-tip format.
            g = grade(entry, home, away, hs, as_)
            if g is None:
                continue
            all_green.add(g, entry["best_odds"])
            top_rec.add(g, entry["best_odds"])
            tip = f"{entry['market']} {entry.get('team') or entry['outcome']}"
            match_rows.append(f"  {home} {hs}-{as_} {away:18} | {tip:28} @ {entry['best_odds']:.2f} | {g.upper()} [legacy]")

    for row in match_rows:
        print(row)

    print("\n" + "=" * 60)
    print(f"Spiele ausgewertet: {len(match_rows)}  (noch offen: {pending})\n")
    for bucket in [all_green, clean_green, suspicious_green, all_red, top_rec, consensus]:
        print(bucket.report())

    if agent_pick.decided or agent_agrees.decided or agent_disagrees.decided:
        print("\n  -- KI-Agent --")
        print(agent_pick.report())
        print(agent_agrees.report())
        print(agent_disagrees.report())

    if not match_rows:
        print(f"Noch keine Tipps auswertbar (offen: {pending}). Ergebnisse fehlen noch.")


if __name__ == "__main__":
    main()
