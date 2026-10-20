# Historical AI-tip fallback audit — 20 October 2026

Exploratory replay of the current rule on recorded pre-match selections;
not the performance of an unchanged strategy deployed throughout this period.
Downloaded `/logs/bet_log` and `/real-results` from the live Fly app. Input
SHA-256 hashes and per-bet decisions are in `report.json`. Raw downloaded
inputs remain in `/tmp/football-fallback-audit/` in this workspace.

95 completed regulation-time fixtures had an AI pick. One latest pre-kickoff
log per competition/team pair/exact kickoff; post-kickoff research excluded.
Reported accepted bets span 28 September–20 October 2026. Thirteen logs had
no matching completed regulation result; five had no AI pick.

| Policy | Bets | Wins | Hit rate | Profit, units | ROI |
|---|---:|---:|---:|---:|---:|
| Current rule replay | 43 | 32 | 74.4% | +25.16 | +58.5% |
| Current + positive raw-model EV | 41 | 30 | 73.2% | +23.61 | +57.6% |
| Current + weaker fallback | 43 | 32 | 74.4% | +25.16 | +58.5% |
| Fallback + positive raw-model EV | 41 | 30 | 73.2% | +23.61 | +57.6% |

One unit per single, recorded decimal prices, no compounding or commission.
AI changes remain disallowed. Fallback activates only when the original's
model probability is below its market probability, with original odds >=1.30.
It chooses the nearest qualifying weaker binary line in the same family and
direction, using the better price for ties. Each candidate needs recorded
model >= market and odds >=1.30. Edge means raw model p * odds - 1 > 0,
including for original tips; no fitted positive-edge threshold is introduced.
Originals failing only EV do not trigger a fallback.

The 24 possible rescues produced no qualifying recorded fallback. Twelve had
at least one recorded weaker binary alternative; none qualified. These logs
have green candidates and only selected red candidates, not the complete
menu. Missing lines must not be reconstructed from today's quotes. Therefore
this does not establish that the idea would never help with full coverage.

The two bets removed by the edge requirement both won: Malta–Gibraltar
Under 2.5 (1.78), and Montenegro to win against Latvia (1.77). This alone is
far too little evidence against an EV filter. Date-cluster bootstrap 95%
interval for its ROI change versus baseline is approximately -4.9 to +2.1
percentage points; no reliable improvement or deterioration is demonstrated.
The high pooled return is dominated by small Nations League/Champions League
samples; Bundesliga alone was 3/6 wins and -11.5% ROI. The existing rule was
already informed by part of this history, so the pooled return is not an
independent estimate of future profitability.

Recommendation: retain the live rule, log the full candidate menu and run the
fallback/EV variants in parallel on future matches before promoting one.

Reproduce:

```sh
.venv/bin/python scripts/audit_fallback_tips.py \
  --logs /tmp/football-fallback-audit/server_bet_log.jsonl \
  --results /tmp/football-fallback-audit/results.json \
  --out data/model_reports/fallback_tip_audit/report.json
```
