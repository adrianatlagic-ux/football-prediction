"""Squads, player values and absences from Transfermarkt, fetched via Apify.

Fetching the squad rather than asking for it removes the possibility of
invention instead of detecting it afterwards: the research agent had already
returned twenty absent players across two fixtures with source links, while
the search tool had grounded nothing and the links were expiring redirects
(data/research_log.jsonl). The per-player values are what turn an absence
into a number the model can use rather than a remark.

Apify runs the request on its own infrastructure, so this machine's address
never reaches Transfermarkt and a markup change is the actor author's problem
rather than a silently broken parser here. The same data is readable without
it - a direct fetch returned an identical 419.0m for Denmark - so nothing but
that separation is being paid for.

Who is actually missing depends on the competition, and src/competitions.py
explains why: national call-ups already exclude the injured and have no
injury page, while club rosters keep them and do. Both paths end in the same
figure, absent_value_share, so the caller does not have to care which applied.
"""
from __future__ import annotations

import json
import os
import urllib.request
from datetime import date, datetime
from typing import Optional

ACTOR = "solidcode~transfermarkt-scraper"
ENDPOINT = "https://api.apify.com/v2/acts/{}/run-sync-get-dataset-items?token={}"
SQUAD_URL = "https://www.transfermarkt.com/x/startseite/verein/{}"

# Records that belong to the competition that issued them: bans, and squad
# registration gaps ("No eligibility" - not named in a Champions League squad,
# say). Everything else, injuries above all, travels with the player.
COMPETITION_BOUND_MARKERS = ("suspension", "ban", "sperre", "suspended", "eligibility")
# The per-player sum never matches the published squad total exactly - a
# player or two carries no value - but a healthy fetch lands within this.
TOLERANCE = 0.15


def _post(payload: dict, token: str, timeout: int) -> list:
    request = urllib.request.Request(
        ENDPOINT.format(ACTOR, token), method="POST",
        data=json.dumps(payload).encode(), headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode())


def fetch_squads(transfermarkt_ids, with_injuries: bool = True,
                 token: Optional[str] = None, timeout: int = 600) -> dict:
    """Every given squad in one run, keyed by Transfermarkt id.

    One run for all teams rather than one per fixture: the actor bills per
    player row, and two teams in the same round share no players but do share
    the run's start-up cost.
    """
    token = token or os.environ["APIFY_TOKEN"]
    items = _post({
        "startUrls": [SQUAD_URL.format(i) for i in transfermarkt_ids],
        "recordType": "club", "language": "com",
        "includeClubSquad": True, "includeInjuries": with_injuries,
        "includeMarketValueHistory": False, "includeTransferHistory": False,
        "includeAchievements": False, "maxResults": 0,
    }, token, timeout)

    squads, totals = {}, {}
    for item in items:
        source = item.get("sourceUrl") or ""
        team_id = source.rsplit("verein/", 1)[-1].split("/")[0] if "verein/" in source else None
        if team_id is None:
            continue
        if item.get("marketValueEur") is not None:
            squads.setdefault(team_id, []).append(item)
        elif item.get("squadMarketValueTotalEur"):
            # The club summary row the run emits alongside the players; kept
            # only to check the player rows add up to what the page states.
            totals[team_id] = int(item["squadMarketValueTotalEur"])

    for team_id, players in squads.items():
        published = totals.get(team_id)
        if not published:
            continue
        parsed = sum(int(p.get("marketValueEur") or 0) for p in players)
        if abs(parsed - published) / published > TOLERANCE:
            raise RuntimeError(
                f"squad {team_id}: player rows add to {parsed/1e6:.0f}m against a "
                f"published {published/1e6:.0f}m - the fetch is incomplete")
    missing = [str(i) for i in transfermarkt_ids if str(i) not in squads]
    if missing:
        raise RuntimeError(f"no squad returned for {', '.join(missing)}")
    return squads


def is_competition_bound(record: dict) -> bool:
    name = (record.get("name") or "").lower()
    return any(marker in name for marker in COMPETITION_BOUND_MARKERS)


def _parse(value) -> Optional[date]:
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value)[:10]).date()
    except ValueError:
        return None


def covers(record: dict, as_of: date) -> bool:
    """Whether the record is running on the given day.

    An open-ended record counts from its start onwards. One without a start
    cannot be placed in time and is ignored rather than assumed current.
    """
    start, end = _parse(record.get("start")), _parse(record.get("end"))
    if start is None or start > as_of:
        return False
    return end is None or end >= as_of


def active_absences(player: dict, as_of: date, competition) -> list:
    """Records that keep this player out of a match in this competition.

    A ban or a registration gap is only binding where it was issued. Dropping
    that test marked four Dortmund players out of a league fixture over a
    DFB-Pokal red card and three Champions League squad registrations, none
    of which stops anyone playing in the Bundesliga.
    """
    out = []
    for record in (player.get("injuries") or player.get("absences") or []):
        if not covers(record, as_of):
            continue
        if is_competition_bound(record):
            if record.get("competitionId") != competition.transfermarkt_code:
                continue
        out.append(record)
    return out


def resolve_names(players: list, names) -> tuple:
    """Match reported names against the squad; report what did not match.

    The unmatched list is the point. The research agent has produced absences
    for players who do not exist, and a name the squad has never heard of is
    the cheapest way to catch that before it reaches a log.
    """
    index = {p["name"].casefold(): p for p in players if p.get("name")}
    matched, unmatched = [], []
    for name in names:
        player = index.get((name or "").casefold())
        if player:
            matched.append(player)
            continue
        # Surname-only reports are common and usually unambiguous.
        surname = (name or "").split()[-1].casefold() if name else ""
        hits = [p for key, p in index.items() if surname and key.endswith(surname)]
        if len(hits) == 1:
            matched.append(hits[0])
        else:
            unmatched.append(name)
    return matched, unmatched


def summarise(players: list, competition, absent_names=(),
              as_of: Optional[date] = None) -> dict:
    """Turn a squad into the quantities a model could use.

    Nothing here is a verdict on the match. Each figure refines the squad
    value the model already consumes, which is the only way new information
    can enter without simply casting another vote.

    Absences come from the injury records where the competition has them, and
    from the research agent's names where it does not - see competitions.py.
    Both are counted, since a club player can also withdraw after the list.
    """
    as_of = as_of or date.today()
    out_by_id, reasons = {}, {}
    if competition.has_injury_page:
        for player in players:
            active = active_absences(player, as_of, competition)
            if active:
                out_by_id[player["id"]] = player
                reasons[player["id"]] = active[0].get("name")

    named, unmatched = resolve_names(players, absent_names)
    for player in named:
        out_by_id.setdefault(player["id"], player)
        reasons.setdefault(player["id"], "reported withdrawal")

    absent = list(out_by_id.values())
    available = [p for p in players if p["id"] not in out_by_id]

    def total(group):
        return sum(int(p.get("marketValueEur") or 0) for p in group)

    squad_value, available_value = total(players), total(available)
    top11 = sorted(available, key=lambda p: -(p.get("marketValueEur") or 0))[:11]
    keepers = [p for p in available if (p.get("positionName") or "") == "Goalkeeper"]
    return {
        "squad_size": len(players),
        "squad_value_eur": squad_value,
        "available_value_eur": available_value,
        # The headline correction: what share of the squad's worth is out.
        "absent_value_share": round(1 - available_value / squad_value, 4) if squad_value else None,
        "absent_players": [{"name": p.get("name"), "value_eur": p.get("marketValueEur"),
                            "reason": reasons.get(p["id"])} for p in absent],
        "names_not_in_squad": unmatched,
        "top11_value_eur": total(top11),
        "goalkeeper_value_eur": max((int(p.get("marketValueEur") or 0) for p in keepers), default=0),
        # A national list far above the usual 25-29 is the wider pool, not a
        # call-up, and its value overstates who can actually play.
        "is_pool_not_callup": competition.squad_is_callup and len(players) > 32,
        "as_of": as_of.isoformat(),
    }


def available_squad_values(teams, registry, competition, as_of=None, token=None):
    """Priced strength of the squads actually named, keyed by team name.

    This is the figure the model should use for one fixture instead of the
    nation's standing value. Germany is worth 1.30bn at full strength; if the
    squad named for a given window is worth 800m, the stored number describes
    a team that is not playing.

    registry maps team name to Transfermarkt id (data/team_registry.csv).
    Teams without an id are simply absent from the result, and the caller
    falls back to the stored value for them - a partial correction is still
    better than none, and pretending otherwise would mean discarding a known
    squad because its opponent is unknown.
    """
    wanted = {t: registry[t] for t in teams if t in registry}
    if not wanted:
        return {}
    squads = fetch_squads(wanted.values(), with_injuries=competition.has_injury_page, token=token)
    values = {}
    for team, team_id in wanted.items():
        players = squads.get(str(team_id))
        if not players:
            continue
        summary = summarise(players, competition, as_of=as_of)
        # A pool listing is not a call-up; its total would overstate who can
        # play, so the stored national figure stays in charge for that side.
        if summary["is_pool_not_callup"] or not summary["available_value_eur"]:
            continue
        values[team] = summary["available_value_eur"]
    return values
