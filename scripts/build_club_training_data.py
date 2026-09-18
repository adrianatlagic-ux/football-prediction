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

    # Bundesliga + 2. Bundesliga (data/club_raw/bundesliga*_*.csv, from
    # OpenLigaDB - see scripts/fetch_bundesliga_data.py). Canonical forms
    # cross-checked against a live The Odds API events call for
    # soccer_germany_bundesliga / soccer_germany_bundesliga2 (2026/27
    # season), same rule as the rest of this table: canonical = whatever
    # the Odds API calls the club, not the scraper's own convention.
    #
    # Two currently-live clubs are a known exception: The Odds API's actual
    # strings are "FC Schalke 04" and "Borussia Monchengladbach" (no
    # umlaut), which conflict with this project's already-established
    # canonical forms above ("Schalke 04", "Borussia Mönchengladbach" with
    # umlaut - both already used by existing CL-derived data). Kept as-is
    # for internal consistency; matching live Bundesliga odds responses
    # against these canonical names will need its own normalize+match layer
    # (same pattern as api/app.py's _ESPN_NAME_MAP or the crest/market-value
    # fuzzy matching), not a literal string comparison.
    "Bayer 04 Leverkusen": "Bayer Leverkusen",
    "DSC Arminia Bielefeld": "Arminia Bielefeld",
    "Energie Cottbus": "FC Energie Cottbus",
    "FC Augsburg": "Augsburg",
    "Hertha BSC": "Hertha Berlin",
    "SC Paderborn 07": "SC Paderborn",
    "SV 07 Elversberg": "Elversberg",
    "SV Werder Bremen": "Werder Bremen",
    "SpVgg Greuther Fürth": "Greuther Fürth",
    "TSG 1899 Hoffenheim": "TSG Hoffenheim",
    "1. FC Heidenheim 1846": "1. FC Heidenheim",
    # Not currently in the top two tiers (no Odds API ground truth) - just
    # collapsing the one duplicate spelling OpenLigaDB itself uses across
    # different seasons so it isn't split into two "teams".
    "Erzgebirge Aue": "FC Erzgebirge Aue",

    # Pre-existing duplicates found while auditing the merged team list for
    # this change (same "same club, two spellings" bug as PSG/Barcelona/etc.
    # above) - the CL scraper was inconsistent season-to-season about
    # including "FC"/"FC" suffixes. Not related to the Bundesliga add, but
    # caught in passing and worth fixing since it was splitting real match
    # history for four clubs (10-20 matches each stranded under the "FC"
    # variant).
    "Juventus FC": "Juventus",
    "Manchester City FC": "Manchester City",
    "Manchester United FC": "Manchester United",
    "Newcastle United FC": "Newcastle United",
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
