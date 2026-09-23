"""Retrospective selection comparison; never changes the live betting policy.

Use stored chronological H/D/A predictions and downloaded football-data CSVs.
All-market results additionally reconstruct the current Poisson recipe using
strictly earlier scores; these are NOT archived live tips or an untouched test.
"""
import argparse
from collections import Counter, defaultdict
from datetime import datetime, timezone
import csv
import hashlib
import json
import math
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from src.bet_selection import price_bet, same_bet
from src.bet_audit import settlement

ALIASES = {
    "Bielefeld": "Arminia Bielefeld", "Bochum": "VfL Bochum",
    "Darmstadt": "SV Darmstadt 98", "Dortmund": "Borussia Dortmund",
    "Ein Frankfurt": "Eintracht Frankfurt", "FC Koln": "1. FC Köln",
    "Freiburg": "SC Freiburg", "Greuther Furth": "Greuther Fürth",
    "Hamburg": "Hamburger SV", "Heidenheim": "1. FC Heidenheim",
    "Hertha": "Hertha Berlin", "Hoffenheim": "TSG Hoffenheim",
    "Leverkusen": "Bayer Leverkusen", "M'gladbach": "Borussia Mönchengladbach",
    "Mainz": "1. FSV Mainz 05", "St Pauli": "FC St. Pauli", "Stuttgart": "VfB Stuttgart",
}
STRATEGIES = {
    "kelly_baseline": "Bisherige Kelly-Auswahl (innerhalb des Testangebots)",
    "max_ev": "Höchster EV",
    "probability_near_ev": "Höchste Trefferchance bei mindestens 80% des besten EV",
    "kelly_model_agrees": "Kelly-Tipp nur bei exakter Zustimmung von Model's Choice",
    "kelly_market_agrees": "Kelly-Tipp nur bei exakter Zustimmung des 1X2-Marktfavoriten",
}


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def write(path, data):
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False, allow_nan=False) + "\n")


def load_joined(predictions, odds_dir):
    rows = [json.loads(l) for l in predictions.read_text().splitlines() if l.strip()]
    rows = [r for r in rows if r["competition"] == "bundesliga"
            and r["strategy"] == "verified_only/monthly/raw"]
    index = {}
    for path in sorted(odds_dir.glob("D1_*.csv")):
        for r in csv.DictReader(path.open(encoding="utf-8-sig")):
            date = datetime.strptime(r["Date"], "%d/%m/%Y").date().isoformat()
            key = (date, ALIASES.get(r["HomeTeam"], r["HomeTeam"]), ALIASES.get(r["AwayTeam"], r["AwayTeam"]))
            if key in index:
                raise ValueError(f"Duplicate odds fixture: {key}")
            index[key] = r
    joined, excluded, seen = [], [], set()
    for r in rows:
        key = (r["date"], r["home"], r["away"])
        if key in seen:
            raise ValueError(f"Duplicate prediction: {key}")
        seen.add(key)
        q = index.get(key)
        if q is None:
            excluded.append({"fixture": key, "reason": "no_exact_date_team_match"})
            continue
        if (int(q["FTHG"]), int(q["FTAG"]), q["FTR"]) != (r["home_goals"], r["away_goals"], r["actual"]):
            raise ValueError(f"Score mismatch: {key}")
        if not r["fit"]["training_end"] < r["fit"]["cutoff"] <= r["date"]:
            raise ValueError(f"Training leakage: {key}")
        p = r["probabilities"]
        if len(p) != 3 or any(not math.isfinite(v) or v < 0 for v in p) or abs(sum(p) - 1) > .001:
            raise ValueError(f"Invalid probabilities: {key}")
        joined.append((r, q))
    return sorted(joined, key=lambda pair: (pair[0]["date"], pair[0]["home"], pair[0]["away"])), excluded


def complete_prices(row, columns):
    try:
        values = [float(row[c]) for c in columns]
        return values if all(math.isfinite(v) and v > 1 for v in values) else None
    except (KeyError, ValueError, TypeError):
        return None


def candidates(prediction, row, closing=False, all_markets=False):
    prefix = "B365C" if closing else "B365"
    prices = complete_prices(row, [prefix + s for s in "HDA"])
    if prices is None:
        return None, ["missing_complete_1x2"]
    ps = [prediction[k] for k in ("probability_home_win", "probability_draw", "probability_away_win")]
    fav = max(range(3), key=lambda i: ps[i])
    home, away = prediction["home_team"], prediction["away_team"]
    favorite_team = [home, None, away][fav]
    bets, missing = [], []

    def add(market, outcome, team, odds, market_probability):
        bet = {"market": market, "outcome": outcome, "team": team, "best_odds": odds}
        priced = price_bet(bet, prediction, None)
        priced.pop("payout_distribution")
        bet.update(priced, market_probability=market_probability)
        contradiction = ps[fav] > .5 and (
            (market == "1X2" and outcome != ["home_win", "draw", "away_win"][fav])
            or (market == "Handicap +0.5" and favorite_team is not None and team != favorite_team))
        bet["suspicious"] = (bet["expected_value"] > .25 or contradiction
            or (market_probability is not None and abs(bet["probability"] - market_probability) > .15))
        bets.append(bet)

    denominator = sum(1 / o for o in prices)
    for i, o in enumerate(prices):
        add("1X2", ["home_win", "draw", "away_win"][i], [home, None, away][i], o, (1 / o) / denominator)
    if all_markets:
        totals = complete_prices(row, [prefix + ">2.5", prefix + "<2.5"])
        if totals:
            denominator = sum(1 / o for o in totals)
            for label, o in zip(("Over", "Under"), totals):
                add("Over/Under 2.5", label, None, o, (1 / o) / denominator)
        else:
            missing.append("missing_complete_total_2.5")
        spreads = complete_prices(row, [prefix + "AHH", prefix + "AHA"])
        try:
            line = float(row["AHCh" if closing else "AHh"])
            if not math.isfinite(line) or abs(line * 4 - round(line * 4)) > 1e-8:
                raise ValueError("Invalid line")
        except (KeyError, ValueError, TypeError):
            spreads = None
        if spreads:
            denominator = sum(1 / o for o in spreads)
            for team, point, o in ((home, line, spreads[0]), (away, -line, spreads[1])):
                if point == 0:
                    point = 0.0
                name = f"Handicap {'+' if point > 0 else ''}{point}"
                # Push/quarter lines have no binary P(profit) market estimate.
                q = (1 / o) / denominator if point % 1 == .5 else None
                add(name, "handicap", team, o, q)
        else:
            missing.append("missing_complete_handicap")
    return bets, missing


def select(bets):
    # Reproduce API stable sorting: EV first, then rounded quarter-Kelly.
    ranked = sorted(bets, key=lambda b: b["expected_value"], reverse=True)
    clean = [b for b in ranked if not b["suspicious"] and b["expected_value"] > 0 and b["kelly_stake_pct"] >= 1]
    kelly = max(clean, key=lambda b: round(b["kelly_stake_pct"], 1), default=None)
    ev = max(clean, key=lambda b: b["expected_value"], default=None)
    near = [b for b in clean if b["expected_value"] >= .8 * ev["expected_value"]] if ev else []
    highest_p = max(near, key=lambda b: (b["probability"], b["expected_value"]), default=None)
    hda = [b for b in bets if b["market"] == "1X2"]
    model = max(hda, key=lambda b: b["probability"])
    market = max(hda, key=lambda b: b["market_probability"])
    return {"kelly_baseline": kelly, "max_ev": ev, "probability_near_ev": highest_p,
            "kelly_model_agrees": kelly if same_bet(kelly, model) else None,
            "kelly_market_agrees": kelly if same_bet(kelly, market) else None}


def summarize(records):
    stats = {}
    for name in STRATEGIES:
        selected = [r["decisions"][name] for r in records if r["decisions"][name] is not None]
        daily = defaultdict(float)
        for r in records:
            if r["decisions"][name] is not None:
                daily[r["date"]] += r["decisions"][name]["profit_units"]
        balance = peak = drawdown = 0
        for day in sorted(daily):
            balance += daily[day]
            peak = max(peak, balance)
            drawdown = max(drawdown, peak - balance)
        outcomes = Counter(r["settlement"] for r in selected)
        differences = sum(not (same_bet(r["decisions"][name], r["decisions"]["kelly_baseline"])
                              or r["decisions"][name] is r["decisions"]["kelly_baseline"] is None) for r in records)
        stats[name] = {"fixtures": len(records), "bets": len(selected), "no_bets": len(records) - len(selected),
            "outcomes": dict(outcomes), "profit_units": balance, "roi": balance / len(selected) if selected else None,
            "positive_return_rate": sum(r["profit_units"] > 0 for r in selected) / len(selected) if selected else None,
            "max_drawdown_end_of_day_units": drawdown, "different_decisions_vs_kelly": differences}
    return stats


def uncertainty(records, repetitions=2000):
    """Paired resampling by calendar week, abstentions have zero profit.

    Descriptive intervals only: previously explored seasons, no multiplicity
    correction, weekly clusters do not remove all football dependence.
    """
    import numpy as np
    groups = defaultdict(list)
    for r in records:
        groups[datetime.fromisoformat(r["date"]).isocalendar()[:2]].append(r)
    names = list(STRATEGIES)
    profit, stakes, fixture_counts = [], [], []
    for week in sorted(groups):
        rows = groups[week]
        profit.append([sum((r["decisions"][n] or {}).get("profit_units", 0) for r in rows) for n in names])
        stakes.append([sum(r["decisions"][n] is not None for r in rows) for n in names])
        fixture_counts.append(len(rows))
    if not profit:
        return {}
    profit, stakes, fixture_counts = np.array(profit), np.array(stakes), np.array(fixture_counts)
    rng = np.random.default_rng(20260923)
    ix = rng.integers(0, len(profit), size=(repetitions, len(profit)))
    p, s, n = profit[ix].sum(axis=1), stakes[ix].sum(axis=1), fixture_counts[ix].sum(axis=1)
    answer = {}
    for i, name in enumerate(names):
        valid = s[:, i] > 0
        roi = p[valid, i] / s[valid, i]
        paired = (p[:, i] - p[:, 0]) / n
        answer[name] = {"roi_95_percent_week_bootstrap": np.quantile(roi, [.025, .975]).tolist() if len(roi) else None,
            "profit_per_fixture_difference_vs_kelly_95_percent": np.quantile(paired, [.025, .975]).tolist()}
    return answer


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--odds-dir", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    if args.out.exists():
        raise SystemExit("Choose a new output directory; reports are immutable")
    source = ROOT / "data/model_reports/retraining_v3/predictions.jsonl"
    old_protocol = json.loads((source.parent / "protocol.json").read_text())
    for name, checksum in old_protocol["sources"].items():
        if digest(ROOT / "data/club_raw" / name) != checksum:
            raise ValueError(f"Historical source changed: {name}")
    pairs, exclusions = load_joined(source, args.odds_dir)
    args.out.mkdir(parents=True)
    protocol = {"created_at": datetime.now(timezone.utc).isoformat(), "model": "verified_only/monthly/raw",
        "selection_rules": STRATEGIES, "near_ev_fraction": .8,
        "filters": {"max_ev": .25, "max_probability_gap": .15, "min_quarter_kelly_pct": 1,
                    "exclude_confident_model_contradiction": True},
        "odds": "One bookmaker: Bet365; pre-closing primary, closing sensitivity; devig same-book complete markets",
        "stakes": "One unit per selected bet, maximum one bet per fixture per strategy",
        "selection_policy": "No strategy optimized on results, no automatic winner promotion",
        "reused_model_development_seasons": ["2021-22", "2022-23", "2023-24"],
        "later_previously_examined_season": "2025-26", "matched_fixtures": len(pairs), "exclusions": exclusions,
        "limitations": ["Retrospective, not original live bet records or an untouched holdout",
            "1X2 uses saved chronological model probabilities; totals/handicaps reconstructed today from earlier scores",
            "Only Bundesliga; no conclusion for Nations League or Champions League",
            "No historical AI picks, research or three-book stress references; those variants cannot be graded here",
            "Only total 2.5 and the offered main handicap line; not the full live menu",
            "Single-book market reference differs from the live multi-book average",
            "Pre-closing quotes have no per-quote timestamps; freshness/final-hour policy cannot be replayed",
            "Archived quotes do not guarantee execution, limits or availability",
            "Training-source hashes verified, but the complete training corpus was not independently reaudited",
            "Bootstrap intervals are descriptive; no correction for previous model experiments"],
        "source_hashes": {str(source.relative_to(ROOT)): digest(source),
                          **{str(p): digest(p) for p in sorted(args.odds_dir.glob('D1_*.csv'))}},
        "code_hashes": {n: digest(ROOT / n) for n in ("scripts/compare_bet_selection.py", "src/poisson_model.py", "src/club_backtest.py", "src/bet_selection.py", "src/bet_audit.py")},
        "data_source": "https://www.football-data.co.uk/germanym.php"}
    # Persist definitions before evaluating any outcomes.
    write(args.out / "protocol.json", protocol)
    from src.club_data_loader import load_completed_matches
    from src.club_features_v3 import prepare_history
    from src.club_backtest import rating_context
    from src.poisson_model import predict_scorelines
    import pandas as pd
    history = prepare_history(load_completed_matches())
    data = defaultdict(list)
    missing = Counter()
    contexts = {}
    for i, (r, odds) in enumerate(pairs):
        date = pd.Timestamp(r["date"])
        if date not in contexts:
            past = history[history.date < date]
            contexts = {date: (past, rating_context(past))}
        past, context = contexts[date]
        probabilities = [round(float(p / sum(r["probabilities"])), 4) for p in r["probabilities"]]
        prediction = dict(zip(("probability_home_win", "probability_draw", "probability_away_win"), probabilities))
        prediction.update(home_team=r["home"], away_team=r["away"])
        score = predict_scorelines(past, r["home"], r["away"], club_mode=True,
                                  target_result_probs=tuple(probabilities), rating_context=context)
        prediction["score_prediction"] = score
        for closing in (False, True):
            for all_markets in (False, True):
                scope = ("all_markets" if all_markets else "1x2") + ("_closing" if closing else "_preclosing")
                bets, reasons = candidates(prediction, odds, closing, all_markets)
                missing.update(scope + ":" + reason for reason in reasons)
                if bets is None:
                    continue
                decisions = select(bets)
                record = {k: r[k] for k in ("season", "date", "home", "away", "home_goals", "away_goals")}
                record.update(scope=scope, training_end=r["fit"]["training_end"], decisions={}, candidates=bets)
                for name, bet in decisions.items():
                    if bet is None:
                        record["decisions"][name] = None
                    else:
                        label, profit = settlement(bet, r["home"], r["away"], r["home_goals"], r["away_goals"])
                        record["decisions"][name] = dict(bet, settlement=label, profit_units=profit)
                data[scope].append(record)
        if (i + 1) % 200 == 0:
            print(f"Compared {i + 1}/{len(pairs)} fixtures", flush=True)
    report = {"protocol": protocol, "missing_markets": dict(missing), "scopes": {}}
    with (args.out / "decisions.jsonl").open("w") as stream:
        for scope, records in data.items():
            for r in records:
                stream.write(json.dumps(r, ensure_ascii=False, allow_nan=False) + "\n")
            stats = {}
            for season in ["all", *sorted({r["season"] for r in records})]:
                group = records if season == "all" else [r for r in records if r["season"] == season]
                stats[season] = {"summary": summarize(group), "uncertainty": uncertainty(group)}
            report["scopes"][scope] = stats
    write(args.out / "results.json", report)
    lines = ["# Vergleich der Wett-Auswahl", "", "Retrospektiver Test mit unverändertem Modell; keine Änderung der Website.",
             "", f"{len(pairs)} exakt über Datum, Teams und Ergebnis zugeordnete Bundesliga-Spiele.",
             "Quoten: Bet365 aus [Football-Data](https://www.football-data.co.uk/germanym.php).", "",
             "Je Tipp eine Einheit. Ausrufezeichen-Kandidaten sind bei allen Regeln ausgeschlossen.",
             "Treffer = positive Auszahlung einschließlich halber Gewinne; Rückzahlungen zählen zum Einsatz.",
             "", "Die Baseline bildet die bestehende Kelly-Sortierung auf diesem begrenzten Quotenangebot ab, nicht sämtliche historischen Live-Tipps."]
    for scope, seasons in report["scopes"].items():
        lines += ["", f"## {scope}", "", "| Saison | Regel | Wetten | Treffer | Profit (Einh.) | ROI | Max. Rückgang* | Andere Entscheidungen als Kelly |", "|---|---|---:|---:|---:|---:|---:|---:|"]
        for season, results in seasons.items():
            for name, s in results["summary"].items():
                hit = f"{s['positive_return_rate']:.1%}" if s['positive_return_rate'] is not None else "—"
                roi = f"{s['roi']:+.1%}" if s['roi'] is not None else "—"
                lines.append(f"| {season} | {STRATEGIES[name]} | {s['bets']} | {hit} | {s['profit_units']:+.2f} | {roi} | {s['max_drawdown_end_of_day_units']:.2f} | {s['different_decisions_vs_kelly']} |")
    lines += ["", "*Rückgang des kumulierten Profits jeweils am Tagesende; keine Kelly-Kontorendite.",
              "", "## Grenzen", "", *["- " + x for x in protocol["limitations"]],
              "", "Details, Unsicherheitsintervalle, Quellhashes und jede Einzelentscheidung stehen in den JSON-Dateien daneben."]
    (args.out / "README.md").write_text("\n".join(lines) + "\n")
    print(f"Report: {args.out}")


if __name__ == "__main__":
    main()
