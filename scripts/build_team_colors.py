"""Extract each team's main colours from its flag or crest.

    python3 scripts/build_team_colors.py

The match donut used ESPN's single "team colour", which is a placeholder
(white, or one shared red) for many clubs and missing for every nation, so
most charts fell back to the same gold and cyan. Here the colours come from
the image the page already shows next to the name: the flag for a nation
(flagcdn.com), the crest for a club (club_crests.json).

Club crests are a poor source on their own (Barcelona's comes out yellow,
Freiburg's grey), so a club's first colour is its ESPN colour where that is
a real one, or a hand-set colour where ESPN returns a placeholder (plain
white or black); the crest's colours follow as alternatives for when two
teams would otherwise look alike.

A colour's share of the image decides its rank. White and near-black are
ranked last, since on the page's dark background black vanishes and white
is hard to tell from the grey used for the draw; they are kept so a black-
and-white club still has its own colours to fall back on.

Writes frontend/src/team_colors.json: {team: {"colors": [...], "iso": ..}}.
"""
from __future__ import annotations

import io
import json
import sys
import urllib.request
from collections import Counter
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "frontend" / "src" / "team_colors.json"

# flagcdn codes. England, Scotland, Wales and Northern Ireland use the
# gb-* subdivision flags.
NATION_ISO = {
    "Albania": "al", "Algeria": "dz", "Andorra": "ad", "Argentina": "ar", "Armenia": "am",
    "Australia": "au", "Austria": "at", "Azerbaijan": "az", "Belarus": "by", "Belgium": "be",
    "Bosnia and Herzegovina": "ba", "Brazil": "br", "Bulgaria": "bg", "Canada": "ca",
    "Cape Verde": "cv", "Colombia": "co", "Croatia": "hr", "Curacao": "cw", "Curaçao": "cw",
    "Cyprus": "cy", "Czech Republic": "cz", "DR Congo": "cd", "Denmark": "dk", "Ecuador": "ec",
    "Egypt": "eg", "England": "gb-eng", "Estonia": "ee", "Faroe Islands": "fo", "Finland": "fi",
    "France": "fr", "Georgia": "ge", "Germany": "de", "Ghana": "gh", "Gibraltar": "gi",
    "Greece": "gr", "Haiti": "ht", "Hungary": "hu", "Iceland": "is", "Iran": "ir", "Iraq": "iq",
    "Israel": "il", "Italy": "it", "Ivory Coast": "ci", "Japan": "jp", "Jordan": "jo",
    "Kazakhstan": "kz", "Kosovo": "xk", "Latvia": "lv", "Liechtenstein": "li", "Lithuania": "lt",
    "Luxembourg": "lu", "Malta": "mt", "Mexico": "mx", "Moldova": "md", "Montenegro": "me",
    "Morocco": "ma", "Netherlands": "nl", "New Zealand": "nz", "North Macedonia": "mk",
    "Northern Ireland": "gb-nir", "Norway": "no", "Panama": "pa", "Paraguay": "py", "Poland": "pl",
    "Portugal": "pt", "Qatar": "qa", "Republic of Ireland": "ie", "Romania": "ro",
    "San Marino": "sm", "Saudi Arabia": "sa", "Scotland": "gb-sct", "Senegal": "sn",
    "Serbia": "rs", "Slovakia": "sk", "Slovenia": "si", "South Africa": "za",
    "South Korea": "kr", "Spain": "es", "Sweden": "se", "Switzerland": "ch", "Tunisia": "tn",
    "Turkey": "tr", "Ukraine": "ua", "United States": "us", "Uruguay": "uy", "Uzbekistan": "uz",
    "Wales": "gb-wls",
}


# Clubs whose ESPN colour is a placeholder (white or black) or wrong.
CLUB_PRIMARY = {
    "1. FC Köln": "#ed1c24", "1. FSV Mainz 05": "#c3141e", "AS Monaco FC": "#e51b22", "Monaco": "#e51b22",
    "Augsburg": "#ba3733", "Bayer Leverkusen": "#e32219", "Besiktas": "#f5f5f5",
    "Borussia Mönchengladbach": "#00983a", "Bournemouth": "#da291c", "Brentford": "#e30613",
    "Eintracht Frankfurt": "#e1000f", "Elversberg": "#f5f5f5", "Fulham": "#f5f5f5",
    "Juventus": "#f5f5f5", "Juventus FC": "#f5f5f5", "Leeds United": "#f5f5f5",
    "Lyon": "#1d4fa0", "Marseille": "#2faee0", "Olympique de Marseille": "#2faee0",
    "Newcastle United": "#f5f5f5", "Newcastle United FC": "#f5f5f5", "Norwich City": "#f9d71c",
    "Porto": "#1f5fbf", "RB Leipzig": "#dd0741", "RC Lens": "#fdd835",
    "Real Madrid": "#f5f5f5", "Real Madrid CF": "#f5f5f5", "SC Freiburg": "#d50032",
    "SC Paderborn": "#1f6fc0", "Schalke 04": "#1f5fbf", "Sevilla": "#d81e05",
    "Sheffield United": "#ee2737", "Tottenham": "#f5f5f5", "Tottenham Hotspur FC": "#f5f5f5",
    "Union Berlin": "#e30613", "Valencia": "#ee7814", "VfB Stuttgart": "#e32219",
    "Villarreal": "#ffe667", "Watford": "#fbee23", "Barcelona": "#a50044",
}
PLACEHOLDERS = {"#ffffff", "#000000"}


def fetch_image(url: str) -> Image.Image:
    with urllib.request.urlopen(url, timeout=20) as response:
        return Image.open(io.BytesIO(response.read())).convert("RGBA")


def _hex(rgb) -> str:
    return "#{:02x}{:02x}{:02x}".format(*rgb)


def _distance(a, b) -> float:
    return sum((x - y) ** 2 for x, y in zip(a, b)) ** 0.5


def palette(image: Image.Image, limit: int = 3) -> list[str]:
    """The image's main colours, largest area first, white and black last."""
    image = image.copy()
    image.thumbnail((120, 120))
    counts = Counter()
    for r, g, b, alpha in image.getdata():
        if alpha < 200:
            continue
        # Coarse bins so anti-aliased edges join their colour.
        counts[(r // 24 * 24 + 12, g // 24 * 24 + 12, b // 24 * 24 + 12)] += 1
    total = sum(counts.values()) or 1
    groups: list[list] = []   # [summed rgb weights, count]
    for rgb, n in counts.most_common():
        for g in groups:
            centre = tuple(c / g[1] for c in g[0])
            if _distance(centre, rgb) < 60:
                g[0] = [c + v * n for c, v in zip(g[0], rgb)]
                g[1] += n
                break
        else:
            groups.append([[v * n for v in rgb], n])
    colours = []
    for sums, n in sorted(groups, key=lambda g: -g[1]):
        if n / total < 0.04:
            continue
        rgb = tuple(min(255, round(v / n)) for v in sums)
        neutral = min(rgb) > 215 or max(rgb) < 50
        colours.append((neutral, rgb))
    ordered = [rgb for neutral, rgb in colours if not neutral] + [rgb for neutral, rgb in colours if neutral]
    return [_hex(rgb) for rgb in ordered[:limit]]


def main():
    crests = json.loads((ROOT / "frontend" / "src" / "club_crests.json").read_text(encoding="utf-8"))
    out, failed = {}, []
    for name, iso in sorted(NATION_ISO.items()):
        try:
            out[name] = {"colors": palette(fetch_image(f"https://flagcdn.com/w160/{iso}.png")), "iso": iso}
        except Exception as exc:
            failed.append((name, exc))
    for name, crest in sorted(crests.items()):
        if name in NATION_ISO:
            continue      # a nation's colours come from its flag
        primary = CLUB_PRIMARY.get(name)
        if not primary and (crest.get("color") or "").lower() not in PLACEHOLDERS:
            primary = crest["color"].lower()
        try:
            alternatives = palette(fetch_image(crest["logo"]))
        except Exception as exc:
            failed.append((name, exc))
            alternatives = []
        colours = ([primary] if primary else []) + [c for c in alternatives if c != primary]
        out[name] = {"colors": colours[:4]}
    for name, info in out.items():
        print(f"  {name:28} {' '.join(info['colors'])}")
    for name, exc in failed:
        print(f"  FEHLER {name}: {exc}", file=sys.stderr)
    OUT.write_text(json.dumps(out, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(f"\n{len(out)} Teams -> {OUT}")


if __name__ == "__main__":
    main()
