"""Append-only pre-match snapshots and fixed-unit settlement, stdlib only."""
import hashlib
import json
import math
import re
import unicodedata
from collections import Counter, defaultdict
from datetime import datetime, timezone

SPORTS = {"soccer_uefa_champs_league", "soccer_germany_bundesliga", "soccer_germany_bundesliga2"}


def timestamp(value):
    dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if dt.tzinfo is None:
        raise ValueError("Timestamp must include timezone")
    return dt.astimezone(timezone.utc)


def norm(name):
    s = unicodedata.normalize("NFKD", str(name)).encode("ascii", "ignore").decode().lower()
    s = re.sub(r"[^a-z0-9]", "", s)
    return {"fcschalke04": "schalke04", "bayer04leverkusen": "bayerleverkusen",
            "bayernmunchen": "bayernmunich", "fcbayernmunchen": "bayernmunich",
            "usa": "unitedstates"}.get(s, s)


def fixture_key(entry):
    # Kickoff is part of identity: repeat fixtures and new seasons never collide.
    return (entry.get("sport_key", ""), norm(entry["home_team"]), norm(entry["away_team"]), timestamp(entry["commence_time"]).isoformat())


def eligibility(entry):
    try:
        kickoff = timestamp(entry.get("commence_time"))
        logged = timestamp(entry.get("logged_at"))
    except (TypeError, ValueError):
        return "missing_or_invalid_time"
    if logged >= kickoff or entry.get("in_play"):
        return "logged_after_kickoff"
    if entry.get("sport_key") not in SPORTS:
        return "unidentified_or_nonclub_competition"
    if (kickoff - logged).total_seconds() > 24 * 3600:
        return "more_than_24h_before_kickoff"
    generated = (entry.get("prediction") or {}).get("generated_at")
    if generated:
        try:
            if timestamp(generated) > logged:
                return "prediction_from_future"
        except ValueError:
            return "invalid_prediction_time"
    return None


def snapshot(match, now):
    entry = dict(match)
    entry.update(schema_version=3, logged_at=now.isoformat())
    reason = eligibility(entry)
    if reason:
        return None, reason
    canonical = {k: v for k, v in entry.items() if k not in ("logged_at", "snapshot_id")}
    entry["snapshot_id"] = hashlib.sha256(json.dumps(canonical, sort_keys=True).encode()).hexdigest()
    return entry, None


def split_line(line):
    if not math.isfinite(line) or abs(line * 4 - round(line * 4)) > 1e-8:
        raise ValueError("Unsupported handicap/total line")
    if round(line * 4) % 2:
        low = math.floor(line * 2) / 2
        return [low, low + 0.5]
    return [line]


def settlement(bet, home, away, hs, aws):
    odds = float(bet["best_odds"])
    if not math.isfinite(odds) or odds <= 1:
        raise ValueError("Invalid decimal odds")
    if hs < 0 or aws < 0 or hs % 1 or aws % 1:
        raise ValueError("Invalid final score")
    market, outcome = bet["market"], bet["outcome"]
    team = norm(bet.get("team", ""))
    def margin():
        if team == norm(home):
            return hs - aws
        if team == norm(away):
            return aws - hs
        raise ValueError("Unmatched bet team")
    if market == "1X2":
        if outcome == "draw":
            values = [1 if hs == aws else -1]
        else:
            values = [1 if margin() > 0 else -1]
    elif market.startswith("Handicap "):
        values = [margin() + line for line in split_line(float(market.split()[-1]))]
    elif market.startswith("Over/Under "):
        if outcome not in ("Over", "Under"):
            raise ValueError("Unknown total outcome")
        values = [(hs + aws - line) * (1 if outcome == "Over" else -1) for line in split_line(float(market.split()[-1]))]
    elif market == "BTTS":
        if outcome.lower() not in ("yes", "no"):
            raise ValueError("Unknown BTTS outcome")
        values = [1 if ((hs > 0 and aws > 0) == (outcome.lower() == "yes")) else -1]
    else:
        raise ValueError("Unsupported market")
    payouts = [(odds - 1 if v > 0 else -1 if v < 0 else 0) for v in values]
    units = sum(payouts) / len(payouts)
    if all(v == 0 for v in values):
        label = "push"
    elif any(v == 0 for v in values):
        label = "half_win" if units > 0 else "half_loss"
    else:
        label = "win" if units > 0 else "loss"
    return label, units


def roles(entry):
    combined = entry.get("combined") or {}
    picks = {"displayed_tip": combined.get("consensus_pick"),
             "value_pick": entry.get("recommendation") if not entry.get("recommendation_warning") else None,
             "model_choice": entry.get("model_favorite"), "safest_pick": entry.get("safest_pick"),
             "ai_pick": (entry.get("agent_eval") or {}).get("pick")}
    for role, bet in picks.items():
        if bet:
            yield role, bet
    for name, decision in (combined.get("strategy_comparison") or {}).get("strategies", {}).items():
        if decision.get("pick"):
            yield "strategy:" + name, decision["pick"]
    seen = set()
    for bet in entry.get("bets", entry.get("green_bets", []) + entry.get("red_bets", [])):
        key = (bet["market"], bet["outcome"], bet.get("team"))
        if key not in seen:
            yield "all_candidates", bet
            seen.add(key)


def evaluate_snapshots(entries, results):
    exclusions = Counter()
    latest = {}
    for entry in entries:
        reason = eligibility(entry)
        if reason:
            exclusions[reason] += 1
            continue
        key = fixture_key(entry)
        if key not in latest or timestamp(entry["logged_at"]) > timestamp(latest[key]["logged_at"]):
            latest[key] = entry
    finished = {}
    for result in results:
        try:
            key = fixture_key(result)
            observed = timestamp(result.get("observed_at"))
            if (result.get("completed") and result.get("score_scope") == "regulation"
                    and observed > timestamp(result.get("commence_time"))):
                if key not in finished or observed > timestamp(finished[key]["observed_at"]):
                    finished[key] = result
        except (KeyError, ValueError, TypeError):
            continue
    grouped = defaultdict(list)
    details = []
    no_bet = 0
    strategy_counts = defaultdict(Counter)
    for key, entry in latest.items():
        result = finished.get(key)
        if result is None:
            exclusions["missing_unambiguous_regulation_result"] += 1
            continue
        if not (entry.get("combined") or {}).get("consensus_pick"):
            no_bet += 1
        for name, decision in ((entry.get("combined") or {}).get("strategy_comparison") or {}).get("strategies", {}).items():
            counter = strategy_counts[(entry["sport_key"], "strategy:" + name)]
            counter["evaluated_fixtures"] += 1
            counter["paper_bets" if decision.get("pick") else "no_bets"] += 1
        for role, bet in roles(entry):
            try:
                if bet.get("quote_last_update") and timestamp(bet["quote_last_update"]) > timestamp(entry["logged_at"]):
                    raise ValueError("Future quote")
                label, units = settlement(bet, entry["home_team"], entry["away_team"], result["home_score"], result["away_score"])
            except (ValueError, TypeError, KeyError):
                exclusions["invalid_bet_or_quote"] += 1
                continue
            market = "Handicap" if bet["market"].startswith("Handicap") else "Over/Under" if bet["market"].startswith("Over/Under") else bet["market"]
            row = {"fixture": key, "role": role, "market": bet["market"], "outcome": label, "profit_units": units,
                   "odds": bet["best_odds"], "snapshot_id": entry.get("snapshot_id"),
                   "odds_stage": entry.get("odds_stage", "untracked"),
                   "odds_fetched_at": entry.get("odds_fetched_at"),
                   "selection_policy": entry.get("selection_policy", "unknown")}
            binary = market in ("1X2", "BTTS") or (market in ("Handicap", "Over/Under") and float(bet["market"].split()[-1]) % 1 == 0.5)
            if binary:
                actual = int(label == "win")
                for name, field in (("model", "model_probability_raw"), ("market", "market_probability")):
                    probability = bet.get(field)
                    if isinstance(probability, (int, float)) and 0 <= probability <= 1:
                        row[f"{name}_brier"] = (probability - actual) ** 2
            details.append(row)
            grouped[(entry["sport_key"], role, market)].append(row)
    summary = []
    for (sport, role, market), rows in sorted(grouped.items()):
        units = sum(r["profit_units"] for r in rows)
        # All placed stakes count, including full pushes and half settlements.
        stats = {"competition": sport, "role": role, "market": market, "bets": len(rows),
                        "stake_units": len(rows), "profit_units": units, "roi": units / len(rows),
                        "outcomes": dict(Counter(r["outcome"] for r in rows))}
        for name in ("model", "market"):
            values = [r[f"{name}_brier"] for r in rows if f"{name}_brier" in r]
            stats[f"{name}_brier_n"] = len(values)
            stats[f"{name}_brier"] = sum(values) / len(values) if values else None
        summary.append(stats)
    strategy_summary = []
    for (sport, role), counts in sorted(strategy_counts.items()):
        rows = [r for r in details if r["fixture"][0] == sport and r["role"] == role]
        daily = defaultdict(float)
        for row in rows:
            daily[row["fixture"][-1][:10]] += row["profit_units"]
        balance = peak = drawdown = 0.0
        for day in sorted(daily):
            balance += daily[day]
            peak = max(peak, balance)
            drawdown = max(drawdown, peak - balance)
        strategy_summary.append({"competition": sport, "strategy": role.removeprefix("strategy:"),
                                 **counts, "settled_bets": len(rows), "profit_units": balance,
                                 "roi": balance / len(rows) if rows else None,
                                 "unsettled_or_invalid_bets": counts["paper_bets"] - len(rows),
                                 "max_drawdown_end_of_day_units": drawdown})
    return {"input_snapshots": len(entries), "eligible_fixtures": len(latest), "no_bet_fixtures": no_bet,
            "strategies": strategy_summary,
            "exclusions": dict(exclusions), "groups": summary, "settlements": details,
            "interpretation": "One-unit returns at recorded odds, not actual account profit. No evidence of edge without sufficient prospective data."}
