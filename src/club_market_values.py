"""
Total squad market values (EUR) for club football teams, from Transfermarkt.
Covers Champions League + the biggest European domestic leagues (source season
2025/26). Fetched via Apify (incognito_mode/transfermarkt-competition-scraper) -
see scripts/fetch_club_market_values.py to refresh.

Coverage is intentionally partial: smaller leagues (Kazakhstan, Belarus, Russia,
Ukraine, Israel, Serbia, Moldova, Cyprus, Romania, Slovenia...) are not included,
so newly-promoted/qualified clubs from those leagues fall back to 0 (get_market_value
below handles that the same way src/market_values.py does for national teams).
"""

MARKET_VALUES: dict[str, int] = {
    "Real Madrid": 1460000000,
    "Real Madrid CF": 1460000000,
    "Manchester City": 1430000000,
    "Manchester City FC": 1430000000,
    "Arsenal": 1330000000,
    "Barcelona": 1260000000,
    "Chelsea": 1080000000,
    "Bayern Munich": 1040000000,
    "Liverpool": 1030000000,
    "Tottenham": 824000000,
    "Tottenham Hotspur FC": 824000000,
    "Manchester United": 774600000,
    "Manchester United FC": 774600000,
    "Inter Milan": 730300000,
    "Crystal Palace": 702500000,
    "Bournemouth": 680980000,
    "Atlético Madrid": 679700000,
    "Club Atlético de Madrid": 679700000,
    "Nottingham Forest": 638680000,
    "Brighton & Hove Albion": 625000000,
    "Juventus": 619300000,
    "Juventus FC": 619300000,
    "RB Leipzig": 618700000,
    "Aston Villa": 613980000,
    "Newcastle United": 606100000,
    "Newcastle United FC": 606100000,
    "Borussia Dortmund": 564450000,
    "Sporting Lisbon": 559000000,
    "Bayer Leverkusen": 548350000,
    "Milan": 511700000,
    "Brentford": 503580000,
    "AS Roma": 503300000,
    "Porto": 493050000,
    "Bayer 04 Leverkusen": 480950000,
    "West Ham United": 469730000,
    "Everton": 459250000,
    "Atalanta": 436050000,
    "Atalanta BC": 436050000,
    "Napoli": 432500000,
    "Galatasaray": 411600000,
    "Galatasaray SK": 411600000,
    "Wolverhampton Wanderers": 389850000,
    "Benfica": 377050000,
    "Fulham": 376200000,
    "Leeds United": 374200000,
    "Villarreal": 331600000,
    "AS Monaco FC": 314650000,
    "Monaco": 314650000,
    "Real Sociedad de Fútbol": 299000000,
    "Eintracht Frankfurt": 288250000,
    "SS Lazio": 288130000,
    "PSV Eindhoven": 284450000,
    "Southampton": 276000000,
    "Besiktas": 273350000,
    "RC Lens": 266600000,
    "Feyenoord": 255830000,
    "Burnley": 236000000,
    "Wolfsburg": 234100000,
    "Athletic Bilbao": 230800000,
    "Ipswich Town": 229230000,
    "Leicester City": 203150000,
    "Club Brugge": 199000000,
    "Olympiacos": 184450000,
    "Marseille": 181850000,
    "Olympique de Marseille": 181850000,
    "Sevilla": 176500000,
    "Borussia Mönchengladbach": 171400000,
    "Trabzonspor": 169600000,
    "Rangers FC": 169000000,
    "Celtic": 162800000,
    "Anderlecht": 152650000,
    "Valencia": 147030000,
    "Sheffield United": 140950000,
    "Norwich City": 135200000,
    "Union Berlin": 129850000,
    "Watford": 110700000,
    "Royal Antwerp FC": 102800000,
    "West Bromwich Albion": 101980000,
    "Basel": 94900000,
    "Royale Union Saint-Gilloise": 93700000,
    "Viktoria Plzen": 90830000,
    "BSC Young Boys": 89280000,
    "Dinamo Zagreb": 88050000,
    "FK Bodø/Glimt": 79180000,
    "Copenhagen": 68250000,
    "Malmo FF": 31430000,
    "Qarabağ Ağdam FK": 25080000,
    "FK Kairat": 9200000,
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
