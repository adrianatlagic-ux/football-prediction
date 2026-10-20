# Main-market odds refreshes

The morning snapshot loads `h2h,totals,spreads` for each active competition
in one EU-region request, in addition to the free fixture list. A successful
three-market response costs three credits per competition, not per fixture.

Inside the last hour before kickoff, due fixtures are grouped by competition.
Each group gets one league odds request spanning its earliest/latest kickoff.
Only matching event IDs, teams, competition and kickoff times are accepted.
Empty or missing events keep the previous snapshot and remain pending; failed
or missing fixtures retry after 15 minutes. Already refreshed fixtures are not
requested again during the process lifetime. Concurrent callers share a lock.
Different kickoff windows and retries can therefore cost additional requests.

The morning snapshot survives restarts. Final snapshots and retry cooldowns
remain in memory, as before; restarting in the last hour can repeat a paid read.
No additional markets such as BTTS are introduced in this change.

Example: nine matches in the same competition/window cost three credits for
one final read rather than 27. Morning prices cost three credits instead of
the former one-credit totals-only read. Monthly usage depends on active league
days, kickoff windows and retries; staying under 500 credits is not guaranteed.
