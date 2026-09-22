"""Pull the full FIFA World Ranking into data/fifa_rankings.csv.

The hardcoded table in src/fifa_rankings.py holds 62 nations - essentially
the WC2026 field - and its points are only trustworthy at the very top. On
2025-09-18 data, our values deviate from FIFA's by 32 points on average
inside the top 20, by 183 for ranks 21-50 and by 548 beyond rank 50, where
they look derived from the rank rather than measured. Everyone absent got
the same 900-point placeholder, which made Andorra and Malta look equally
strong while their actual records differ threefold.

This fetches all 211 ranked nations with their real points.

    python3 scripts/fetch_fifa_rankings.py            # dry run
    python3 scripts/fetch_fifa_rankings.py --write

The endpoint keys each edition by an opaque id rather than a date, and only
the ids advertised on FIFA's own ranking page resolve. The script reads that
page, tries the ids newest-first and takes the first that answers, so it
picks up newer editions as FIFA publishes them without needing a guess here.
"""
import argparse
import json
import re
import sys
import urllib.request
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

ROOT = Path(__file__).resolve().parents[1]
OUT_PATH = ROOT / "data" / "fifa_rankings.csv"
RANKING_PAGE = "https://inside.fifa.com/fifa-rankings/world-ranking/men"
RANKING_API = "https://inside.fifa.com/api/ranking-overview?locale=en&dateId=id{}"

# FIFA's spellings -> the names used in data/international_results.csv.
# A team we fail to map keeps the placeholder, so the script reports any
# unmapped name that actually appears in our results rather than staying
# quiet about it.
NAME_MAP = {
    "USA": "United States",
    "Türkiye": "Turkey",
    "Czechia": "Czech Republic",
    "Côte d'Ivoire": "Ivory Coast",
    "IR Iran": "Iran",
    "Korea Republic": "South Korea",
    "Korea DPR": "North Korea",
    "Congo DR": "DR Congo",
    "Cabo Verde": "Cape Verde",
    "China PR": "China",
    "The Gambia": "Gambia",
    "Kyrgyz Republic": "Kyrgyzstan",
    "Chinese Taipei": "Taiwan",
    "Hong Kong, China": "Hong Kong",
    "Brunei Darussalam": "Brunei",
    "St Kitts and Nevis": "St. Kitts and Nevis",
    "St Lucia": "St. Lucia",
    "St Vincent and the Grenadines": "St. Vincent and the Grenadines",
    "Curaçao": "Curacao",
}


def fetch(url: str) -> bytes:
    # No User-Agent: FIFA, like ESPN, is friendlier to the default one.
    # The ranking page answers 308 to the bare path, so follow redirects.
    opener = urllib.request.build_opener(urllib.request.HTTPRedirectHandler)
    with opener.open(url, timeout=25) as response:
        return response.read()


def available_ids() -> list[int]:
    html = fetch(RANKING_PAGE).decode("utf-8", errors="ignore")
    return sorted({int(x) for x in re.findall(r"id(\d{5})", html)}, reverse=True)


def latest_ranking() -> tuple[list[dict], str]:
    for date_id in available_ids():
        payload = json.loads(fetch(RANKING_API.format(date_id)))
        rankings = payload.get("rankings") or []
        if rankings:
            return rankings, rankings[0]["lastUpdateDate"][:10]
    raise SystemExit("No ranking edition returned data; the endpoint may have changed.")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--write", action="store_true")
    args = parser.parse_args()

    rankings, as_of = latest_ranking()
    rows, unranked = [], []
    for entry in rankings:
        item = entry["rankingItem"]
        # FIFA lists a few nations with points but no rank (provisional
        # membership). Without a rank they cannot feed the ranking features,
        # so they are skipped and named rather than written as rank 0.
        if item.get("rank") is None or item.get("totalPoints") is None:
            unranked.append(item.get("name"))
            continue
        rows.append({
            "team": NAME_MAP.get(item["name"], item["name"]),
            "fifa_name": item["name"],
            "rank": int(item["rank"]),
            "points": float(item["totalPoints"]),
            "as_of": as_of,
        })
    frame = pd.DataFrame(rows).sort_values("rank")

    print(f"{len(frame)} nations, ranking of {as_of}")
    if unranked:
        print(f"skipped, no rank published: {', '.join(unranked)}")
    print(frame.head(3)[["rank", "team", "points"]].to_string(index=False))
    print("  ...")
    print(frame.tail(2)[["rank", "team", "points"]].to_string(index=False))

    results = pd.read_csv(ROOT / "data" / "international_results.csv")
    played = set(results.home_team) | set(results.away_team)
    unmapped = sorted(set(frame.team) & set(frame.fifa_name) - played)
    if unmapped:
        print(f"\nWARNING: FIFA names absent from our results, add to NAME_MAP if they are ours:")
        print("  " + ", ".join(unmapped[:20]))
    uncovered = sorted(t for t in played if t not in set(frame.team))
    print(f"\nteams in our results without a ranking: {len(uncovered)}")
    if uncovered:
        print("  " + ", ".join(uncovered[:15]) + (" ..." if len(uncovered) > 15 else ""))

    if not args.write:
        print("\nDry run. Re-run with --write.")
        return
    frame.to_csv(OUT_PATH, index=False)
    print(f"\nWrote {OUT_PATH}")


if __name__ == "__main__":
    main()
