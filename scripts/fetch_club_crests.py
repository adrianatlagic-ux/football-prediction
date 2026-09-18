"""Refresh frontend/src/club_crests.json from ESPN's team-logo CDN.

ESPN serves a stable, public logo URL per team
(https://a.espncdn.com/i/teamlogos/soccer/500/{id}.png) alongside each
league's team list - no API key, no scraping fragility. Covers Champions
League + the biggest European domestic leagues.

    python3 scripts/fetch_club_crests.py

Coverage is intentionally partial (~70%): smaller leagues (Kazakhstan,
Belarus, Russia, Ukraine, Israel, Serbia, Moldova, Cyprus, Romania,
Slovenia...) aren't fetched, so those clubs simply show no crest in the UI -
the frontend already falls back to plain text for any team missing here.
"""
import json
import re
import sys
import time
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).parent.parent))

DATA_PATH = Path(__file__).parent.parent / "data" / "club_football_results.csv"
OUT_PATH = Path(__file__).parent.parent / "frontend" / "src" / "club_crests.json"

# ESPN league slugs covering Champions League + the biggest domestic leagues.
LEAGUE_SLUGS = [
    "eng.1", "eng.2", "esp.1", "ger.1", "ita.1", "fra.1", "por.1", "ned.1",
    "tur.1", "bel.1", "sui.1", "sco.1", "uefa.champions",
]

_STRIP_TOKENS = ["FC", "CF", "AFC", "KV", "SK", "AC", "BC", "SFP", "SCO", "AJ",
                 "CD", "FK", "JK", "RC", "SS", "US", "de", "du", "of"]
_ACCENTS = str.maketrans("éüöğçş", "euogcs")
_MIN_MATCH_LEN = 6  # see scripts/fetch_club_market_values.py for why this guards against false positives

# Manual overrides where the shared "core" name is too short/different for
# the automatic matcher (e.g. "Inter Milan" vs ESPN's "Internazionale").
MANUAL_ALIASES = {
    "Inter Milan": "Internazionale",
    "Ajax": "Ajax Amsterdam",
    "Sporting Lisbon": "Sporting CP",
}


def _normalize(name: str) -> str:
    n = name.replace("-", " ")
    n = re.sub(r"\b(19|18)\d{2}\b", "", n)
    for tok in _STRIP_TOKENS:
        n = re.sub(rf"\b{re.escape(tok)}\b", "", n)
    n = re.sub(r"^(1\.|AS |AZ )", "", n)
    n = n.translate(_ACCENTS)
    n = re.sub(r"[^a-zA-Z0-9 ]", "", n)
    return re.sub(r"\s+", " ", n).strip().lower()


def _fetch_espn_teams() -> dict[str, dict]:
    teams: dict[str, dict] = {}
    for slug in LEAGUE_SLUGS:
        resp = requests.get(
            f"https://site.api.espn.com/apis/site/v2/sports/soccer/{slug}/teams",
            params={"limit": 100},
            headers={"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)"},
            timeout=15,
        )
        resp.raise_for_status()
        league_teams = resp.json().get("sports", [{}])[0].get("leagues", [{}])[0].get("teams", [])
        for t in league_teams:
            team = t["team"]
            name = team.get("displayName")
            logos = team.get("logos") or []
            if name and logos:
                teams[name] = {"logo": logos[0]["href"], "color": f"#{team['color']}" if team.get("color") else None}
        print(f"  {slug}: {len(league_teams)} Teams (gesamt: {len(teams)})")
        time.sleep(1)
    return teams


def main():
    print("Hole Vereinswappen von ESPN...")
    espn_teams = _fetch_espn_teams()
    espn_items = [(_normalize(name), name, data) for name, data in espn_teams.items()]
    espn_by_orig = {orig: data for _, orig, data in espn_items}

    import pandas as pd
    our_teams = sorted({
        t for col in ("home_team", "away_team") for t in pd.read_csv(DATA_PATH)[col]
    })

    result: dict[str, dict] = {}
    missing = []
    for t in our_teams:
        if t in MANUAL_ALIASES and MANUAL_ALIASES[t] in espn_by_orig:
            result[t] = espn_by_orig[MANUAL_ALIASES[t]]
            continue
        nt = _normalize(t)
        hit = None
        for norm_e, orig_e, data in espn_items:
            if nt == norm_e:
                hit = data
                break
        if not hit:
            candidates = []
            for norm_e, orig_e, data in espn_items:
                shorter = min(len(nt), len(norm_e))
                if shorter >= _MIN_MATCH_LEN and (nt in norm_e or norm_e in nt):
                    candidates.append(data)
            if len(candidates) == 1:
                hit = candidates[0]
        if hit:
            result[t] = hit
        else:
            missing.append(t)

    print(f"\n{len(result)}/{len(our_teams)} Teams gematcht, {len(missing)} ohne Wappen (Text-Fallback).")
    OUT_PATH.write_text(json.dumps(result, indent=2, ensure_ascii=False, sort_keys=True), encoding="utf-8")
    print(f"Geschrieben: {OUT_PATH}")


if __name__ == "__main__":
    main()
