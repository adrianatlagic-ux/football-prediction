"""What differs between competitions when reading squads.

The pipeline around this - fetch the squad, price the absences, ask the
research agent for what no table holds, log it before kickoff - is identical
everywhere. Only three things actually vary, and all three are plain facts
about how Transfermarkt organises its data rather than modelling choices:

Whether the squad list is a call-up. A national side names 25 to 29 players
for a window, and an injured player is simply not named, so the list already
encodes availability. A club squad is a standing roster: the injured are
still on it, and availability has to be looked up separately.

Whether an injury page exists. Transfermarkt keeps suspension and injury
records against clubs, not against national teams - /sperrenundverletzungen/
returns entries for Bayern and Real Madrid and nothing at all for Germany.
So the club path can read absences deterministically; the national path
cannot and has to ask the research agent, whose answers are then checked
against the squad.

Which competition an absence belongs to. This one is easy to get wrong and
expensive when you do. A first rehearsal marked four Dortmund players out of
a Bundesliga fixture: one was serving a DFB-Pokal red card, and three simply
were not registered for the Champions League squad. All four were free to
play in the league. Records carry the competition that issued them, so a ban
or a registration gap only counts when that competition is the one being
played. Injuries carry no competition and always count.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

TM = "https://www.transfermarkt.com/x/startseite/wettbewerb/{}"


@dataclass(frozen=True)
class Competition:
    key: str
    label: str
    # Where the team registry comes from. Clubs: a Transfermarkt competition
    # page the Apify actor understands. National teams: None, because the
    # actor rejects the participant-page URL shape, so the registry is built
    # by scripts/fetch_national_market_values.py instead.
    registry_url: Optional[str]
    squad_is_callup: bool
    has_injury_page: bool
    # Transfermarkt's own code for this competition, matched against the
    # competitionId on a suspension or eligibility record. None for national
    # teams: their records all come from club competitions and so never apply.
    transfermarkt_code: Optional[str]
    international: bool = False

    @property
    def needs_research_for_absences(self) -> bool:
        """True where no table lists who is missing, so we must ask and verify."""
        return not self.has_injury_page


COMPETITIONS = {
    c.key: c for c in [
        Competition("nations_league", "UEFA Nations League", None,
                    squad_is_callup=True, has_injury_page=False,
                    transfermarkt_code=None, international=True),
        Competition("bundesliga", "Bundesliga", TM.format("L1"),
                    squad_is_callup=False, has_injury_page=True,
                    transfermarkt_code="L1"),
        Competition("bundesliga2", "2. Bundesliga", TM.format("L2"),
                    squad_is_callup=False, has_injury_page=True,
                    transfermarkt_code="L2"),
        Competition("premier_league", "Premier League", TM.format("GB1"),
                    squad_is_callup=False, has_injury_page=True,
                    transfermarkt_code="GB1"),
        Competition("la_liga", "LaLiga", TM.format("ES1"),
                    squad_is_callup=False, has_injury_page=True,
                    transfermarkt_code="ES1"),
        Competition("serie_a", "Serie A", TM.format("IT1"),
                    squad_is_callup=False, has_injury_page=True,
                    transfermarkt_code="IT1"),
        Competition("ligue_1", "Ligue 1", TM.format("FR1"),
                    squad_is_callup=False, has_injury_page=True,
                    transfermarkt_code="FR1"),
        Competition("champions_league", "Champions League", TM.format("CL"),
                    squad_is_callup=False, has_injury_page=True,
                    transfermarkt_code="CL"),
    ]
}


def get(key: str) -> Competition:
    try:
        return COMPETITIONS[key]
    except KeyError:
        raise SystemExit(
            f"unknown competition {key!r}; known: {', '.join(sorted(COMPETITIONS))}")
