#!/bin/sh
# Runtime state lives on the Fly volume mounted at /app/state, so a deploy or
# restart keeps the logs, the job reports, the Apify spend count, the squad
# cache, the odds and the predictions the server wrote itself. Each path under
# data/ becomes a link into the volume; files shipped in the image are copied
# in only where the volume has none yet (new fixtures, new predictions), so
# what the server wrote always wins. Without a volume (locally) nothing changes.
set -e
STATE=/app/state
if [ -d "$STATE" ]; then
  for dir in data/logs data/jobs data/squad_cache data/book_odds data/predictions_cache data/fixtures; do
    mkdir -p "$STATE/$dir"
    if [ -d "/app/$dir" ] && [ ! -L "/app/$dir" ]; then
      (cd "/app/$dir" && find . -type f) | while read -r f; do
        if [ ! -e "$STATE/$dir/$f" ]; then
          mkdir -p "$(dirname "$STATE/$dir/$f")"
          cp "/app/$dir/$f" "$STATE/$dir/$f"
        fi
      done
      rm -rf "/app/$dir"
    fi
    mkdir -p "$(dirname "/app/$dir")"
    ln -sfn "$STATE/$dir" "/app/$dir"
  done
  for file in data/odds_snapshot.json data/model_track_record.json; do
    mkdir -p "$(dirname "$STATE/$file")"
    if [ -f "/app/$file" ] && [ ! -L "/app/$file" ]; then
      [ -f "$STATE/$file" ] || cp "/app/$file" "$STATE/$file"
      rm -f "/app/$file"
    fi
    ln -sfn "$STATE/$file" "/app/$file"
  done
fi
exec uvicorn api.app:app --host 0.0.0.0 --port 8080
