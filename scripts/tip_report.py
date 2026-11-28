"""How the tips did, week by week - one report for the /tipp-analyse skill.

    python3 scripts/tip_report.py                    # the server's logs, from 9 November
    python3 scripts/tip_report.py --since 2026-11-15
    python3 scripts/tip_report.py --local            # data/logs in the repository instead

Prints Markdown tables (German, for the reader of the site):

1. every tipper per week - the bet tip (the AI's pick, v9), the shadow (v10
   with memory) and the market's likeliest bet (🎯): tips,
   hit rate, the hit rate the bookmakers' odds expected, the difference
   (the only sign of skill: hitting more often than the odds say), units won
   at 1 per tip, and the change of the hit rate against the week before;
2. the same per kind of bet (win, handicap, over, under);
3. the matches where shadow and AI picked differently;
4. whether the shadow learns: its own probability against its hit rate, and
   how much memory it read and used, per week;
5. the combo tickets per week, rule and size.

A push (handicap landing on the line) returns the stake and counts as neither
hit nor miss. Weeks run Monday to Sunday.
"""
import argparse
import json
import sys
import urllib.request
from collections import defaultdict
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))
from grade_bets import DEFAULT_API, _norm, grade  # noqa: E402

# Since November the page's bet tip is the AI's pick (bet_tip.tip equals
# agent_eval.pick on every logged match), so it is one row.
TIPPERS = (
    ("Wett-Tipp (KI v9)", lambda e: (e.get("agent_eval") or {}).get("pick")),
    ("Schatten (v10 + Gedächtnis)", lambda e: (e.get("agent_eval_shadow") or {}).get("pick")),
    ("🎯 Markt (wahrscheinlichster Tipp)", lambda e: e.get("likely_pick")),
)
COMBO_RULES = {"ai_pick": "KI-Kombi", "agree": "KI + Modell"}


def fetch(api: str, name: str) -> list:
    with urllib.request.urlopen(f"{api}/logs/{name}", timeout=60) as r:
        return [json.loads(line) for line in r.read().decode("utf-8").splitlines() if line.strip()]


def load(args) -> tuple[list, list]:
    if args.local:
        from src import log_store
        return log_store.load_tips(), log_store.load_combos()
    return fetch(args.api, "tips"), fetch(args.api, "combos")


def week_of(day: str) -> date:
    d = date.fromisoformat(day[:10])
    return d - timedelta(days=d.weekday())


def week_label(monday: date) -> str:
    sunday = monday + timedelta(days=6)
    return f"{monday.day:02d}.{monday.month:02d}.–{sunday.day:02d}.{sunday.month:02d}."


def kind(pick: dict) -> str:
    m = pick["market"]
    if m == "1X2":
        return "Sieg/Remis"
    if m.startswith("Handicap"):
        return "Handicap"
    if m.startswith("Over/Under"):
        return "Über" if pick.get("outcome") == "Over" else "Unter"
    return m


def label(pick: dict) -> str:
    """A pick in plain words: "Sieg Porto", "Remis", "Unter 3,5", "Handicap Lille +1,5"."""
    m, o, team = pick["market"], pick.get("outcome"), pick.get("team") or ""
    line = m.split(" ")[-1].replace(".", ",")
    if m == "1X2":
        return "Remis" if o == "draw" else f"Sieg {team}"
    if m.startswith("Over/Under"):
        return f"{'Über' if o == 'Over' else 'Unter'} {line}"
    if m.startswith("Handicap"):
        return f"Handicap {team} {line}"
    return f"{m} {o}"


def outcome(pick: dict, entry: dict):
    r = entry["result"]
    return grade(pick, entry["home_team"], entry["away_team"], r["home_score"], r["away_score"])


class Tally:
    def __init__(self):
        self.n = self.hits = self.pushes = 0
        self.units = self.expected = 0.0
        self.priced = 0

    def add(self, pick: dict, result: str):
        if result == "push":
            self.pushes += 1
            return
        if result not in ("win", "loss"):
            return
        self.n += 1
        if result == "win":
            self.hits += 1
            self.units += pick["best_odds"] - 1
        else:
            self.units -= 1
        p = pick.get("market_probability")
        if isinstance(p, (int, float)):
            self.expected += p
            self.priced += 1

    @property
    def rate(self):
        return self.hits / self.n if self.n else None

    @property
    def market_rate(self):
        return self.expected / self.priced if self.priced else None


def pct(x) -> str:
    return "–" if x is None else f"{x:.0%}"


def pp(x) -> str:
    return "–" if x is None else f"{x * 100:+.0f} Pkt."


def units(x) -> str:
    return f"{x:+.2f}"


def table(header: list, rows: list) -> str:
    out = ["| " + " | ".join(header) + " |", "|" + "|".join("---" for _ in header) + "|"]
    out += ["| " + " | ".join(str(c) for c in row) + " |" for row in rows]
    return "\n".join(out)


def finished_entries(tips: list, since: str) -> list:
    return sorted((e for e in tips if e.get("result") and str(e.get("commence_time", ""))[:10] >= since),
                  key=lambda e: e["commence_time"])


def per_week(entries: list) -> list:
    weeks = defaultdict(list)
    for e in entries:
        weeks[week_of(e["commence_time"])].append(e)
    return sorted(weeks.items())


def section_tippers(entries: list) -> str:
    weeks = per_week(entries)
    parts = []
    for name, get in TIPPERS:
        rows, previous = [], None
        total = Tally()
        for monday, es in weeks:
            t = Tally()
            for e in es:
                pick = get(e)
                if pick:
                    res = outcome(pick, e)
                    t.add(pick, res)
                    total.add(pick, res)
            if not t.n:
                continue
            delta = None if previous is None else t.rate - previous
            rows.append([week_label(monday), t.n, f"{t.hits} ({pct(t.rate)})", pct(t.market_rate),
                         pp(None if t.market_rate is None else t.rate - t.market_rate),
                         units(t.units), pp(delta)])
            previous = t.rate
        if not total.n:
            continue
        rows.append(["**gesamt**", total.n, f"**{total.hits} ({pct(total.rate)})**", pct(total.market_rate),
                     f"**{pp(None if total.market_rate is None else total.rate - total.market_rate)}**",
                     f"**{units(total.units)}**", ""])
        parts.append(f"### {name}\n\n" + table(
            ["Woche", "Tipps", "Treffer", "Markt erwartet", "besser als Markt", "Einheiten", "Δ Trefferquote zur Vorwoche"],
            rows))
    return "\n\n".join(parts)


def section_kinds(entries: list, last_weeks: int) -> str:
    weeks = [m for m, _ in per_week(entries)]
    recent_from = weeks[-last_weeks] if len(weeks) >= last_weeks else (weeks[0] if weeks else None)
    rows = []
    for name, get in TIPPERS[:2]:
        by_kind = defaultdict(Tally)
        recent = defaultdict(Tally)
        for e in entries:
            pick = get(e)
            if not pick:
                continue
            res = outcome(pick, e)
            by_kind[kind(pick)].add(pick, res)
            if recent_from and week_of(e["commence_time"]) >= recent_from:
                recent[kind(pick)].add(pick, res)
        for k in ("Sieg/Remis", "Handicap", "Über", "Unter"):
            t, r = by_kind[k], recent[k]
            if not t.n:
                continue
            rows.append([name, k, t.n, f"{t.hits}–{t.n - t.hits} ({pct(t.rate)})", pct(t.market_rate), units(t.units),
                         f"{r.n} Tipps, {pct(r.rate)}" if r.n else "keine"])
    return table(["Wer", "Tipp-Art", "Tipps", "Treffer–Fehlschläge", "Markt erwartet", "Einheiten",
                  f"letzte {last_weeks} Wochen"], rows)


def section_differing(entries: list) -> str:
    rows, real_w, shadow_w = [], 0, 0
    for e in entries:
        a = (e.get("agent_eval") or {}).get("pick")
        s = (e.get("agent_eval_shadow") or {}).get("pick")
        if not a or not s:
            continue
        same = (a["market"], a.get("outcome"), a.get("team")) == (s["market"], s.get("outcome"), s.get("team"))
        if same:
            continue
        ra, rs = outcome(a, e), outcome(s, e)
        real_w += ra == "win"
        shadow_w += rs == "win"
        r = e["result"]
        mark = {"win": "✓", "loss": "✕", "push": "="}
        rows.append([f"{e['commence_time'][8:10]}.{e['commence_time'][5:7]}.", f"{e['home_team']} – {e['away_team']}",
                     f"{r['home_score']}:{r['away_score']}", f"{label(a)} {mark.get(ra, '?')}", f"{label(s)} {mark.get(rs, '?')}"])
    head = f"{len(rows)} Spiele mit verschiedenem Tipp: Wett-Tipp trifft {real_w}, Schatten trifft {shadow_w}.\n\n"
    return head + table(["Datum", "Spiel", "Ergebnis", "Wett-Tipp", "Schatten"], rows[-15:]) + (
        f"\n\n(die letzten 15 von {len(rows)})" if len(rows) > 15 else "")


def section_learning(entries: list) -> str:
    rows = []
    for monday, es in per_week(entries):
        n = hits = 0
        own = cases = used = 0.0
        counted = 0
        for e in es:
            s = e.get("agent_eval_shadow") or {}
            pick = s.get("pick")
            if not pick:
                continue
            res = outcome(pick, e)
            if res not in ("win", "loss"):
                continue
            n += 1
            hits += res == "win"
            if isinstance(s.get("pick_probability"), (int, float)):
                own += s["pick_probability"] / 100
                counted += 1
            cases += len(s.get("memory_cases") or [])
            used += len(s.get("memory_used") or [])
        if not n:
            continue
        own_rate = own / counted if counted else None
        rows.append([week_label(monday), n, pct(hits / n), pct(own_rate),
                     pp(None if own_rate is None else hits / n - own_rate), f"{cases / n:.1f}", f"{used / n:.1f}"])
    return table(["Woche", "Tipps", "Trefferquote", "eigene Schätzung", "Abstand (Treffer − Schätzung)",
                  "Fälle im Gedächtnis je Spiel", "davon benutzt"], rows)


def section_combos(combos: list, tips: list, since: str) -> str:
    finished = {}
    for e in tips:
        if e.get("result"):
            finished[(_norm(e["home_team"]), _norm(e["away_team"]))] = e["result"]

    def settle(ticket):
        outs = []
        for leg in ticket["legs"]:
            r = finished.get((_norm(leg["home_team"]), _norm(leg["away_team"])))
            outs.append(None if r is None else grade(leg, leg["home_team"], leg["away_team"], r["home_score"], r["away_score"]))
        if "loss" in outs:
            return "loss"
        return "win" if all(o in ("win", "push") for o in outs) else None

    # A day's combos are rebuilt at each kickoff; the last version before its
    # first kickoff is the one that could still be placed (scripts/grade_combos.py).
    final = {}
    for t in combos:
        if str(t.get("date", ""))[:10] < since or t.get("policy") not in COMBO_RULES:
            continue
        first = t.get("first_kickoff") or min(l["commence_time"] for l in t["legs"])
        final[(t.get("competition"), t.get("policy"), t.get("leg_count"), first[:16])] = t
    stats = defaultdict(lambda: [0, 0, 0.0, 0.0, 0])
    for t in final.values():
        s = stats[(week_of(t["date"]), t["policy"], t["leg_count"])]
        res = settle(t)
        if res is None:
            s[4] += 1
            continue
        s[0] += 1
        s[3] += t.get("estimated_probability") or 0
        if res == "win":
            s[1] += 1
            s[2] += t["combined_odds"] - 1
        else:
            s[2] -= 1
    rows = []
    for (monday, policy, size), (n, won, u, exp, open_) in sorted(stats.items()):
        rows.append([week_label(monday), COMBO_RULES.get(policy, policy), f"{size}er", n,
                     f"{won} ({pct(won / n) if n else '–'})", pct(exp / n) if n else "–", units(u), open_ or ""])
    return table(["Woche", "Regel", "Größe", "Scheine", "gewonnen", "erwartet", "Einheiten", "offen"], rows)


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--api", default=DEFAULT_API)
    parser.add_argument("--since", default="2026-11-09")
    parser.add_argument("--local", action="store_true", help="read data/logs instead of the server")
    parser.add_argument("--recent-weeks", type=int, default=2)
    args = parser.parse_args()
    tips, combos = load(args)
    entries = finished_entries(tips, args.since)
    if not entries:
        print(f"Keine abgerechneten Spiele seit {args.since}.")
        return
    print(f"# Tipp-Analyse seit {args.since}\n")
    print(f"{len(entries)} abgerechnete Spiele, das letzte am {entries[-1]['commence_time'][:10]}. "
          "„Markt erwartet“ ist die Trefferquote, die die Quoten der Buchmacher vorhersagen; "
          "„besser als Markt“ ist der einzige Hinweis auf echtes Können. Einheiten = Gewinn bei 1 € pro Tipp.\n")
    print("## 1. Wer trifft wie oft, Woche für Woche\n")
    print(section_tippers(entries))
    print("\n## 2. Nach Tipp-Art\n")
    print(section_kinds(entries, args.recent_weeks))
    print("\n## 3. Schatten gegen KI-Tipp, wo sie verschieden getippt haben\n")
    print(section_differing(entries))
    print("\n## 4. Lernt der Schatten?\n")
    print("Lernen hieße: seine eigene Schätzung kommt der Trefferquote näher, und er trifft öfter als der Markt.\n")
    print(section_learning(entries))
    print("\n## 5. Kombis\n")
    print(section_combos(combos, tips, args.since))
    print("\nWenige Tipps pro Woche schwanken stark: erst ab etwa 30 Tipps sagt eine Trefferquote etwas, "
          "bei Kombis erst ab Dutzenden Scheinen.")


if __name__ == "__main__":
    main()
