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
import re
import urllib.request
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

from src import apify_budget

ACTOR = "solidcode~transfermarkt-scraper"
ENDPOINT = "https://api.apify.com/v2/acts/{}/run-sync-get-dataset-items?token={}"
SQUAD_URL = "https://www.transfermarkt.com/x/startseite/verein/{}"
ABSENCE_URL = "https://www.transfermarkt.com/x/sperrenundverletzungen/verein/{}"

# Records that belong to the competition that issued them: bans, and squad
# registration gaps ("No eligibility" - not named in a Champions League squad,
# say). Everything else, injuries above all, travels with the player.
COMPETITION_BOUND_MARKERS = ("suspension", "ban", "sperre", "suspended", "eligibility")
# Squads with their player values are kept this long before Apify is paid
# again. Values move when Transfermarkt updates them, every few weeks, and a
# national call-up stands for the whole international window. What does change
# by the hour - who is injured or banned - comes from fetch_absences, which is
# read fresh for every match and costs nothing.
SQUAD_CACHE_DIR = Path(os.getenv("SQUAD_CACHE_DIR",
                                 Path(__file__).resolve().parents[1] / "data" / "squad_cache"))
CLUB_SQUAD_TTL = timedelta(days=7)
NATIONAL_SQUAD_TTL = timedelta(days=10)
# All that summarise() reads from a player row.
_KEPT_FIELDS = ("id", "name", "marketValueEur", "positionName")

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


def fetch_absences(transfermarkt_id: str) -> dict:
    """Current injuries and bans for a club, keyed by Transfermarkt player id.

    The squad feed does not carry these. Its "injuries" field returns card
    suspensions and registration gaps only - three Bundesliga clubs came back
    with no injured players at all, which is not what the club pages say. This
    is the page that does: name, reason, and the dates either side of it.

    Only clubs have such a page; national teams return an empty one, because
    Transfermarkt records injuries against the club a player belongs to.
    """
    with urllib.request.urlopen(ABSENCE_URL.format(transfermarkt_id), timeout=30) as response:
        body = response.read().decode("utf-8", "ignore")
    out = {}
    for match in re.finditer(r"/profil/spieler/(\d+)", body):
        player_id = match.group(1)
        if player_id in out:
            continue
        # Reason and dates follow the player block as plain cells.
        window = re.sub(r"<[^>]+>", "\x00", body[match.end():match.end() + 1600])
        cells = [c.strip() for c in window.split("\x00") if c.strip()]
        # The reason sits immediately before the first date: the row runs
        # name, position, age, reason, from, to. Anchoring on the date keeps
        # this working when a cell is empty rather than counting columns.
        first_date = next((i for i, c in enumerate(cells)
                           if re.fullmatch(r"\d{2}/\d{2}/\d{4}", c)), None)
        dates = [c for c in cells if re.fullmatch(r"\d{2}/\d{2}/\d{4}", c)]
        reason = cells[first_date - 1] if first_date else None
        out[player_id] = {
            "name": reason,
            # No competition is attached to these. An injury applies
            # everywhere, and a ban whose competition we cannot read is left
            # to the competition test, which will not match and so will not
            # rule anyone out on a guess.
            "competitionId": None,
            "start": _to_iso(dates[0]) if dates else None,
            "end": _to_iso(dates[1]) if len(dates) > 1 else None,
        }
    return out


def _to_iso(value: str):
    try:
        day, month, year = value.split("/")
        return f"{year}-{month}-{day}"
    except (ValueError, AttributeError):
        return None


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


SQUAD_RUN_COST_USD = 0.05


def cached_squads(transfermarkt_ids, ttl: timedelta, token: Optional[str] = None,
                  now: Optional[datetime] = None) -> dict:
    """Squads keyed by Transfermarkt id, from the cache where it is young enough.

    Only the stale or missing ones go to Apify, still in a single run.
    """
    now = now or datetime.now(timezone.utc)
    out, stale = {}, []
    for team_id in (str(i) for i in transfermarkt_ids):
        try:
            cached = json.loads((SQUAD_CACHE_DIR / f"{team_id}.json").read_text(encoding="utf-8"))
            if now - datetime.fromisoformat(cached["fetched_at"]) < ttl:
                out[team_id] = cached["players"]
                continue
        except (OSError, ValueError, KeyError):
            pass
        stale.append(team_id)
    # About 40 player rows a team at $0.001 each; past the account's cap the
    # stale teams are left out and the line-up job tries again later.
    if stale and not apify_budget.allows(len(stale) * SQUAD_RUN_COST_USD, token):
        stale = []
    if stale:
        fetched = fetch_squads(stale, with_injuries=False, token=token)
        apify_budget.note_spend(len(stale) * SQUAD_RUN_COST_USD)
        SQUAD_CACHE_DIR.mkdir(parents=True, exist_ok=True)
        for team_id, players in fetched.items():
            slim = [{k: p.get(k) for k in _KEPT_FIELDS} for p in players]
            (SQUAD_CACHE_DIR / f"{team_id}.json").write_text(
                json.dumps({"fetched_at": now.isoformat(), "players": slim}, ensure_ascii=False) + "\n",
                encoding="utf-8")
            out[team_id] = slim
    return out


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
    ttl = NATIONAL_SQUAD_TTL if competition.international else CLUB_SQUAD_TTL
    squads = cached_squads(wanted.values(), ttl, token=token)
    values = {}
    for team, team_id in wanted.items():
        players = squads.get(str(team_id))
        if not players:
            continue
        if competition.has_injury_page:
            # The squad feed carries no injuries - see fetch_absences - so the
            # club's own absence page is read and attached here.
            try:
                absences = fetch_absences(team_id)
            except Exception:
                absences = {}
            players = [{**p, "injuries": [absences[str(p["id"])]] if str(p.get("id")) in absences else []}
                       for p in players]
        summary = summarise(players, competition, as_of=as_of)
        # A pool listing is not a call-up; its total would overstate who can
        # play, so the stored national figure stays in charge for that side.
        if summary["is_pool_not_callup"] or not summary["available_value_eur"]:
            continue
        values[team] = summary["available_value_eur"]
    return values
