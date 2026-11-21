"""The AI's memory of its own tips: one CASE per finished, logged match.

After a match the AI's tip is reviewed: the facts come from ESPN (score, goals
with minute, stats), Gemini searches only for what ESPN does not have (how the
teams played, big chances, absentees, what was at stake) and checks each of
the AI's own pre-match arguments against it. No general lessons - those pile
up and contradict each other; a case only says what happened in THAT match.

The shadow agent (api/app.py, _run_shadow_agent) reads the cases of the two
teams it tips, each team separately, BEFORE it researches. Its tip is only
logged next to the real one (agent_eval_shadow), never shown, so the two can
be compared on the same matches.

    data/memory/<wettbewerb>.jsonl   one line per case, one file per
                                     competition like the tip logs

data/memory ships in the image (unlike data/logs, see .dockerignore): start.sh
copies files the Fly volume does not have yet, so the first deploy seeds the
server; from then on the server's own file wins and GitHub copies it back
(scripts/pull_server_logs.py).

The server adds the cases of yesterday's matches in its daily job
(src/jobs.run_daily); scripts/build_match_memory.py fills it for old matches.
"""
from __future__ import annotations

import json
import os
import re
import sys
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Optional

from src import log_store

ROOT = Path(__file__).resolve().parents[1]
MEMORY = ROOT / "data" / "memory"
MODEL = "gemini-3.8-flash"
ESPN = "https://site.api.espn.com/apis/site/v2/sports/soccer/{league}"
ESPN_LEAGUES = {
    "soccer_uefa_nations_league": "uefa.nations",
    "soccer_uefa_champs_league": "uefa.champions",
    "soccer_germany_bundesliga": "ger.1",
    "soccer_fifa_world_cup": "fifa.world",
}
COMPETITION_NAMES = {
    "soccer_uefa_nations_league": "UEFA Nations League",
    "soccer_uefa_champs_league": "UEFA Champions League",
    "soccer_germany_bundesliga": "Bundesliga",
    "soccer_fifa_world_cup": "FIFA World Cup",
}
STATS = (("possessionPct", "Ballbesitz %"), ("totalShots", "Schüsse"), ("shotsOnTarget", "aufs Tor"),
         ("wonCorners", "Ecken"), ("yellowCards", "Gelb"), ("redCards", "Rot"))
EVENTS = ("Goal", "Penalty", "Red Card", "Own Goal")
# Cases per team shown to the shadow agent, the newest ones.
CASES_PER_TEAM = 6
# Reviews per daily run: a few dozen matches a week, ~2 cents and ~2 searches each.
DAILY_LIMIT = 40


def load_cases(folder: Path | None = None) -> list[dict]:
    out = []
    for path in sorted((folder or MEMORY).glob("*.jsonl")):
        for line in path.read_text(encoding="utf-8").splitlines():
            try:
                out.append(json.loads(line))
            except ValueError:
                continue
    return out


def as_text(folder: Path | None = None) -> str:
    """Every case, one JSON per line, for the /logs/memory endpoint."""
    return "".join(p.read_text(encoding="utf-8") for p in sorted((folder or MEMORY).glob("*.jsonl")))


def append_cases(cases: list[dict], folder: Path | None = None) -> None:
    groups: dict[str, list[dict]] = {}
    for c in cases:
        groups.setdefault(log_store.slug(c), []).append(c)
    for name, group in groups.items():
        path = (folder or MEMORY) / f"{name}.jsonl"
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as f:
            for c in group:
                f.write(json.dumps(c, ensure_ascii=False) + "\n")


def case_id(entry: dict) -> str:
    return "-".join((log_store.slug(entry), str(entry.get("commence_time"))[:10],
                     log_store.norm(entry["home_team"]), log_store.norm(entry["away_team"])))


def _pick(entry: dict) -> Optional[dict]:
    a = entry.get("agent_eval") or {}
    return a.get("pick") or a.get("selected_pick")


def bet_label(pick: dict) -> str:
    side = pick.get("team") or pick.get("outcome")
    return f"{pick['market']} {side} @{pick.get('best_odds')}"


def arguments_of(agent_eval: dict) -> list[str]:
    """What the AI said before kickoff: its verdict and its research."""
    args = [agent_eval["bet_reasoning"]] if agent_eval.get("bet_reasoning") else []
    args += agent_eval.get("bet_points") or []
    for key, value in (agent_eval.get("research") or {}).items():
        if value:
            args.append(f"[{key}] {value}")
    return args


def _grade(pick: dict, entry: dict) -> Optional[str]:
    sys.path.insert(0, str(ROOT / "scripts"))
    from grade_bets import grade
    r = entry["result"]
    return grade(pick, entry["home_team"], entry["away_team"], r["home_score"], r["away_score"])


def _get_json(url: str) -> dict:
    with urllib.request.urlopen(url, timeout=30) as r:
        return json.loads(r.read())


def espn_facts(entry: dict, get: Callable[[str], dict] = _get_json) -> str:
    """Stats and key events of the match from ESPN, or '' if ESPN does not have it."""
    league = ESPN_LEAGUES.get(entry.get("sport_key"))
    if not league:
        return ""
    base = ESPN.format(league=league)
    day = str(entry["commence_time"])[:10].replace("-", "")
    home, away = log_store.norm(entry["home_team"]), log_store.norm(entry["away_team"])

    def same(x, y):
        return x == y or (min(len(x), len(y)) >= 4 and (x in y or y in x))

    try:
        events = get(f"{base}/scoreboard?dates={day}").get("events", [])
        for ev in events:
            sides = {c["homeAway"]: log_store.norm(c["team"]["displayName"])
                     for c in ev["competitions"][0]["competitors"]}
            if same(sides.get("home", ""), home) and same(sides.get("away", ""), away):
                break
        else:
            return ""
        summary = get(f"{base}/summary?event={ev['id']}")
    except Exception:
        return ""
    lines = []
    for t in summary.get("boxscore", {}).get("teams", []):
        st = {x["name"]: x["displayValue"] for x in t.get("statistics", [])}
        lines.append(f"{t['team']['displayName']}: " + ", ".join(f"{label} {st[k]}" for k, label in STATS if k in st))
    events = [f"{k.get('clock', {}).get('displayValue', '')} {k.get('text', '')}" for k in summary.get("keyEvents", [])
              if any(k.get("type", {}).get("text", "").startswith(e) for e in EVENTS)]
    return "Statistik (ESPN): " + " | ".join(lines) + "\nEreignisse (ESPN):\n" + "\n".join(events)


REVIEW_PROMPT = """You are reviewing one of YOUR OWN past football bets after the match. You are writing ONE
case for your memory: what happened in THIS match and why. Not general rules.

Match: {home} vs {away} ({competition}), kickoff {kickoff}. Final score {hs}:{as_}.
Your bet: {bet} -> {outcome}.
{alt}
Facts we already have (do NOT search for these and do not repeat them in your text):
{facts}

Your arguments before the match (numbered):
{args}

Use Google Search (match reports, local media, at most 3 searches) only for what the facts above do
not show: how each team set up and played (deep block, pressing, counters, rotation), the big chances
and who missed them, line-ups and absentees, what was at stake and how that showed on the pitch.

Then:
- For EACH numbered argument: came_true (yes / no / partly / irrelevant) and WHY in this match, with
  concrete evidence (players, moments, numbers) - not general statements.
- luck_or_reasoning: was the result of the bet mainly luck (chances, refereeing, freak goals) or
  mainly right/wrong reading of the match? Explain with this match's evidence.
- situation: describe the match - relative strength, home/away, stakes, how each team ACTUALLY
  played here.
- what_decided: 1-2 sentences on what decided the bet in this match.
Do NOT write general lessons or rules.

Reply ONLY with JSON, all text in German:
{{"situation": "...", "how_it_went": "the course of play and why, beyond the facts above, 2-3 sentences",
  "arguments": [{{"n": 1, "argument": "short", "came_true": "yes|no|partly|irrelevant", "why": "..."}}],
  "luck_or_reasoning": "luck|reasoning|mixed", "luck_explanation": "...", "what_decided": "..."}}"""

FORCE_SEARCH = "\n\nIMPORTANT: You MUST call Google Search before answering. Do not describe the match from memory."


def _client():
    from google import genai
    key = os.getenv("GEMINI_API_KEY", "")
    if not key:
        raise RuntimeError("GEMINI_API_KEY fehlt")
    return genai.Client(api_key=key)


def review(entry: dict, client=None, facts: Callable[[dict], str] = espn_facts) -> Optional[dict]:
    """One case for a finished, logged match, or None if the review failed.

    Without a Google search Gemini writes a match report from thin air, so an
    answer that did not search is asked again (twice) and then dropped."""
    from google.genai import types
    pick = _pick(entry)
    a = entry["agent_eval"]
    r = entry["result"]
    outcome = _grade(pick, entry)
    known = facts(entry)
    prompt = REVIEW_PROMPT.format(
        home=entry["home_team"], away=entry["away_team"], kickoff=entry["commence_time"],
        competition=COMPETITION_NAMES.get(entry.get("sport_key"), "football"),
        hs=r["home_score"], as_=r["away_score"], bet=bet_label(pick),
        outcome={"win": "WON", "loss": "LOST", "push": "PUSH"}.get(outcome, str(outcome)),
        alt=f"Alternative you considered: {a['alternative_reasoning']}\n" if a.get("alternative_reasoning") else "",
        facts=known or "(none - ESPN had no data; the final score above is certain)",
        args="\n".join(f"{i}. {t}" for i, t in enumerate(arguments_of(a), 1)))
    client = client or _client()
    from src import gemini_usage
    for attempt in range(3):
        response = client.models.generate_content(
            model=MODEL, contents=prompt + (FORCE_SEARCH if attempt else ""),
            config=types.GenerateContentConfig(tools=[types.Tool(google_search=types.GoogleSearch())]))
        gemini_usage.record("memory_review", response, grounded=True)
        cand = (getattr(response, "candidates", None) or [None])[0]
        grounding = getattr(cand, "grounding_metadata", None)
        queries = list(getattr(grounding, "web_search_queries", None) or [])
        if queries:
            break
    else:
        return None
    try:
        data = json.loads(re.search(r"\{.*\}", response.text or "", re.S).group(0))
    except (AttributeError, ValueError):
        return None
    sources = [getattr(getattr(c, "web", None), "title", None) for c in getattr(grounding, "grounding_chunks", None) or []]
    return {
        "id": case_id(entry), "sport_key": entry.get("sport_key"), "competition": entry.get("competition"),
        "commence_time": entry["commence_time"], "home_team": entry["home_team"], "away_team": entry["away_team"],
        "score": f"{r['home_score']}:{r['away_score']}", "tip": bet_label(pick), "tip_market": pick["market"],
        "outcome": outcome, "espn_facts": known, "arguments_before": arguments_of(a),
        "situation": data.get("situation", ""), "how_it_went": data.get("how_it_went", ""),
        "arguments": data.get("arguments") or [], "luck_or_reasoning": data.get("luck_or_reasoning", ""),
        "luck_explanation": data.get("luck_explanation", ""), "what_decided": data.get("what_decided", ""),
        "sources": [s for s in sources if s], "search_queries": queries,
        "candidates": graded_candidates(entry),
        "reviewed_at": datetime.now(timezone.utc).isoformat(),
    }


def graded_candidates(entry: dict) -> list[dict]:
    """The shadow agent's candidates (prompt v10) with whether each came in.

    No model call: the bets on offer and the final score settle them. A
    candidate that matches no priced bet is kept with result None."""
    shadow = entry.get("agent_eval_shadow") or {}
    bets = entry.get("bets") or []
    out = []
    for c in shadow.get("candidates_considered") or []:
        bet = next((b for b in bets if b.get("market") == c.get("market")
                    and (b.get("team") or b.get("outcome")) == c.get("outcome")), None)
        out.append({"market": c.get("market"), "outcome": c.get("outcome"), "probability": c.get("probability"),
                    "reason": c.get("reason", ""), "result": _grade(bet, entry) if bet else None,
                    "picked": bool(shadow.get("pick") and bet and bet.get("market") == shadow["pick"].get("market")
                                   and (bet.get("team") or bet.get("outcome"))
                                   == (shadow["pick"].get("team") or shadow["pick"].get("outcome")))})
    return out


def due(entries: list[dict], cases: list[dict]) -> list[dict]:
    """Logged matches with a final score and an AI pick that have no case yet."""
    have = {c["id"] for c in cases}
    return [e for e in entries if e.get("result") and _pick(e) and e.get("agent_eval")
            and case_id(e) not in have]


def update(entries: Optional[list[dict]] = None, limit: int = DAILY_LIMIT, folder: Path | None = None,
           review_one: Callable[[dict], Optional[dict]] = review, workers: int = 4) -> dict:
    """Review finished matches that have no case yet, newest first, and store the cases."""
    entries = log_store.load_tips() if entries is None else entries
    todo = sorted(due(entries, load_cases(folder)), key=lambda e: str(e.get("commence_time")), reverse=True)[:limit]
    failed = []

    def safe(e):
        try:
            return review_one(e)
        except Exception as exc:  # one failed review must not stop the rest
            failed.append(f"{e['home_team']}-{e['away_team']}: {type(exc).__name__}: {exc}")
            return None

    added = 0
    with ThreadPoolExecutor(max(1, workers)) as pool:
        # Each case is stored as soon as it is done, so a crash or a restart
        # mid-run keeps every review already paid for.
        for case in pool.map(safe, todo):
            if case:
                append_cases([case], folder)
                added += 1
    return {"due": len(todo), "added": added, "failed": len(todo) - added, "errors": failed[:5]}


def team_cases(team: str, before: str, cases: list[dict], limit: int = CASES_PER_TEAM) -> list[dict]:
    """The newest cases of one team from matches that kicked off before `before`."""
    key = log_store.norm(team)
    own = [c for c in cases if key in (log_store.norm(c["home_team"]), log_store.norm(c["away_team"]))
           and str(c["commence_time"]) < str(before)]
    return sorted(own, key=lambda c: str(c["commence_time"]))[-limit:]


def _brief(c: dict) -> dict:
    return {"case": c["id"],
            "match": f"{c['home_team']} - {c['away_team']} {c['score']} ({str(c['commence_time'])[:10]}, "
                     f"{COMPETITION_NAMES.get(c.get('sport_key'), c.get('competition') or 'football')})",
            "your_tip": f"{c['tip']} -> {c['outcome']}",
            "how_it_went": c.get("how_it_went", ""),
            "your_arguments_checked": [f"{x.get('argument')} -> {x.get('came_true')}: {x.get('why')}"
                                       for x in c.get("arguments", [])],
            "luck_or_reasoning": f"{c.get('luck_or_reasoning')}: {c.get('luck_explanation')}",
            "what_decided": c.get("what_decided", ""),
            # From the shadow assessment of that match; its pick can differ from
            # the tip above, so no bet is marked as "the pick" here.
            **({"bets_you_also_rated": [
                f"{x['market']} {x['outcome']} (your estimate {x['probability']}%) -> {x['result']}"
                for x in c["candidates"] if x.get("result")]} if c.get("candidates") else {})}


MEMORY_BLOCK = """

YOUR MEMORY - your own earlier tips in matches of THESE two teams, each checked after the match: how it
went, which of your arguments came true and why, luck or reading, what decided the bet. Where a case
lists "bets_you_also_rated", those are other bets of that match with the probability you gave them and
whether they came in. Read the cases before you research (STEP 1): where you misread a team before,
check that point now (e.g. whether the player who made the difference is available, whether the team
plays the same way). One match is not a rule.
If a past case actually influenced your verdict, mention it briefly and concretely in bet_reasoning
(opponent, score, what happened) and list it in memory_used; if none did, do not mention the memory.

{home} (oldest first):
{home_cases}

{away} (oldest first):
{away_cases}"""


def prompt_block(home: str, away: str, before: str, cases: Optional[list[dict]] = None) -> tuple[str, list[str]]:
    """The memory section for the shadow agent and the case ids in it; ('', []) if neither team has a case."""
    cases = load_cases() if cases is None else cases
    hc, ac = team_cases(home, before, cases), team_cases(away, before, cases)
    if not hc and not ac:
        return "", []
    dump = lambda xs: json.dumps([_brief(c) for c in xs], ensure_ascii=False, indent=1) if xs else "(no earlier tips)"
    ids = list(dict.fromkeys(c["id"] for c in hc + ac))
    return MEMORY_BLOCK.format(home=home, away=away, home_cases=dump(hc), away_cases=dump(ac)), ids
