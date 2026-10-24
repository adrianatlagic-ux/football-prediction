# AI tip input quality

The established Gemini research prompt is still the basis of the tip. It makes
one grounded Gemini call at the early review and one at the scheduled review
before kickoff, as before. There is no parallel Gemini call or second search.
The revised input supplies all supported, fresh 1X2, Handicap, Over/Under and
BTTS quotes in neutral order. It also supplies the statistical model's headline
1X2 probabilities and, when available, its home/away expected goals. Those are
labelled model estimates to weigh against current research. The chosen model
bet, green/red shortlist labels, per-bet model scores, Kelly stakes and expected
value are not supplied.

A paid call is postponed until all three 1X2 outcomes, both directions of one
totals line and opposing handicap lines are present. BTTS is optional. While
coverage is incomplete, the tip reports `incomplete_markets`; the normal
schedule retries until a complete snapshot is available. The pre-kickoff read
still uses its existing odds refresh. This change adds no provider requests.

The later check receives the earlier selection and a concise quote delta as
context. New team news, market availability or odds can justify a different
choice. The prompt asks for a concrete reason and a comparison with the
strongest alternative. The existing rule still withholds a public tip when the
AI changes its selection.
This is recorded as `revised_from_previous`; it is not interpreted as proof
that the new selection is worse. A first complete review after an incomplete
book is not counted as a change of mind.

`agent_eval` keeps the exact candidate/quote snapshot, model context, full
prompt, research, source associations, and the prior selection and input at a
re-check. The bet log copies it for later analysis. The model and the AI now
share headline probabilities; their agreement is a comparison, not an
independent confirmation. Historical tip performance cannot establish the
causal effect of this change without a simultaneous control group. Comparing
market distribution and realized outcomes after 30–50 matches is a first
observation, not evidence of profitability.

A longer prompt can use slightly more input tokens, but there is no additional
Gemini request per review. No live Gemini calls were used for validation.

Focused verification:

```sh
.venv/bin/python -m pytest -q tests/test_ai_tip_research.py tests/test_bet_tip_fallback.py tests/test_bet_selection.py tests/test_odds_schedule.py tests/test_odds_snapshot.py tests/test_odds_runtime.py
```
