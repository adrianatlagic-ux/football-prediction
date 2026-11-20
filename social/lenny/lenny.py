"""Lenny Zero bot: decides the next episode from GoalIQ's real tips and results.

    python3 social/lenny/lenny.py next              # print the brief for the next episode
    python3 social/lenny/lenny.py commit BRIEF.json # record an episode once it was produced
    python3 social/lenny/lenny.py status            # bankroll and open bet

Lenny follows GoalIQ with one fixed rule: on every matchday he stakes half his
bankroll on GoalIQ's first published tip (a game with one of his featured clubs
first). Before the matchday he announces that he is going in; the tip itself is
only published in the app shortly before kickoff. Afterwards the real result
decides whether he celebrates or crashes. The money is fictional, the tips, odds
and results are the real logged ones (data/logs/tips). The rule never looks at
results, so nothing is cherry-picked.

`next` never changes anything; only `commit` writes the state, so a failed
video production does not move the story on.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT))

from scripts.grade_bets import grade  # noqa: E402
from src.log_store import norm  # noqa: E402

TZ = ZoneInfo("Europe/Berlin")
CONFIG = HERE / "config.json"
STATE = HERE / "state.json"
FIXTURES = ROOT / "data" / "fixtures"
TIPS = ROOT / "data" / "logs" / "tips"
COMPETITION_FILES = {"bl": "bundesliga", "cl": "champions-league", "nl": "nations-league"}
COMPETITION_NAMES = {"bl": "Bundesliga", "cl": "Champions League", "nl": "Nations League"}

# Tip statuses where GoalIQ published a bet. Anything else means "no tip for this game".
PUBLISHED = {"ok"}
# A match still missing from the logs this long after kickoff was never logged: Lenny sat it out.
STALE_DAYS = 3


# ---------------------------------------------------------------- loading

def load_json(path: Path, default=None):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default


def load_config() -> dict:
    return load_json(CONFIG, {})


def fresh_state(config: dict) -> dict:
    return {"episode": 0, "bankroll_eur": 3.12, "open_bet": None, "results": [], "episodes": []}


def load_state(config: dict) -> dict:
    return load_json(STATE) or fresh_state(config)


def load_fixtures(competitions) -> list[dict]:
    out = []
    for key in competitions:
        for f in load_json(FIXTURES / f"{key}.json", []) or []:
            kickoff = datetime.fromisoformat(f"{f['date']}T{f.get('time') or '15:30'}").replace(tzinfo=TZ)
            out.append({**f, "competition": key, "kickoff": kickoff})
    return out


def load_tips(competitions) -> list[dict]:
    out = []
    for key in competitions:
        path = TIPS / f"{COMPETITION_FILES[key]}.jsonl"
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except OSError:
            continue
        out += [json.loads(line) for line in lines if line.strip()]
    return out


# ---------------------------------------------------------------- matching

def _kickoff_utc(entry: dict) -> datetime:
    return datetime.fromisoformat(entry["commence_time"].replace("Z", "+00:00"))


# ---------------------------------------------------------------- tips in words

def describe_tip(tip: dict, home: str, away: str) -> str:
    market, outcome, team = tip["market"], tip["outcome"], tip.get("team")
    if market == "1X2":
        return "a draw" if outcome == "draw" else f"{team} to win"
    if market.startswith("Over/Under"):
        line = market.split()[-1]
        return f"{'over' if outcome == 'Over' else 'under'} {line} goals"
    if market == "BTTS":
        return "both teams to score" if outcome.lower() == "yes" else "not both teams to score"
    if market == "Handicap +0.5":
        return f"{team} not to lose"
    if market == "Handicap 0.0":
        return f"{team} to win (stake back on a draw)"
    if market.startswith("Handicap"):
        point = float(market.split()[-1])
        if point < 0:
            return f"{team} to win by {int(-point + 0.5)} or more"
        return f"{team} not to lose by {int(point + 0.5)} or more"
    return f"{market} {outcome} {team or ''}".strip()


# ---------------------------------------------------------------- story logic

def mood(state: dict) -> str:
    last = [r["outcome"] for r in state["results"][-3:]]
    if not last:
        return "hungry"
    if last[-1] == "loss" and last.count("loss") >= 2:
        return "rock_bottom"
    if last[-1] == "loss":
        return "shaken"
    if last.count("win") == 3:
        return "on_fire"
    if last[-1] == "win":
        return "rising"
    return "steady"


def streak(state: dict) -> dict:
    kind, n = None, 0
    for r in reversed(state["results"]):
        if r["outcome"] == "push":
            continue
        if kind is None:
            kind = r["outcome"]
        if r["outcome"] != kind:
            break
        n += 1
    return {"kind": kind, "length": n}


def matchdays(fixtures: list[dict]) -> list[dict]:
    """Fixtures grouped into matchdays (competition + round), each with its kickoff window."""
    groups = {}
    for f in fixtures:
        groups.setdefault((f["competition"], f.get("group") or f["kickoff"].date().isoformat()), []).append(f)
    out = []
    for (comp, group), games in groups.items():
        games.sort(key=lambda g: g["kickoff"])
        out.append({"id": f"{comp}:{group}:{games[0]['kickoff'].date().isoformat()}", "competition": comp,
                    "group": group, "start": games[0]["kickoff"], "end": games[-1]["kickoff"], "games": games})
    return sorted(out, key=lambda m: m["start"])


def pick_matchday(fixtures: list[dict], config: dict, now: datetime, covered: set) -> dict | None:
    """The next matchday that starts within the horizon and has not been announced yet."""
    horizon = now + timedelta(days=config.get("preview_horizon_days", 4))
    for md in matchdays(fixtures):
        if now + timedelta(hours=2) <= md["start"] <= horizon and md["id"] not in covered:
            return md
    return None


def lennys_tip(bet: dict, tips: list[dict], featured: set) -> dict | None:
    """The rule, fixed before kickoff: GoalIQ's first published tip of the matchday,
    a match with one of Lenny's featured clubs first. Never chosen by the result."""
    start = datetime.fromisoformat(bet["start"]) - timedelta(hours=3)
    end = datetime.fromisoformat(bet["end"]) + timedelta(hours=3)
    published = [e for e in tips if start <= _kickoff_utc(e) <= end
                 and (e.get("bet_tip") or {}).get("status") in PUBLISHED and (e.get("bet_tip") or {}).get("tip")]
    if not published:
        return None

    def rank(e):
        stars = (norm(e["home_team"]) in featured) + (norm(e["away_team"]) in featured)
        return (-min(stars, 1), _kickoff_utc(e))

    return sorted(published, key=rank)[0]


def settle(entry: dict, stake: float) -> dict | None:
    """Grade GoalIQ's real tip against the real result. None while the result is missing."""
    tip = entry["bet_tip"]["tip"]
    result = entry.get("result")
    if not result:
        return None
    hs, as_ = result["home_score"], result["away_score"]
    outcome = grade(tip, entry["home_team"], entry["away_team"], hs, as_)
    if outcome is None:
        return None
    odds = float(tip["best_odds"])
    profit = {"win": stake * (odds - 1), "loss": -stake, "push": 0.0}[outcome]
    return {"outcome": outcome, "score": f"{hs}-{as_}", "odds": odds,
            "tip_text": describe_tip(tip, entry["home_team"], entry["away_team"]),
            "profit_eur": round(profit, 2)}


# Lenny only loses a life stage once he falls clearly below it, so a bankroll
# hovering around a threshold does not make him move house every week.
DOWN_BUFFER = 0.6


def _stages(config: dict) -> list[dict]:
    return sorted(config.get("life_stages", []), key=lambda s: s["min_eur"])


def life_level(bankroll: float, level: int | None, config: dict) -> int | None:
    """The life stage after a bankroll change: up as soon as he can afford it, down only with a buffer."""
    stages = _stages(config)
    if not stages:
        return None
    affordable = max(i for i, s in enumerate(stages) if bankroll >= s["min_eur"])
    if level is None or affordable >= level:
        return affordable
    while level > 0 and bankroll < stages[level]["min_eur"] * DOWN_BUFFER:
        level -= 1
    return level


def life_stage(level: int | None, config: dict) -> dict:
    """Where Lenny lives, how he moves, what he wears: what the viewer actually sees change."""
    if level is None:
        return {"name": "unknown"}
    return {**_stages(config)[level], "level": level}


def next_brief(state: dict, config: dict, fixtures: list[dict], tips: list[dict], now: datetime) -> dict:
    """The next episode. Every episode is about Lenny's life; the bet only runs alongside."""
    brief = _decide(state, config, fixtures, tips, now)
    if brief["type"] == "none":
        return brief
    before = state.get("life_level")
    if before is None:
        before = life_level(brief["bankroll_before_eur"], None, config)
    after = life_level(brief["bankroll_after_eur"], before, config)
    change = "same" if before == after or None in (before, after) else ("up" if after > before else "down")
    return {**brief, "life_stage_before": life_stage(before, config), "life_stage": life_stage(after, config),
            "life_change": change}


def _decide(state: dict, config: dict, fixtures: list[dict], tips: list[dict], now: datetime) -> dict:
    bankroll = round(state["bankroll_eur"], 2)
    base = {"episode": state["episode"] + 1, "created_at": now.isoformat(), "bankroll_before_eur": bankroll,
            "mood": mood(state), "streak": streak(state), "character": config.get("character", {})}
    min_stake = config.get("min_stake_eur", 5.0)
    featured = {norm(c) for c in config.get("featured_clubs", [])}
    bet = state.get("open_bet")

    cap = config.get("max_episodes_per_week")
    recent = [e for e in state["episodes"] if datetime.fromisoformat(e["created_at"]) > now - timedelta(days=7)]
    if cap and len(recent) >= cap:
        return {**base, "type": "none", "reason": f"{len(recent)} episodes in the last 7 days (cap {cap})"}

    # The two fixed opening episodes come before any bet.
    if state["episode"] == 0:
        return {**base, "type": "pilot", "bankroll_before_eur": 3.12, "bankroll_after_eur": 3.12,
                "note": "rock bottom: broken flat, 3.12 EUR in the account, no plan. No app, no betting yet."}
    if state["episode"] == 1:
        return {**base, "type": "discovery", "bankroll_after_eur": config.get("start_bankroll_eur", 50.0),
                "note": "a friend is right three times in a row with the GoalIQ app; Lenny sells his console "
                        "for a starting stake and decides to follow GoalIQ from the next matchday"}

    if bet:
        end = datetime.fromisoformat(bet["end"])
        if now < end + timedelta(hours=2):
            return {**base, "type": "none", "reason": f"{bet['label']} still running (last kickoff {bet['end']})"}
        entry = lennys_tip(bet, tips, featured)
        if entry:
            graded = settle(entry, bet["stake_eur"])
            if graded:
                return {**base, "type": "result", "matchday": bet, "match": _match(entry), **graded,
                        "stake_eur": bet["stake_eur"], "bankroll_after_eur": round(bankroll + graded["profit_eur"], 2),
                        "mood_after": _mood_after(state, graded["outcome"])}
        if now - end > timedelta(days=STALE_DAYS):
            return {**base, "type": "skip", "matchday": bet, "outcome": "no_tip", "profit_eur": 0.0,
                    "stake_eur": bet["stake_eur"], "bankroll_after_eur": bankroll, "mood_after": mood(state),
                    "note": "GoalIQ published no tip on this matchday: Lenny kept his money"}
        return {**base, "type": "none",
                "reason": "matchday over but not settled in data/logs yet (GitHub syncs the server logs at 08:15 and 20:15 UTC)"}

    if bankroll < min_stake:
        refill = config.get("comeback_refill_eur", 50.0)
        return {**base, "type": "broke", "bankroll_after_eur": round(bankroll + refill, 2), "refill_eur": refill,
                "note": "bankroll below the minimum stake: side hustle / comeback episode"}

    covered = {e["matchday"]["id"] for e in state["episodes"] if e.get("matchday")}
    md = pick_matchday(fixtures, config, now, covered)
    if md:
        stake = min(bankroll, round(max(min_stake, bankroll * config.get("stake_fraction", 0.5)), 2))
        stars = [g for g in md["games"] if norm(g["home_team"]) in featured or norm(g["away_team"]) in featured]
        return {**base, "type": "preview", "matchday": _matchday(md), "stake_eur": stake,
                "bankroll_after_eur": bankroll,
                "big_games": [_match(g) for g in (stars or md["games"])[:4]],
                "note": "Lenny goes in on GoalIQ's first published tip of this matchday. The tip appears in the "
                        "app shortly before kickoff: do not name or invent it."}

    if any(e["type"] == "lifestyle" for e in recent):
        return {**base, "type": "none", "reason": "no matchday ahead and already one life episode this week"}
    return {**base, "type": "lifestyle", "bankroll_after_eur": bankroll,
            "note": "no matchday ahead (e.g. international break): life episode that fits the mood"}


def _mood_after(state: dict, outcome: str) -> str:
    return mood({"results": state["results"] + [{"outcome": outcome}]})


def _matchday(md: dict) -> dict:
    return {"id": md["id"], "competition": COMPETITION_NAMES.get(md["competition"], md["competition"]),
            "label": f"{COMPETITION_NAMES.get(md['competition'], md['competition'])} {md['group']}",
            "start": md["start"].isoformat(), "end": md["end"].isoformat()}


def _match(g: dict) -> dict:
    kickoff = g.get("kickoff") or g.get("commence_time")
    if isinstance(kickoff, datetime):
        kickoff = kickoff.isoformat()
    return {"home_team": g["home_team"], "away_team": g["away_team"], "kickoff": kickoff}


def commit(state: dict, brief: dict) -> dict:
    if brief["type"] == "none":
        raise SystemExit("nothing to record: the brief says there is no episode to make")
    if brief["episode"] != state["episode"] + 1:
        raise SystemExit(f"brief is for episode {brief['episode']}, state expects {state['episode'] + 1}")
    state = json.loads(json.dumps(state))
    kind = brief["type"]
    if kind == "preview":
        state["open_bet"] = {**brief["matchday"], "stake_eur": brief["stake_eur"]}
    elif kind in ("result", "skip"):
        state["open_bet"] = None
        if kind == "result":
            state["results"].append({"matchday": brief["matchday"]["id"], "match": brief["match"],
                                     "outcome": brief["outcome"], "profit_eur": brief["profit_eur"]})
    state["bankroll_eur"] = brief["bankroll_after_eur"]
    state["episode"] = brief["episode"]
    if "life_stage" in brief:
        state["life_level"] = brief["life_stage"].get("level")
    keep = {k: brief[k] for k in ("episode", "type", "created_at", "bankroll_after_eur", "matchday", "match")
            if k in brief}
    state["episodes"].append(keep)
    return state


# ---------------------------------------------------------------- cli

def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)
    n = sub.add_parser("next")
    n.add_argument("--now", help="ISO time to plan from (default: now)")
    c = sub.add_parser("commit")
    c.add_argument("brief")
    sub.add_parser("status")
    args = p.parse_args(argv)

    config = load_config()
    state = load_state(config)
    if args.cmd == "status":
        print(json.dumps({k: state[k] for k in ("episode", "bankroll_eur", "open_bet")}, indent=2,
                         ensure_ascii=False))
    elif args.cmd == "next":
        now = datetime.fromisoformat(args.now) if args.now else datetime.now(timezone.utc)
        if now.tzinfo is None:
            now = now.replace(tzinfo=TZ)
        comps = config.get("competitions", ["bl", "cl"])
        brief = next_brief(state, config, load_fixtures(comps), load_tips(comps), now)
        print(json.dumps(brief, indent=2, ensure_ascii=False))
    elif args.cmd == "commit":
        brief = json.loads(Path(args.brief).read_text(encoding="utf-8"))
        STATE.write_text(json.dumps(commit(state, brief), indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        print(f"episode {brief['episode']} recorded, bankroll {brief['bankroll_after_eur']} EUR")


if __name__ == "__main__":
    main()
