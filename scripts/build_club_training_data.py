"""Merge and normalize the raw Champions League + Premier League CSVs in
data/club_raw/ into one training file: data/club_football_results.csv

The two sources name clubs differently (CL scrape: "Arsenal FC", "Tottenham
Hotspur", "FC Basel 1893" / PL PulseLive API: "Arsenal", "Tottenham",
"Fulham") - without normalizing these to one canonical name, the same club
would get split into two separate "teams" in training, each with half the
match history. TEAM_ALIASES below maps every variant seen in the pulled data
to one canonical form; new source data will need new entries added here.

    python3 scripts/build_club_training_data.py
"""
import csv
from pathlib import Path

RAW_DIR = Path(__file__).parent.parent / "data" / "club_raw"
OUT_PATH = Path(__file__).parent.parent / "data" / "club_football_results.csv"

TEAM_ALIASES = {
    # Canonical form = whatever The Odds API calls the club (that's the name
    # every live prediction request looks up by), not the scraper's own
    # convention. "Paris Saint-Germain FC" was the scraper's own inconsistency
    # (some seasons dropped the "FC") - without this it silently split PSG's
    # history into two separate "teams", each with half its matches.
    "Paris Saint-Germain FC": "Paris Saint Germain",
    "FC Barcelona": "Barcelona",
    "Feyenoord Rotterdam": "Feyenoord",
    "FC Bayern München": "Bayern Munich",
    "PSV": "PSV Eindhoven",
    "FC Red Bull Salzburg": "RB Salzburg",
    "Arsenal FC": "Arsenal",
    "Tottenham Hotspur": "Tottenham",
    "Chelsea FC": "Chelsea",
    "Everton FC": "Everton",
    "Liverpool FC": "Liverpool",
    "Fulham FC": "Fulham",
    "Celtic FC": "Celtic",
    "FC Basel 1893": "Basel",
    "FC Basel": "Basel",
    "PFC Ludogorets Razgrad": "Ludogorets Razgrad",
    "SSC Napoli": "Napoli",
    "AC Milan": "Milan",
    "Bor. Mönchengladbach": "Borussia Mönchengladbach",
    "Club Brugge KV": "Club Brugge",
    "Sevilla FC": "Sevilla",
    "Valencia CF": "Valencia",
    "Villarreal CF": "Villarreal",
    "Málaga CF": "Malaga",
    "Real Sociedad": "Real Sociedad",
    "Athletic Club": "Athletic Bilbao",
    "Beşiktaş": "Besiktas",
    "AFC Ajax": "Ajax",
    "RSC Anderlecht": "Anderlecht",
    "KAA Gent": "Gent",
    "KRC Genk": "Genk",
    "NK Maribor": "Maribor",
    "Dinamo Zagreb": "Dinamo Zagreb",
    "Dinamo Kiev": "Dynamo Kyiv",
    "Shakhtar Donetsk": "Shakhtar Donetsk",
    "CSKA Moskva": "CSKA Moscow",
    "Zenit St. Petersburg": "Zenit",
    "Spartak Moskva": "Spartak Moscow",
    "FK Rostov": "Rostov",
    "BATE Borisov": "BATE Borisov",
    "Viktoria Plzeň": "Viktoria Plzen",
    "Oţelul Galaţi": "Otelul Galati",
    "FC Steaua Bucureşti": "Steaua Bucuresti",
    "CFR Cluj": "CFR Cluj",
    "FC Nordsjælland": "Nordsjaelland",
    "FC København": "Copenhagen",
    "Malmö FF": "Malmo FF",
    "Legia Warszawa": "Legia Warsaw",
    "APOEL Nikosia": "APOEL",
    "Maccabi Tel Aviv": "Maccabi Tel Aviv",
    "FK Astana": "Astana",
    "Galatasaray": "Galatasaray",
    "Olympiakos Piraeus": "Olympiacos",
    "Olympique Lyonnais": "Lyon",
    "Olympique Marseille": "Marseille",
    "Paris Saint-Germain": "Paris Saint Germain",
    "AS Monaco": "Monaco",
    "Inter": "Inter Milan",
    "Trabzonspor": "Trabzonspor",
    "Lille OSC": "Lille",
    "SL Benfica": "Benfica",
    "Sporting CP": "Sporting Lisbon",
    "Sporting Clube de Portugal": "Sporting Lisbon",
    "Sporting Braga": "Braga",
    "Sporting Clube de Braga": "Braga",
    "SK Slavia Praha": "Slavia Praha",
    "Racing Club de Lens": "RC Lens",
    "FC Porto": "Porto",
    "Bor. Dortmund": "Borussia Dortmund",
    "Bayern München": "Bayern Munich",
    "Bayer Leverkusen": "Bayer Leverkusen",
    "FC Schalke 04": "Schalke 04",
    "VfL Wolfsburg": "Wolfsburg",
    "1. FC Union Berlin": "Union Berlin",
}


def _canon(name: str) -> str:
    return TEAM_ALIASES.get(name, name)


def main():
    rows = []
    files = sorted(RAW_DIR.glob("*.csv"))
    for path in files:
        with path.open(encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for r in reader:
                rows.append({
                    "date": r["date"],
                    "home_team": _canon(r["home_team"]),
                    "away_team": _canon(r["away_team"]),
                    "home_score": r["home_score"],
                    "away_score": r["away_score"],
                })
    rows.sort(key=lambda r: r["date"])

    with OUT_PATH.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["date", "home_team", "away_team", "home_score", "away_score"])
        writer.writeheader()
        writer.writerows(rows)

    teams = sorted({r["home_team"] for r in rows} | {r["away_team"] for r in rows})
    print(f"{len(rows)} matches from {len(files)} files -> {OUT_PATH}")
    print(f"{len(teams)} distinct teams")


if __name__ == "__main__":
    main()
