# Combo market-probability floor review, 25 October 2026

Question: Would removing the shown `agree` combo policy's 45% minimum
margin-free market probability improve hit rate or flat-stake ROI? The
comparison keeps the other rules fixed: bet-at-home only, one leg per match,
same Berlin matchday, fresh binary-settlement quotes, at least 1.30 per leg,
model probability no more than five points below the market, and at least
3.00 combined odds. ROI is net units divided by tickets at one unit per
ticket. The same ticket search and ranking were replayed for each floor.
This isolates the probability-floor question under the former single-book
rule. It is not a backtest of the new cross-book combination display.

## Primary sensitivity checks

| Data | Floor | 2-fold (wins/tickets, ROI) | 3-fold | 4-fold |
| --- | ---: | ---: | ---: | ---: |
| Nations League live, 7 days | 45% | 5/6, +162% | 4/7, +100% | 3/6, +164.5% |
| Nations League live, 7 days | none | 5/7, +133.3% | 3/7, +48.4% | 3/7, +126.7% |
| Nations League history, 25 days, 1X2 only | 45% | 7/15, +56.9% | 5/14, +42.8% | 3/9, +115.4% |
| Nations League history, 25 days, 1X2 only | none | 9/22, +34.9% | 6/20, +24.6% | 3/20, −3.1% |

The 44% floor produced exactly the same tickets and outcomes as 45% in both
datasets. A separate replay of the server's saved bet log from 4–24 October
matched 75 finished fixtures across 13 days. That log stores only each
market's best-book quote, not every bet-at-home offer; its replay is therefore
incomplete and not directly equivalent to the live combo endpoint. Its
2-fold result was 2/2, +210.5% at 45%, versus 5/7, +190.7% with no floor;
the small samples and missing offers make these percentages unstable.

Removing the floor creates more tickets but shows no consistent improvement
in hit rate or ROI. The historical returns are highly variable and do not
prove profitability. The narrow 44% tolerance is a product-rule adjustment,
not a claim of better performance: it adds no tickets in the completed
historical tests, but admits Leverkusen at 44.18% in the 25 October morning
snapshot. Together with Bayern at bet-at-home, that produces a same-book
2-fold at 2.15 × 1.45 = 3.12. The match outcomes were still unknown when
this change was prepared.

The subsequent display change selects the best fresh offer for each leg,
regardless of bookmaker. Historical returns above cannot establish whether
that change improves hit rate or ROI. A product of prices from different
bookmakers is a theoretical quote, not a verified available accumulator.
