Log today's betting tips and show the honest performance record so far.

Usage: `/bet-bilanz`

Run, in order:

1. `python3 scripts/log_bets.py`
   Fetches the current live Best-Bet recommendations and appends any new ones to
   data/bet_log.jsonl (each match logged once, with the odds at that moment).

2. `python3 scripts/grade_bets.py`
   Grades every logged tip whose match has finished against the real result and
   prints the running record: wins/losses/pushes, hit rate, profit/loss in units,
   and ROI per tip.

After running, report the bilanz honestly and plainly. Do NOT spin a losing record
as good - if we're down units or below break-even, say so directly. The whole point
of this log is an honest forward-test of whether the tips actually beat the market.
Remind the user the sample is only meaningful after a few dozen graded tips.
