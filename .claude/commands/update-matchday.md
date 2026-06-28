Update training data and publish predictions for an upcoming WC2026 matchday, replacing the old n8n step.

Usage: `/update-matchday 2026-06-27` (date is the matchday to generate predictions for; omit for today)

Run, in order:

1. `python3 scripts/update_training_data.py`
   Pulls finished results from ESPN into `data/international_results.csv`, retrains the model, and
   regenerates all cached predictions. Skip this step only if it was already run very recently
   (e.g. earlier the same day) and no new matches have finished since.

2. `python3 scripts/predict_and_upload.py <date>`
   Generates predictions for every fixture on `<date>` and uploads them to the live backend
   (`https://football-prediction.fly.dev`) so the website and the Best Bets tab can use them.

After both steps, report a short summary: how many results were pulled in, whether the model was
retrained, and which matches got predictions uploaded (with their H/D/A split). Do not run
`fly deploy` as part of this — it's not needed, predictions are pushed live via the API directly.
