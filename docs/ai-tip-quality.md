# Independent AI tip review

The live Gemini selector uses `src/ai_tip_research.py`, version
`independent_market_review_v2`. It receives every fresh supported bet from the
full `bets` list, sorted by market and outcome. Green/red display shortlists,
model probabilities, Kelly scores and previous picks do not enter its prompt.
The existing downstream model agreement and weaker-line fallback rules remain.

Before a paid research call, the candidate book must include all three 1X2
outcomes, both directions of at least one totals line and opposing handicap
lines for the two teams. BTTS is included when available but is optional.
Missing main markets produce `incomplete_markets`, no AI bet and no Wett-Tipp.
A later scheduled complete snapshot can be evaluated again. Existing scheduled
Odds API reads already request h2h, totals and spreads together; this change
adds no provider requests or BTTS scraping. Freshness retains the application's
scheduled-snapshot semantics (fresh at retrieval, not a continuous live feed).

The prompt supplies kickoff date/year, competition, research time and quote
retrieval time. It preserves the research angles and local-language search,
requests dated source facts, comparison of available market families, the best
alternative and counterevidence. It explicitly permits no pick and neither
requests invented precise probabilities nor a target distribution of markets.
Source association and publication timestamps are logged, not certified as
independently verified facts.

The pre-kickoff review makes a new decision without seeing its predecessor.
Only afterwards does the server compare selections. A changed selection still
withholds the Wett-Tipp. A first complete review after missing markets is not
mislabelled as a change of mind. An intentional no-pick result has a distinct
user-facing message instead of saying research is pending.

`agent_eval` preserves the exact public input snapshot, coverage, candidate
quotes and provenance, prompt version, market comparison and alternative reason.
At recheck it also preserves the first input and first pick. These are saved by
the existing agent cache and bet log. Existing cached decisions are not silently
rewritten on deployment: the new policy applies on the next scheduled AI call.

## Validation

Mocked Gemini calls verify full-book selection, neutral ordering, no model/old
pick leakage, missing/stale/one-sided markets, first review after incomplete
coverage, changed-pick withholding, unchanged-pick confirmation and log retention.
No paid Gemini requests or live outcome claims are part of these tests.

Run the focused suite:

```sh
.venv/bin/python -m pytest -q tests/test_ai_tip_research.py tests/test_bet_tip_fallback.py tests/test_bet_selection.py tests/test_odds_schedule.py tests/test_odds_snapshot.py tests/test_odds_runtime.py
```

The complete suite currently cannot collect three unrelated research tests:
`test_hit_selector.py`, `test_joint_score_model.py`, `test_strict_selector.py`.
Their imported training/research modules are absent from this checkout.
