"""Pull finished WC2026 results from ESPN into the training CSV, then retrain.

Run this before each matchday so the model's "recent form" features reflect
games that have actually been played, not just matchday 1.

    python3 scripts/update_training_data.py

What it does:
  1. Fetches all WC2026 fixtures from ESPN (same source the live site uses).
  2. For each completed match, fills in home_score/away_score in
     data/international_results.csv (rows already exist for the full
     schedule - dates/teams are pre-filled, only the score is missing).
  3. Retrains the model (scripts/train.py) so attack/defense ratings and the
     classifier pick up the new results.
  4. Regenerates all cached predictions (scripts/regenerate_cache.py) so the
     website's displayed cards match the freshly retrained model.
"""
import json
import subprocess
import sys
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import pandas as pd

CSV_PATH = Path(__file__).parent.parent / "data" / "international_results.csv"

# Same name normalization as api/app.py's ESPN integration, kept in sync.
_ESPN_NAME_MAP = {
    "Czechia": "Czech Republic",
    "Bosnia-Herzegovina": "Bosnia and Herzegovina",
    "Türkiye": "Turkey",
    "Curaçao": "Curacao",
    "Ivory Coast": "Ivory Coast",
    "Congo DR": "DR Congo",
    "USA": "United States",
}


def _espn_team(name: str) -> str:
    return _ESPN_NAME_MAP.get(name, name)


def fetch_espn_results() -> list[dict]:
    url = (
        "https://site.api.espn.com/apis/site/v2/sports/soccer/fifa.world/"
        "scoreboard?dates=20260611-20260719&limit=100"
    )
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=15) as resp:
        data = json.loads(resp.read())

    results = []
    for event in data.get("events", []):
        comp = event["competitions"][0]
        completed = comp["status"]["type"].get("completed", False)
        if not completed:
            continue
        competitors = comp["competitors"]
        home_c = next((c for c in competitors if c.get("homeAway") == "home"), competitors[0])
        away_c = next((c for c in competitors if c.get("homeAway") == "away"), competitors[1])
        venue = comp.get("venue", {}).get("address", {})
        results.append({
            "home_team": _espn_team(home_c["team"]["displayName"]),
            "away_team": _espn_team(away_c["team"]["displayName"]),
            "home_score": int(home_c.get("score", 0)),
            "away_score": int(away_c.get("score", 0)),
            "date": (comp.get("date") or event.get("date") or "")[:10],
            "city": venue.get("city", ""),
            "country": venue.get("country", ""),
        })
    return results


def update_csv(results: list[dict]) -> int:
    """Fill in scores for existing (pre-scheduled) rows, and APPEND a new row
    for results with no matching row at all. Knockout-round matchups (Round
    of 32 onward) aren't known until the group stage finishes, so there's no
    pre-existing template row for them the way there is for group-stage
    fixtures - without this append step, every knockout result was silently
    dropped and never made it into training data at all."""
    df = pd.read_csv(CSV_PATH)
    updated = 0
    new_rows = []
    for r in results:
        mask = (
            (df["home_team"] == r["home_team"])
            & (df["away_team"] == r["away_team"])
            & (df["home_score"].isna())
        )
        if mask.any():
            df.loc[mask, "home_score"] = r["home_score"]
            df.loc[mask, "away_score"] = r["away_score"]
            updated += mask.sum()
            continue
        already_has_result = (
            (df["home_team"] == r["home_team"])
            & (df["away_team"] == r["away_team"])
            & (df["date"] == r["date"])
            & df["home_score"].notna()
        ).any()
        if already_has_result:
            continue
        new_rows.append({
            "date": r["date"],
            "home_team": r["home_team"],
            "away_team": r["away_team"],
            "home_score": r["home_score"],
            "away_score": r["away_score"],
            "tournament": "FIFA World Cup",
            "city": r["city"],
            "country": r["country"],
            "neutral": True,
        })
    if new_rows:
        df = pd.concat([df, pd.DataFrame(new_rows)], ignore_index=True)
        updated += len(new_rows)
    if updated:
        df.to_csv(CSV_PATH, index=False)
    return updated


def main():
    print("Hole abgeschlossene WM2026-Ergebnisse von ESPN...")
    results = fetch_espn_results()
    print(f"  {len(results)} abgeschlossene Spiele gefunden.")

    updated = update_csv(results)
    print(f"  {updated} Zeile(n) in {CSV_PATH.name} aktualisiert.")

    if updated == 0:
        print("Keine neuen Ergebnisse - Modell muss nicht neu trainiert werden.")
        return

    print("\nTrainiere Modell neu...")
    subprocess.run([sys.executable, "scripts/train.py"], check=True, cwd=Path(__file__).parent.parent)

    print("\nRegeneriere alle gecachten Vorhersagen...")
    subprocess.run([sys.executable, "scripts/regenerate_cache.py"], check=True, cwd=Path(__file__).parent.parent)

    print("\nFertig - Modell und Cache sind jetzt auf dem aktuellen Ergebnisstand.")


if __name__ == "__main__":
    main()
