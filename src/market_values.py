"""Squad market values (EUR) from Transfermarkt.

Two sources, deliberately kept apart. The hand-written table below covers the
48 World Cup 2026 participants as of June 2026. data/national_market_values.csv
adds all 54 UEFA nations, scraped from the Nations League participant pages
(scripts/fetch_national_market_values.py).

The CSV wins where both have a team, because it is refetchable and dated. The
two are different measurements - World Cup 26-man squads versus the squads
Transfermarkt lists for the Nations League - but across the 16 nations in both
the median ratio is 1.04, so neither is systematically higher. The spread runs
0.73 to 1.72, which is too wide for a single conversion factor to fix, so no
rescaling is attempted; per-team variation would only be traded for a
different per-team error.

Why this file changed: for a Nations League round, eleven of sixteen teams had
no entry at all, and a miss returned 0. Zero is not "unknown" - it is a value
meaning worthless, and the ratio then asserted 2.0 or 0.5. The model was told
Denmark is worth nothing and Norway twice as strong. Unknown teams now get a
neutral ratio and raise a flag the model can learn from, the same way
fifa_ranking_missing already works for rankings.
"""
import csv
from pathlib import Path

MARKET_VALUES: dict[str, int] = {
    # Top Tier
    "France":           1_520_000_000,
    "England":          1_360_000_000,
    "Spain":            1_220_000_000,
    "Portugal":         1_010_000_000,
    "Germany":            979_000_000,
    "Brazil":             923_200_000,
    "Netherlands":        804_200_000,
    "Argentina":          800_500_000,
    "Norway":             589_900_000,
    "Belgium":            547_500_000,
    "Ivory Coast":        522_100_000,
    "Morocco":            498_300_000,
    "Senegal":            478_100_000,
    "Turkey":             473_700_000,
    "Sweden":             406_080_000,
    "Croatia":            387_300_000,
    "United States":      385_650_000,
    "Ecuador":            368_700_000,
    "Uruguay":            359_300_000,
    "Switzerland":        332_500_000,
    "Colombia":           302_350_000,
    "Japan":              270_850_000,
    "Austria":            265_000_000,
    "Scotland":           220_000_000,
    "Australia":          185_000_000,
    "Mexico":             180_000_000,
    "South Korea":        175_000_000,
    "Czech Republic":     165_000_000,
    "Ghana":              160_000_000,
    "Canada":             155_000_000,
    "Egypt":              130_000_000,
    "Tunisia":            110_000_000,
    "Algeria":            105_000_000,
    "Saudi Arabia":       100_000_000,
    "Iran":                95_000_000,
    "Bosnia and Herzegovina": 90_000_000,
    "Paraguay":            85_000_000,
    "New Zealand":         50_000_000,
    "Qatar":               45_000_000,
    "Uzbekistan":          40_000_000,
    "Iraq":                38_000_000,
    "Panama":              35_000_000,
    "South Africa":        30_000_000,
    "Jordan":              25_000_000,
    "Cape Verde":          22_000_000,
    "DR Congo":            20_000_000,
    "Haiti":               12_000_000,
    "Curaçao":              8_000_000,
}

_CSV = Path(__file__).resolve().parents[1] / "data" / "national_market_values.csv"


def _load() -> dict:
    """Hand-written table overlaid with the scraped one, which wins."""
    values = dict(MARKET_VALUES)
    if _CSV.exists():
        with _CSV.open(encoding="utf-8") as fh:
            for row in csv.DictReader(fh):
                try:
                    values[row["team"]] = int(row["market_value_total_eur"])
                except (KeyError, TypeError, ValueError):
                    continue
    return values


VALUES = _load()
_MAX_VALUE = max(VALUES.values())


def has_market_value(team: str) -> bool:
    """Whether we hold a real value, as opposed to falling back to a placeholder."""
    return team in VALUES


def get_market_value(team: str) -> float:
    return float(VALUES.get(team, 0))


def get_market_value_ratio(home: str, away: str) -> float:
    """Strength ratio, or 1.0 where either side is unknown.

    The old code answered 2.0 / 0.5 when one side was missing - a confident
    claim that the known team is twice as strong, which is exactly backwards
    for a strong nation we simply had no row for. 1.0 asserts nothing, and
    market_value_missing tells the model to discount the pair.
    """
    if not (has_market_value(home) and has_market_value(away)):
        return 1.0
    h, a = get_market_value(home), get_market_value(away)
    return h / a if a else 1.0


def get_market_value_normalized(team: str) -> float:
    return get_market_value(team) / _MAX_VALUE
