"""Add national-team badges and colours to frontend/src/club_crests.json.

The win-probability donut and the form bar colour each side by its team
colour. National teams had no entry, so every Nations League tie fell back
to the same gold/cyan pair and looked identical to every other.

    python3 scripts/fetch_national_crests.py            # dry run
    python3 scripts/fetch_national_crests.py --write

Existing entries are never overwritten - the file already holds hand-checked
club colours, and a national side sharing a club's name must not silently
repaint it. Names go through the same map as the results importer so a badge
and its fixture refer to the same team.
"""
import argparse
import json
import sys
import urllib.request
from pathlib import Path
from typing import Optional

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.fetch_national_results import team_name

ROOT = Path(__file__).resolve().parents[1]
CRESTS_PATH = ROOT / "frontend" / "src" / "club_crests.json"
TEAMS_API = "https://site.api.espn.com/apis/site/v2/sports/soccer/{}/teams?limit=200"

# Near-white and near-black read as "no colour" against the dark card, and
# the donut needs two distinguishable sides. Teams whose ESPN colour lands
# in those bands get their alternate colour instead.
_TOO_PALE = 0xE0
_TOO_DARK = 0x20


def _brightness(hex_colour: str) -> int:
    try:
        value = int(hex_colour.lstrip("#"), 16)
    except (ValueError, AttributeError):
        return 0
    r, g, b = (value >> 16) & 255, (value >> 8) & 255, value & 255
    return (r * 299 + g * 587 + b * 114) // 1000


def pick_colour(team: dict) -> Optional[str]:
    primary = team.get("color")
    alternate = team.get("alternateColor")
    for candidate in (primary, alternate):
        if not candidate:
            continue
        if _TOO_DARK < _brightness(candidate) < _TOO_PALE:
            return f"#{candidate.lstrip('#')}"
    return f"#{primary.lstrip('#')}" if primary else None


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--league", default="uefa.nations")
    parser.add_argument("--write", action="store_true")
    args = parser.parse_args()

    with urllib.request.urlopen(TEAMS_API.format(args.league), timeout=25) as response:
        payload = json.loads(response.read())
    teams = payload["sports"][0]["leagues"][0]["teams"]

    crests = json.loads(CRESTS_PATH.read_text(encoding="utf-8"))
    added, skipped, colourless = {}, [], []
    for wrapper in teams:
        team = wrapper["team"]
        name = team_name(team["displayName"])
        if name in crests:
            skipped.append(name)
            continue
        colour = pick_colour(team)
        logos = team.get("logos") or []
        if not colour:
            colourless.append(name)
            continue
        added[name] = {"color": colour, "logo": logos[0]["href"] if logos else ""}

    for name, entry in sorted(added.items()):
        print(f"  {name:26} {entry['color']}  {'badge' if entry['logo'] else 'NO BADGE'}")
    print(f"\nnew: {len(added)} | already present: {len(skipped)}")
    if colourless:
        print(f"no usable colour, left out: {', '.join(colourless)}")

    # Two sides of one tie must never end up with the same colour. The donut
    # already falls back at render time, but a clash here is worth naming.
    by_colour = {}
    for name, entry in {**crests, **added}.items():
        by_colour.setdefault(entry["color"].lower(), []).append(name)
    clashes = {c: n for c, n in by_colour.items() if len(n) > 3}
    if clashes:
        print("\nshared colours (the donut falls back for these):")
        for colour, names in sorted(clashes.items(), key=lambda x: -len(x[1]))[:4]:
            print(f"  {colour}: {len(names)} teams - {', '.join(sorted(names)[:5])} ...")

    if not added:
        print("\nNothing to add.")
        return
    if not args.write:
        print("\nDry run. Re-run with --write.")
        return
    crests.update(added)
    CRESTS_PATH.write_text(
        json.dumps(dict(sorted(crests.items())), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8")
    print(f"\nWrote {CRESTS_PATH} ({len(crests)} entries)")


if __name__ == "__main__":
    main()
