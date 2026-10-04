"""National team names as OddsPortal writes them in other languages.

OddsPortal localises team names by where the request seems to come from.
Read through a residential proxy it once answered in Polish ("Grecja -
Niemcy"), and every match failed to pair with the English fixture list, so
the day had no bet-at-home prices. Names are mapped to English before they
are stored; unknown names pass through unchanged.
"""
from __future__ import annotations

import unicodedata

# Polish and German spellings of the European nations (and a few others in
# the Nations League / qualifiers), mapped to the English names the fixture
# list uses.
_NAMES = {
    # Polish
    "albania": "Albania", "andora": "Andorra", "armenia": "Armenia", "austria": "Austria",
    "azerbejdzan": "Azerbaijan", "bialorus": "Belarus", "belgia": "Belgium",
    "bosnia i hercegowina": "Bosnia and Herzegovina", "bulgaria": "Bulgaria", "chorwacja": "Croatia",
    "cypr": "Cyprus", "czarnogora": "Montenegro", "czechy": "Czech Republic", "dania": "Denmark",
    "estonia": "Estonia", "finlandia": "Finland", "francja": "France", "gibraltar": "Gibraltar",
    "grecja": "Greece", "gruzja": "Georgia", "hiszpania": "Spain", "holandia": "Netherlands",
    "irlandia": "Republic of Ireland", "irlandia polnocna": "Northern Ireland", "islandia": "Iceland",
    "izrael": "Israel", "kazachstan": "Kazakhstan", "kosowo": "Kosovo", "liechtenstein": "Liechtenstein",
    "litwa": "Lithuania", "luksemburg": "Luxembourg", "lotwa": "Latvia", "macedonia polnocna": "North Macedonia",
    "malta": "Malta", "moldawia": "Moldova", "niemcy": "Germany", "norwegia": "Norway", "polska": "Poland",
    "portugalia": "Portugal", "rumunia": "Romania", "san marino": "San Marino", "serbia": "Serbia",
    "slowacja": "Slovakia", "slowenia": "Slovenia", "szkocja": "Scotland", "szwajcaria": "Switzerland",
    "szwecja": "Sweden", "turcja": "Turkey", "ukraina": "Ukraine", "walia": "Wales", "wegry": "Hungary",
    "wlochy": "Italy", "wyspy owcze": "Faroe Islands", "anglia": "England", "rosja": "Russia",
    # German
    "albanien": "Albania", "armenien": "Armenia", "osterreich": "Austria", "aserbaidschan": "Azerbaijan",
    "weissrussland": "Belarus", "belarus": "Belarus", "belgien": "Belgium",
    "bosnien und herzegowina": "Bosnia and Herzegovina", "bulgarien": "Bulgaria", "kroatien": "Croatia",
    "zypern": "Cyprus", "montenegro": "Montenegro", "tschechien": "Czech Republic", "danemark": "Denmark",
    "estland": "Estonia", "finnland": "Finland", "frankreich": "France", "griechenland": "Greece",
    "georgien": "Georgia", "spanien": "Spain", "niederlande": "Netherlands", "irland": "Republic of Ireland",
    "nordirland": "Northern Ireland", "island": "Iceland", "kasachstan": "Kazakhstan", "kosovo": "Kosovo",
    "litauen": "Lithuania", "luxemburg": "Luxembourg", "lettland": "Latvia", "nordmazedonien": "North Macedonia",
    "moldau": "Moldova", "moldawien": "Moldova", "deutschland": "Germany", "norwegen": "Norway",
    "polen": "Poland", "rumanien": "Romania", "serbien": "Serbia", "slowakei": "Slovakia",
    "slowenien": "Slovenia", "schottland": "Scotland", "schweiz": "Switzerland", "schweden": "Sweden",
    "turkei": "Turkey", "italien": "Italy", "ungarn": "Hungary", "farer": "Faroe Islands",
    "faroer": "Faroe Islands", "england": "England",
}


def _key(name: str) -> str:
    plain = unicodedata.normalize("NFKD", name or "").replace("ł", "l").replace("Ł", "L")
    plain = plain.encode("ascii", "ignore").decode().lower()
    return " ".join(plain.replace("-", " ").split())


def to_english(name: str) -> str:
    return _NAMES.get(_key(name), name)
