# AI-tip fallback rule (`ki_model_fallback_v3`)

The original AI pick remains the headline whenever its model probability is
at least the market probability and its odds are at least 1.30. A changed AI
pick still withholds all tips, including same-direction changes.

Only a model-below-market rejection triggers a search through the current
priced candidates. An alternative must be binary, strictly weaker, have a
fresh actual quote >=1.30 and its own model probability >= its own market
probability. There is no positive-EV requirement.

- Under: increase the goal line (Under 2.5 -> Under 3.5).
- Over: decrease the goal line (Over 2.5 -> Over 1.5).
- Team win: same-team positive half-goal handicap (+0.5 = double chance).
- Team handicap: increase the same team's half-goal handicap (-1.5 -> -0.5).

Choose the nearest qualifying line; ties use the better quote, then stable
market/outcome/team ordering. Harder bets, opposite teams/directions,
whole/quarter lines and cross-family substitutions are excluded. Missing
quotes, model/market data, or an original below the minimum odds do not
trigger a rescue.

The response marks `is_fallback`, `original_pick`, and `fallback_reason`.
The UI labels the result as an alternative derived from the original AI pick;
confirmation refers to the AI retaining that original pick. It places the
accepted alternative among the visible table signals. Existing bet-tip logs
keep this metadata, and new logs also include all priced candidates.
