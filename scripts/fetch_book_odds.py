"""Fetch bet-at-home's current 1X2 odds from OddsPortal for all three competitions.

The price tip compares a bookmaker Adrian can actually use against Pinnacle's
margin-free price. The Odds API carries Pinnacle but none of the German-
licensed books; OddsPortal carries them when fetched through a German proxy,
and it does not carry Pinnacle. So the two sources are joined per fixture.

    python3 scripts/fetch_book_odds.py                  # all three competitions
    python3 scripts/fetch_book_odds.py --max-items 5    # cheap check

bet-at-home was chosen from the archive: across 389 Bundesliga matches it
most often quoted above Pinnacle's closing fair price, and on the season with
clean Pinnacle data (2023-24) all its opportunities sat at ordinary odds
rather than long shots (see scripts/german_books_vs_pinnacle.py).

The app refreshes these odds itself in the hour before kickoff
(src/book_odds.refresh_if_due); this script fills the file for everything
further out. Costs about 0.3 cents per fixture on Apify.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src import book_odds  # noqa: E402


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--max-items", type=int, default=60)
    args = ap.parse_args()

    for sport_key in book_odds.LEAGUES:
        try:
            fixtures = book_odds.fetch_league(sport_key, args.max_items)
        except Exception as exc:
            print(f"  {sport_key}: FEHLER {type(exc).__name__}: {exc}")
            continue
        book_odds.store(sport_key, fixtures, replace=True)
        print(f"  {sport_key:28} {len(fixtures):3} Spiele mit {book_odds.BOOKMAKER}")
    print(f"\n-> {book_odds.path()}")


if __name__ == "__main__":
    main()
