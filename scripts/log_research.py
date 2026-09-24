"""Store structured pre-kickoff research, one append-only line per match.

Astra's condition for ever evaluating the AI research was that snapshots must
be written before kickoff, never reconstructed afterwards. Explaining a result
with today's knowledge proves nothing. So this refuses to write once a match
has started, and stamps every line with how many minutes were left.

    python3 scripts/log_research.py --fixtures frontend/src/nl_fixtures.json
    python3 scripts/log_research.py --dry-run     # prompt only, no API calls

The log is not yet used by anything. It cannot be: a feature has to be shown
to predict something before it may influence a bet, and that needs months of
these lines. Writing them is the prerequisite, not the result.
"""
import argparse
import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import pandas as pd

from src.research_schema import (
    derive_features, evidence_quality, is_usable, normalise, research_prompt,
    snapshot, verify_rest_days)

LOG = ROOT / "data" / "research_log.jsonl"
HISTORY = ROOT / "data" / "international_results.csv"
BERLIN = ZoneInfo("Europe/Berlin")


def kickoff_utc(fixture: dict) -> datetime:
    """Fixture times are local to the competition; we store UTC."""
    local = datetime.fromisoformat(f"{fixture['date']}T{fixture.get('time', '00:00')}")
    return local.replace(tzinfo=BERLIN).astimezone(timezone.utc)


def ask_gemini(prompt: str):
    """One search-grounded call. Returns (parsed, grounding sources).

    The redirect URIs Gemini returns expire quickly, so the publisher name
    that comes alongside them is the part worth keeping.
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
            if web is None:
                continue
            sources.append({
                "domain": getattr(web, "domain", None) or getattr(web, "title", None),
                "redirect": getattr(web, "uri", None),
            })
    return json.loads(text), sources


def already_logged(match_ids):
    """Snapshots accumulate; only skip a match logged in this same hour."""
    seen = set()
    if not LOG.exists():
        return seen
    for line in LOG.open(encoding="utf-8"):
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if row.get("match_id") in match_ids:
            seen.add((row["match_id"], row["logged_at"][:13]))
    return seen


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--fixtures", type=Path, default=ROOT / "frontend/src/nl_fixtures.json")
    ap.add_argument("--competition", default="UEFA Nations League")
    ap.add_argument("--dry-run", action="store_true", help="Print the prompt, call nothing")
    args = ap.parse_args()

    fixtures = json.loads(args.fixtures.read_text(encoding="utf-8"))
    history = pd.read_csv(HISTORY)
    now = datetime.now(timezone.utc)

    upcoming = [f for f in fixtures if kickoff_utc(f) > now]
    print(f"{len(fixtures)} Spiele, davon {len(upcoming)} noch vor Anpfiff "
          f"(jetzt {now.astimezone(BERLIN):%H:%M} Berlin)")
    for f in fixtures:
        if f not in upcoming:
            print(f"  uebersprungen (angepfiffen): {f['home_team']} - {f['away_team']}")

    seen = already_logged({f["match_id"] for f in upcoming})
    written = 0
    for f in upcoming:
        ko = kickoff_utc(f)
        prompt = research_prompt(f["home_team"], f["away_team"], args.competition,
                                 ko.isoformat(), now.isoformat())
        if args.dry_run:
            print(f"\n--- {f['match_id']} ---\n{prompt}")
            continue
        if (f["match_id"], now.isoformat()[:13]) in seen:
            print(f"  schon in dieser Stunde erfasst: {f['match_id']}")
            continue
        try:
            parsed, grounding = ask_gemini(prompt)
        except Exception as exc:
            print(f"  FEHLER {f['match_id']}: {type(exc).__name__}: {exc}")
            continue

        record = {
            "match_id": f["match_id"], "competition": args.competition,
            "home_team": f["home_team"], "away_team": f["away_team"],
            "kickoff": ko.isoformat(), **normalise(parsed, f["home_team"], f["away_team"]),
            "grounding": grounding[:20],
        }
        record["derived"] = derive_features(record)
        record["rest_days_check"] = verify_rest_days(record, history)
        record["evidence"] = evidence_quality(record, grounding)
        record["usable"] = is_usable(record)
        try:
            line = snapshot(record, now)
        except ValueError as exc:
            print(f"  {f['match_id']}: {exc}")
            continue

        with LOG.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(line, ensure_ascii=False) + "\n")
        written += 1

        d, ev = record["derived"], record["evidence"]
        flag = "OK     " if record["usable"] else "VERWORFEN"
        print(f"  {flag} {f['home_team']} - {f['away_team']}: "
              f"{d['home_out']}/{d['away_out']} Ausfaelle "
              f"({d['home_starters_out']}/{d['away_starters_out']} Stammspieler), "
              f"{ev['grounding_chunks']} Suchtreffer"
              f"{' von ' + ', '.join(ev['publishers'][:3]) if ev['publishers'] else ''}, "
              f"{line['minutes_before_kickoff']} Min vor Anpfiff")

    if not args.dry_run:
        print(f"\n{written} Zeilen angehaengt an {LOG.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
