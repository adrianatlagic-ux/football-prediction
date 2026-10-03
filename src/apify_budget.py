"""Apify's own count of the billing cycle's spend, checked before every run.

The local count (src/book_odds.spend_path) runs by calendar month, misses
the squad runs and anything run by hand, and was lost once in a move - so on
3 October the account hit its limit and every read was refused until the
cycle ended. Apify knows the real figure: GET /users/me/limits gives this
cycle's usage and the account's monthly cap. A run goes ahead only if it
fits under the cap minus RESERVE_USD.

If Apify cannot be asked, the run is allowed and the local count decides,
as before.
"""
from __future__ import annotations

import json
import os
import threading
import time
import urllib.request
from typing import Optional

RESERVE_USD = float(os.getenv("APIFY_RESERVE_USD", "1.0"))
CACHE_SECONDS = 600
_lock = threading.Lock()
_cache = {"at": 0.0, "usage": None}


def usage(token: Optional[str] = None) -> Optional[dict]:
    """{"used": usd this cycle, "limit": usd cap or None, "cycle_end": iso},
    or None when Apify cannot be asked. Cached ten minutes."""
    token = token or os.getenv("APIFY_TOKEN")
    if not token:
        return None
    with _lock:
        if _cache["usage"] is not None and time.time() - _cache["at"] < CACHE_SECONDS:
            return dict(_cache["usage"])
        try:
            req = urllib.request.Request("https://api.apify.com/v2/users/me/limits",
                                         headers={"Authorization": f"Bearer {token}"})
            with urllib.request.urlopen(req, timeout=15) as r:
                data = json.loads(r.read())["data"]
        except Exception:
            return None
        found = {"used": float((data.get("current") or {}).get("monthlyUsageUsd") or 0.0),
                 "limit": (data.get("limits") or {}).get("maxMonthlyUsageUsd"),
                 "cycle_end": (data.get("monthlyUsageCycle") or {}).get("endAt")}
        _cache.update(at=time.time(), usage=found)
        return dict(found)


def allows(cost_usd: float, token: Optional[str] = None) -> bool:
    """Whether a run costing about `cost_usd` fits under the cap and reserve."""
    u = usage(token)
    if u is None or u["limit"] is None:
        return True
    return u["used"] + cost_usd <= float(u["limit"]) - RESERVE_USD


def note_spend(cost_usd: float) -> None:
    """Add a run to the cached figure, so the next check before Apify's own
    count catches up does not see the old number."""
    with _lock:
        if _cache["usage"] is not None:
            _cache["usage"]["used"] += cost_usd
