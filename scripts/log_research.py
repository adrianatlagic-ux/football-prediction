"""Snapshot a fixture 59 minutes before kickoff: squads first, then research.

Astra's condition for ever judging the AI research was that snapshots be
written before kickoff and never reconstructed afterwards - explaining a
result with today's knowledge proves nothing. So this refuses to write once
a match has started and stamps every line with the minutes that were left.

Why 59 minutes: official line-ups are published around the hour mark, so it
is the earliest moment at which lineup_confirmed can be true rather than a
guess, and late enough that withdrawals have surfaced.

    python3 scripts/log_research.py                 # act only inside the window
    python3 scripts/log_research.py --dry-run       # show the plan, call nothing
    python3 scripts/log_research.py --force         # ignore the window (testing)

Squads are read from Transfermarkt directly - one request per team, no paid
scraper - and cross-checked against the independently published squad total,
so a parser that stops matching raises instead of logging zeroes. The
research call adds only what no table holds: withdrawals between the call-up
and kickoff, whether the eleven is official, and whether the tie still
matters. Every player name it returns is resolved against the squad we
fetched, and one that does not appear there marks the record unusable.

Nothing written here feeds a prediction. A field has to be shown to predict
something before it may move a bet, and that needs months of these lines.
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.research_schema import (
    derive_features, evidence_quality, is_usable, normalise, research_prompt, snapshot)
from src.competitions import get as get_competition
from src.squad_data import fetch_squads, summarise

LOG = ROOT / "data" / "research_log.jsonl"
REGISTRY = ROOT / "data" / "team_registry.csv"
BERLIN = ZoneInfo("Europe/Berlin")

TARGET_MINUTES = 59
# Manual runs are not punctual. Act from the target until shortly before
# kickoff, but never twice for the same fixture.
WINDOW_FLOOR = 15


def kickoff_utc(fixture: dict) -> datetime:
    local = datetime.fromisoformat(f"{fixture['date']}T{fixture.get('time', '00:00')}")
    return local.replace(tzinfo=BERLIN).astimezone(timezone.utc)


def team_ids(competition_key: str) -> dict:
    with REGISTRY.open(encoding="utf-8") as fh:
        return {r["team"]: r["transfermarkt_id"] for r in csv.DictReader(fh)
                if r["competition"] == competition_key}


def logged_fixtures(log: Path) -> set:
    if not log.exists():
        return set()
    done = set()
    for line in log.open(encoding="utf-8"):
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if row.get("schema_version") == "research_v2":
            done.add(row.get("match_id"))
    return done


def ask_gemini(prompt: str):
    """One search-grounded call. Returns (parsed, grounding sources).

    The redirect URIs Gemini hands back expire within hours - several were
    already dead when first checked - so the publisher name beside them is
    the part worth storing, and the count is what tells us a search happened.
    """
    from google import genai
    from google.genai import types

    client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])
    response = client.models.generate_content(
        model="gemini-2.5-flash", contents=prompt,
        config=types.GenerateContentConfig(
            tools=[types.Tool(google_search=types.GoogleSearch())]),
    )
    text = re.sub(r"^```(?:json)?|```$", "", (response.text or "").strip(),
                  flags=re.MULTILINE).strip()
    sources = []
    for candidate in getattr(response, "candidates", []) or []:
        grounding = getattr(candidate, "grounding_metadata", None)
        for chunk in getattr(grounding, "grounding_chunks", []) or []:
            web = getattr(chunk, "web", None)
            if web is not None:
                sources.append({"domain": getattr(web, "domain", None) or getattr(web, "title", None),
                                "redirect": getattr(web, "uri", None)})
    return json.loads(text), sources


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--fixtures", type=Path, default=ROOT / "frontend/src/nl_fixtures.json")
    ap.add_argument("--competition", default="nations_league",
                    help="key from src/competitions.py")
    ap.add_argument("--dry-run", action="store_true", help="Show the plan, call nothing")
    ap.add_argument("--force", action="store_true", help="Ignore the timing window")
    ap.add_argument("--log", type=Path, default=LOG,
                    help="Where to append (point elsewhere for a rehearsal)")
    args = ap.parse_args()

    competition = get_competition(args.competition)
    fixtures = json.loads(args.fixtures.read_text(encoding="utf-8"))
    now = datetime.now(timezone.utc)
    done = logged_fixtures(args.log)

    due, pending = [], []
    for fixture in fixtures:
        left = (kickoff_utc(fixture) - now).total_seconds() / 60
        if fixture["match_id"] in done:
            continue
        if left <= 0:
            continue
        if args.force or WINDOW_FLOOR <= left <= TARGET_MINUTES:
            due.append(fixture)
        else:
            pending.append((fixture, left))

    print(f"Jetzt {now.astimezone(BERLIN):%H:%M} Berlin | {len(done)} bereits erfasst")
    for fixture, left in sorted(pending, key=lambda t: t[1]):
        opens = (kickoff_utc(fixture) - timedelta(minutes=TARGET_MINUTES)).astimezone(BERLIN)
        print(f"  wartet bis {opens:%H:%M}  {fixture['home_team']} - {fixture['away_team']}")
    if not due:
        print("\nNichts faellig. Skript zum Fenster erneut starten.")
        return

    print(f"\n{len(due)} Spiel(e) faellig:")
    for fixture in due:
        print(f"  {fixture['home_team']} - {fixture['away_team']}")
    if args.dry_run:
        print("\n--dry-run: nichts aufgerufen.")
        return

    ids = team_ids(competition.key)
    teams = sorted({t for f in due for t in (f["home_team"], f["away_team"])})
    wanted = {t: ids[t] for t in teams if t in ids}
    missing = [t for t in teams if t not in ids]
    if missing:
        print(f"  ohne Transfermarkt-Id, uebersprungen: {', '.join(missing)}")

    print(f"\nHole Kader fuer {len(wanted)} Mannschaften...", flush=True)
    try:
        raw = fetch_squads(wanted.values(), with_injuries=competition.has_injury_page)
    except RuntimeError as exc:
        # The cross-check failed: better no snapshot than a wrong one.
        raise SystemExit(f"ABBRUCH: {exc}")
    squads = {team: raw[str(tm_id)] for team, tm_id in wanted.items()}
    for team, players in squads.items():
        total = sum(int(p.get("marketValueEur") or 0) for p in players)
        note = ("  (Pool, kein Spieltagskader)"
                if competition.squad_is_callup and len(players) > 32 else "")
        print(f"  {team:24} {len(players):3} Spieler, {total/1e6:7.1f} Mio{note}")

    squad_log = args.log.with_name(args.log.stem + "_squads.jsonl")
    with squad_log.open("a", encoding="utf-8") as fh:
        for team, players in squads.items():
            fh.write(json.dumps({"fetched_at": now.isoformat(), "team": team,
                                 "players": players}, ensure_ascii=False) + "\n")

    written = 0
    for fixture in due:
        ko = kickoff_utc(fixture)
        home, away = fixture["home_team"], fixture["away_team"]
        names = {t: [p["name"] for p in squads.get(t, [])] for t in (home, away)}

        prompt = research_prompt(home, away, competition.label, ko.isoformat(),
                                 now.isoformat(), squads=names)
        try:
            parsed, grounding = ask_gemini(prompt)
        except Exception as exc:
            print(f"  FEHLER {fixture['match_id']}: {type(exc).__name__}: {exc}")
            parsed, grounding = {}, []

        record = {
            "match_id": fixture["match_id"], "competition": competition.key,
            "home_team": home, "away_team": away, "kickoff": ko.isoformat(),
            **normalise(parsed, home, away), "grounding": grounding[:20],
        }
        # The agent names withdrawals; the squad supplies what they are worth.
        record["squads"] = {
            side: summarise(squads.get(team, []), competition,
                            [a["player"] for a in record["absences"] if a["team"] == team],
                            ko.date())
            for side, team in (("home", home), ("away", away))
        }
        record["derived"] = derive_features(record)
        record["evidence"] = evidence_quality(record, grounding)
        unknown = sorted({n for side in record["squads"].values()
                          for n in side["names_not_in_squad"]})
        record["evidence"]["names_not_in_squad"] = unknown
        record["usable"] = is_usable(record) and not unknown

        try:
            line = snapshot(record, now)
        except ValueError as exc:
            print(f"  {fixture['match_id']}: {exc}")
            continue
        with args.log.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(line, ensure_ascii=False) + "\n")
        written += 1

        h, a = record["squads"]["home"], record["squads"]["away"]
        flag = "OK       " if record["usable"] else "VERWORFEN"
        print(f"\n  {flag} {home} - {away}  ({line['minutes_before_kickoff']} Min vorher)")
        print(f"    Kaderwert fehlt: {h['absent_value_share']:.1%} / {a['absent_value_share']:.1%}")
        print(f"    Aufstellung offiziell: {record['lineup_confirmed']['home']} / "
              f"{record['lineup_confirmed']['away']}  |  "
              f"{record['evidence']['grounding_chunks']} Suchtreffer")
        for side in (h, a):
            for player in side["absent_players"]:
                print(f"      fehlt: {player['name']} ({player['value_eur']/1e6:.0f} Mio)")
        if unknown:
            print(f"    NICHT IM KADER (erfunden?): {', '.join(unknown)}")

    print(f"\n{written} Zeilen angehaengt an {args.log}")


if __name__ == "__main__":
    main()
