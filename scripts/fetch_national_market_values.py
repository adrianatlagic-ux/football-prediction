"""Squad market values for every UEFA nation, from the Nations League tiers.

src/market_values.py holds a hand-written table of the 48 World Cup 2026
participants. For a Nations League fixture that covers barely a third of the
field: eleven of the sixteen teams playing on 2026-09-24 had no entry, and
get_market_value returns 0 for a miss. Zero is not "unknown" - it is a real
number meaning worthless, and market_value_ratio then hard-codes 2.0 or 0.5.
So the model was told Denmark is worth nothing and Norway twice as strong.

The four Nations League participant pages carry all 54 UEFA nations with
their squad value, in one request each.

    python3 scripts/fetch_national_market_values.py

One caveat worth keeping in view: these values are a different measurement
from the hand-written ones, which were 26-man World Cup squads. A nation's
value here covers the squad Transfermarkt lists for the competition. Mixing
the two bases would bias any match between a UEFA and a non-UEFA side, so
the output records which basis each row came from rather than blending them
silently.
"""
from __future__ import annotations

import argparse
import csv
import re
import sys
import time
import urllib.request
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

TIERS = {"UNLA": "A", "UNLB": "B", "UNLC": "C", "UNLD": "D"}
URL = "https://www.transfermarkt.com/uefa-nations-league-a/teilnehmer/pokalwettbewerb/{}"
OUT = ROOT / "data" / "national_market_values.csv"

# Transfermarkt spelling -> the names our results and fixtures use.
ALIASES = {
    "Ireland": "Republic of Ireland", "Czechia": "Czech Republic",
    "Türkiye": "Turkey", "Turkiye": "Turkey",
    "Bosnia-Herzegovina": "Bosnia and Herzegovina",
    "Faroe Islands": "Faroe Islands", "North Macedonia": "North Macedonia",
}


def parse_money(text: str) -> int | None:
    """'€1.78bn' -> 1780000000. Transfermarkt uses . as the decimal point here."""
    m = re.search(r"€\s*([\d.,]+)\s*(bn|m|k)", text, re.I)
    if not m:
        return None
    scale = {"bn": 1e9, "m": 1e6, "k": 1e3}[m.group(2).lower()]
    return int(round(float(m.group(1).replace(",", "")) * scale))


def fetch_tier(code: str) -> list[dict]:
    # A spoofed browser UA gets blocked here; the default Python one works.
    with urllib.request.urlopen(URL.format(code), timeout=30) as resp:
        body = resp.read().decode("utf-8", "ignore")
    teams = []
    for row in re.findall(r'<tr class="(?:odd|even)">(.*?)</tr>', body, re.S):
        name = re.search(r'/startseite/verein/(\d+)"[^>]*>([^<]+)<', row)
        cells = [re.sub(r"<[^>]+>", "", c).strip()
                 for c in re.findall(r"<td[^>]*>(.*?)</td>", row, re.S)]
        if not name or len(cells) < 5:
            continue
        total = parse_money(cells[4])
        if total is None:
            continue
        raw = name.group(2).strip()
        teams.append({
            "team": ALIASES.get(raw, raw), "transfermarkt_name": raw,
            "transfermarkt_id": name.group(1), "tier": TIERS[code],
            "squad_size": int(cells[2]) if cells[2].isdigit() else None,
            "avg_age": cells[3] or None,
            "market_value_total_eur": total,
            "basis": "nations_league_squad",
            "determined_date": date.today().isoformat(),
        })
    return teams


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out", type=Path, default=OUT)
    args = ap.parse_args()

    rows = []
    for code in TIERS:
        found = fetch_tier(code)
        print(f"  Liga {TIERS[code]}: {len(found)} Nationen")
        rows.extend(found)
        time.sleep(1)

    rows.sort(key=lambda r: -r["market_value_total_eur"])
    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)

    print(f"\n{len(rows)} Nationen -> {args.out.relative_to(ROOT)}")
    print(f"  staerkste:  {rows[0]['team']} {rows[0]['market_value_total_eur']/1e9:.2f} Mrd")
    print(f"  schwaechste: {rows[-1]['team']} {rows[-1]['market_value_total_eur']/1e6:.1f} Mio")


if __name__ == "__main__":
    main()
