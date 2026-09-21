# Market-value policy comparison

| Policy | n | Accuracy | Log loss | Brier |
|---|---:|---:|---:|---:|
| current_season | 1788 | 53.4% | 0.9837 | 0.5847 |
| lagged_season | 1788 | 53.0% | 0.9882 | 0.5879 |
| verified_only | 1788 | 53.1% | 0.9922 | 0.5906 |

| Policy | Competition | n | Accuracy | Log loss | Brier |
|---|---|---:|---:|---:|---:|
| current_season | bundesliga | 1224 | 52.9% | 0.9884 | 0.5876 |
| lagged_season | bundesliga | 1224 | 52.6% | 0.9959 | 0.5927 |
| verified_only | bundesliga | 1224 | 52.7% | 1.0029 | 0.5974 |
| verified_only | champions_league | 564 | 53.9% | 0.9691 | 0.5757 |
| lagged_season | champions_league | 564 | 53.9% | 0.9716 | 0.5776 |
| current_season | champions_league | 564 | 54.3% | 0.9734 | 0.5785 |

## Paired log-loss tests

| Comparison | n | Mean difference | z |
|---|---:|---:|---:|
| lagged_season_vs_verified_only | 1788 | -0.0040 | -1.62 |
| current_season_vs_verified_only | 1788 | -0.0086 | -2.84 |
| current_season_vs_lagged_season | 1788 | -0.0045 | -2.43 |

Negative mean difference favours the first policy. |z| below ~2 is not
distinguishable from noise at this sample size.

A better score for `current_season` would not establish that its availability
assumption holds - leakage also improves scores. The useful reading is the
reverse: if it is not clearly better, the aggressive assumption buys nothing.
