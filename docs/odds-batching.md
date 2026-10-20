# Main-market odds refreshes

The morning snapshot loads `h2h,totals,spreads` for each active competition
in one EU-region request, in addition to the free fixture list. A successful
three-market response costs three credits per competition, not per fixture.

Inside the last hour before kickoff, due fixtures are grouped by competition.
Each group gets one league odds request spanning its earliest/latest kickoff.
Only matching event IDs, teams, competition and kickoff times are accepted.
Empty or missing events keep the previous snapshot and remain pending; failed
or missing fixtures retry after 15 minutes. Already refreshed fixtures are not
requested again before kickoff, including after a restart. Concurrent callers share a lock.
Different kickoff windows and retries can therefore cost additional requests.

Morning and final snapshots survive restarts. Final quotes and 15-minute retry
cooldowns are written atomically to `data/jobs/odds_final.json`, already on the
Fly volume through start.sh. Restored quotes must match the event identity and
must have been fetched in its last pre-match hour. Expired quotes are ignored.
Persistence failures produce a cache alert; requests in flight at process death
can still have spent credits before a response was saved.

`/jobs/status` includes `odds_api`: latest observed remaining/used credits,
last-request cost, last paid-request cost, observation time and earliest next
refresh due time. Unknown quota values are null until valid provider headers
arrive; observations are not a live balance query or a monthly reset estimate.
The due time is triggered by the next request or scheduler pass, not a promised
exact execution time. Status reads spend no additional Odds API credits.
Quota observations live in `data/jobs/odds_quota.json`.
No additional markets such as BTTS are introduced in this change.

Example: nine matches in the same competition/window cost three credits for
one final read rather than 27. Morning prices cost three credits instead of
the former one-credit totals-only read. Monthly usage depends on active league
days, kickoff windows and retries; staying under 500 credits is not guaranteed.
