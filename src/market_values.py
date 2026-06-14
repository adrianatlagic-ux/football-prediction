"""
Squad market values (EUR) from Transfermarkt, June 2026.
Alle 48 WM-2026-Teilnehmer. Quelle: transfermarkt.com
"""

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

_MAX_VALUE = max(MARKET_VALUES.values())


def get_market_value(team: str) -> float:
    return float(MARKET_VALUES.get(team, 0))


def get_market_value_ratio(home: str, away: str) -> float:
    h = get_market_value(home)
    a = get_market_value(away)
    if h == 0 and a == 0:
        return 1.0
    if a == 0:
        return 2.0
    if h == 0:
        return 0.5
    return h / a


def get_market_value_normalized(team: str) -> float:
    return get_market_value(team) / _MAX_VALUE
