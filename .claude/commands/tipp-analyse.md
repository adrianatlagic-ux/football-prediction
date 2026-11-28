Show how the tips did, week by week: bet tip (AI v9), shadow (v10 with memory), the market's likeliest bet and the combos.

Usage: `/tipp-analyse` (optional: a start date, e.g. `/tipp-analyse 2026-11-15`)

Run:

`python3 scripts/tip_report.py` (add `--since <date>` when a date was given)

It reads the server's logs (https://football-prediction.fly.dev/logs/tips and /logs/combos)
and prints five Markdown tables. Show all five tables to the user as they are, in German,
then add a short reading (five to eight sentences, plain words, no jargon):

1. Which tipper hit more often than the bookmakers' odds expected ("besser als Markt") over the
   whole period, and which did not. That column is the only sign of real skill; a hit rate alone
   is not.
2. What changed against the week before ("Δ Trefferquote zur Vorwoche") and whether that is more
   than chance: with fewer than about 30 tips a week, a swing of 10 points is normal.
3. Which kind of bet (win, handicap, over, under) wins or loses the units.
4. Shadow vs bet tip where they differ: who hits more.
5. Whether the shadow learns: its own estimate should come closer to its hit rate over the weeks,
   and its "besser als Markt" should rise. Say plainly if neither happens.
6. Combos: say how many tickets there are; under a few dozen per rule and size the result says
   little.

Be honest: do not spin a losing record or read a pattern into a handful of tips. If something
looks broken (a tipper with no tips in a week, missing results), say so.
