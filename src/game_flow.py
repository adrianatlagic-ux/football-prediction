"""
Spielverlauf-Vorhersage basierend auf xG-Werten (Dixon-Coles Poisson).

Modelliert:
- Torwahrscheinlichkeit pro 15-Minuten-Fenster
- Erstes Tor (wer, wann)
- Halbzeitstand-Verteilung
- Comeback-Wahrscheinlichkeit
- Dramatik-Index (späte Tore)
- Matchtyp (offen / taktisch / einseitig)
- Wahrscheinlichste Spielgeschichte
"""

from __future__ import annotations
import hashlib
import numpy as np
from scipy.stats import poisson

# Empirische Torverteilung über 90 Minuten (aus Analyse tausender Länderspiele)
# Quelle: typische Verteilung in Literatur, normiert auf 6 x 15-Min-Fenster
GOAL_TIME_DIST = np.array([
    0.135,  # 1-15 min  — langsamer Start
    0.155,  # 16-30 min — etwas mehr Aktivität
    0.180,  # 31-45 min — Druck vor Halbzeit
    0.145,  # 46-60 min — Abwarten nach Pause
    0.185,  # 61-75 min — Hochphase
    0.200,  # 76-90 min — Schlussspurt, Nachspielzeit
])
GOAL_TIME_LABELS = ["1-15'", "16-30'", "31-45'", "46-60'", "61-75'", "76-90'"]
FIRST_HALF_SHARE = GOAL_TIME_DIST[:3].sum()   # ~0.47
SECOND_HALF_SHARE = GOAL_TIME_DIST[3:].sum()  # ~0.53


def predict_game_flow(
    home_xg: float, away_xg: float, home_team: str, away_team: str,
    final_score: str | None = None,
) -> dict:
    total_xg = home_xg + away_xg

    # 1. Torverteilung pro 15-Min-Fenster
    home_per_window = home_xg * GOAL_TIME_DIST
    away_per_window = away_xg * GOAL_TIME_DIST

    # 2. Halbzeit-xG
    home_xg_h1 = home_xg * FIRST_HALF_SHARE
    away_xg_h1 = away_xg * FIRST_HALF_SHARE
    home_xg_h2 = home_xg * SECOND_HALF_SHARE
    away_xg_h2 = away_xg * SECOND_HALF_SHARE

    # 3. Erstes Tor
    p_no_goal_90 = poisson.pmf(0, home_xg) * poisson.pmf(0, away_xg)
    p_home_first = home_xg / (home_xg + away_xg) * (1 - p_no_goal_90)
    p_away_first = away_xg / (home_xg + away_xg) * (1 - p_no_goal_90)
    p_no_goals   = p_no_goal_90

    # Minute des ersten Tors (erwartete Minute, bedingt auf mind. 1 Tor)
    expected_first_goal_min = _expected_first_goal_minute(total_xg)

    # 4. Halbzeitstand-Wahrscheinlichkeiten (Top 5)
    ht_probs = _score_distribution(home_xg_h1, away_xg_h1, max_goals=4)
    top_ht = sorted(ht_probs.items(), key=lambda x: -x[1])[:5]

    # 5. Comeback-Wahrscheinlichkeit
    p_home_comeback = _comeback_prob(home_xg, away_xg)
    p_away_comeback = _comeback_prob(away_xg, home_xg)

    # 6. Dramatik (mind. 1 Tor nach der 75. Minute)
    goals_last_15_xg = total_xg * GOAL_TIME_DIST[5]
    p_late_goal = 1 - poisson.pmf(0, goals_last_15_xg)

    # 7. Matchtyp
    match_type, match_desc = _classify_match(home_xg, away_xg)

    # 8. Spielgeschichten (wahrscheinlichste Szenarien)
    stories = _build_stories(home_team, away_team, home_xg, away_xg,
                              home_xg_h1, away_xg_h1, home_xg_h2, away_xg_h2)

    # 9. Dominanz-Index (-1 = Away dominiert, +1 = Home dominiert)
    dominance = (home_xg - away_xg) / max(total_xg, 0.01)

    # 10. Geschätzte Spielstatistiken (Possession, Schüsse, etc.)
    predicted_stats = _predicted_match_stats(home_xg, away_xg, dominance)

    # 11. Match-Ticker: Tor-für-Tor-Verlauf, konsistent mit Endstand UND Halbzeitstand
    match_ticker = _build_match_ticker(
        home_team, away_team, final_score,
        home_xg_h1, away_xg_h1, home_xg_h2, away_xg_h2,
    )

    return {
        "match_type": match_type,
        "match_description": match_desc,
        "dominance_index": round(dominance, 2),
        "total_xg": round(total_xg, 2),
        "first_goal": {
            f"{home_team}_scores_first": round(p_home_first, 3),
            f"{away_team}_scores_first": round(p_away_first, 3),
            "no_goals":                  round(p_no_goals, 3),
            "expected_minute":           expected_first_goal_min,
        },
        "halftime_xg": {
            home_team: round(home_xg_h1, 2),
            away_team: round(away_xg_h1, 2),
        },
        "top_halftime_scores": [
            {"score": f"{h}:{a}", "probability": round(p, 3)}
            for (h, a), p in top_ht
        ],
        "goal_timing": {
            label: {
                home_team: round(float(h), 3),
                away_team: round(float(a), 3),
            }
            for label, h, a in zip(GOAL_TIME_LABELS, home_per_window, away_per_window)
        },
        "comeback_probability": {
            home_team: round(p_home_comeback, 3),
            away_team: round(p_away_comeback, 3),
        },
        "late_drama_probability": round(p_late_goal, 3),
        "match_stories": stories,
        "predicted_stats": predicted_stats,
        "match_ticker": match_ticker,
    }


def _seeded_rng(*parts: object) -> np.random.Generator:
    """Deterministischer RNG aus den Spiel-Eckdaten (Teams + Endstand).

    Gleiche Eingaben -> gleicher Ticker (wichtig für den Predictions-Cache),
    aber unterschiedliche Spiele/Ergebnisse erzeugen unterschiedliche,
    realistisch wirkende Minutenverteilungen statt eines starren Schemas.
    """
    seed_str = "-".join(str(p) for p in parts)
    seed = int(hashlib.md5(seed_str.encode()).hexdigest()[:8], 16)
    return np.random.default_rng(seed)


def _minute_weights(windows: list[int]) -> np.ndarray:
    """Pro-Minute-Gewichte für eine Halbzeit, abgeleitet aus GOAL_TIME_DIST."""
    weights = np.repeat(GOAL_TIME_DIST[windows], 15)
    return weights / weights.sum()


def _sample_minutes(
    n: int, minute_range: range, windows: list[int],
    exclude: set[int], rng: np.random.Generator,
) -> list[int]:
    """Zieht `n` verschiedene Minuten aus `minute_range`, gewichtet nach
    GOAL_TIME_DIST und ohne die in `exclude` enthaltenen Minuten."""
    if n <= 0:
        return []
    minutes = np.array(list(minute_range))
    weights = _minute_weights(windows)

    mask = np.array([m not in exclude for m in minutes])
    if mask.sum() < n:
        mask[:] = True  # Fallback falls zu viele Minuten belegt sind

    minutes, weights = minutes[mask], weights[mask]
    weights = weights / weights.sum()

    n = min(n, len(minutes))
    chosen = rng.choice(minutes, size=n, replace=False, p=weights)
    return sorted(int(m) for m in chosen)


def _assign_goal_teams(
    minutes: list[int], home_goals: int, away_goals: int,
    home: str, away: str, rng: np.random.Generator,
) -> list[tuple[int, str]]:
    """Ordnet den gezogenen Tor-Minuten zufällig die Teams zu (Anzahl bleibt fix)."""
    labels = [home] * home_goals + [away] * away_goals
    rng.shuffle(labels)
    return list(zip(minutes, labels))


def _score_at(minute: int, goal_events: list[tuple[int, str]], home: str, away: str) -> str:
    h = sum(1 for m, t in goal_events if m <= minute and t == home)
    a = sum(1 for m, t in goal_events if m <= minute and t == away)
    return f"{h}:{a}"


def _build_match_ticker(
    home: str, away: str, final_score: str | None,
    home_xg_h1: float, away_xg_h1: float, home_xg_h2: float, away_xg_h2: float,
) -> list[dict]:
    """Baut einen Minute-für-Minute-Ticker (auf Englisch), dessen Halbzeit- UND
    Endstand exakt zur Modellvorhersage passen (score_prediction + top_halftime_scores).

    Tor- und Chancen-Minuten werden per gewichtetem Zufall (seedbasiert auf
    Teams + Endstand) gezogen, sodass sie sich an GOAL_TIME_DIST orientieren,
    sich nicht überlappen und zwischen Spielen variieren.
    """
    if not final_score:
        return []

    try:
        home_goals, away_goals = (int(x) for x in final_score.split(":"))
    except ValueError:
        return []

    # Wahrscheinlichsten Halbzeitstand wählen: P(HT=(h,a) | FT) ∝ P(H1=(h,a)) * P(H2=(FT-h, FT-a)).
    # Beide Halbzeiten sind im Modell unabhängige Poisson-Verteilungen, daher reicht
    # es, über alle mit dem Endstand kompatiblen Aufteilungen die wahrscheinlichste
    # zu wählen - statt einfach den global wahrscheinlichsten HT-Stand (meist 0:0)
    # zu nehmen, der fast nie 0:0-an-0:0-vorbei-Tore in H2 zulässt.
    max_goals = max(home_goals, away_goals, 4)
    h1_probs = _score_distribution(home_xg_h1, away_xg_h1, max_goals=max_goals)
    h2_probs = _score_distribution(home_xg_h2, away_xg_h2, max_goals=max_goals)

    ht_home, ht_away, best_p = 0, 0, -1.0
    for h in range(home_goals + 1):
        for a in range(away_goals + 1):
            p = h1_probs.get((h, a), 0.0) * h2_probs.get((home_goals - h, away_goals - a), 0.0)
            if p > best_p:
                best_p, ht_home, ht_away = p, h, a

    h1_home_goals, h1_away_goals = ht_home, ht_away
    h2_home_goals, h2_away_goals = home_goals - ht_home, away_goals - ht_away

    rng = _seeded_rng(home, away, final_score)

    h1_range, h2_range = range(1, 46), range(46, 91)
    h1_windows, h2_windows = [0, 1, 2], [3, 4, 5]

    h1_minutes = _sample_minutes(h1_home_goals + h1_away_goals, h1_range, h1_windows, set(), rng)
    h2_minutes = _sample_minutes(h2_home_goals + h2_away_goals, h2_range, h2_windows, set(), rng)

    goal_events = (
        _assign_goal_teams(h1_minutes, h1_home_goals, h1_away_goals, home, away, rng) +
        _assign_goal_teams(h2_minutes, h2_home_goals, h2_away_goals, home, away, rng)
    )
    goal_events.sort(key=lambda e: e[0])
    used_minutes = {m for m, _ in goal_events}

    events: list[dict] = [{
        "minute": 1,
        "type": "kickoff",
        "team": None,
        "headline": "Kickoff!",
        "description": f"The match between {home} and {away} is underway.",
        "score_after": "0:0",
    }]

    h_score, a_score = 0, 0
    for minute, team in goal_events:
        if team == home:
            h_score += 1
        else:
            a_score += 1
        events.append({
            "minute": minute,
            "type": "goal",
            "team": team,
            "headline": f"GOAL! {team}!",
            "description": f"{team} score to make it {h_score}:{a_score}.",
            "score_after": f"{h_score}:{a_score}",
        })

    # "Big chance"-Highlights: Anzahl richtet sich nach dem erwarteten Tempo
    # des Spiels (Gesamt-xG), jeweils auf beide Halbzeiten verteilt und einem
    # Team zufällig zugeordnet (gewichtet nach dessen xG-Anteil in der Halbzeit).
    for minute_range, windows, h_xg, a_xg in (
        (h1_range, h1_windows, home_xg_h1, away_xg_h1),
        (h2_range, h2_windows, home_xg_h2, away_xg_h2),
    ):
        n_chances = int(np.clip(round((h_xg + a_xg) / 0.9), 1, 2))
        chance_minutes = _sample_minutes(n_chances, minute_range, windows, used_minutes, rng)
        used_minutes.update(chance_minutes)

        total_xg = h_xg + a_xg
        p_home = h_xg / total_xg if total_xg > 0 else 0.5
        for minute in chance_minutes:
            team = home if rng.random() < p_home else away
            events.append({
                "minute": minute,
                "type": "chance",
                "team": team,
                "headline": f"Big chance for {team}!",
                "description": f"{team} create a great opportunity but fail to convert.",
                "score_after": _score_at(minute, goal_events, home, away),
            })

    events.append({
        "minute": 45,
        "type": "halftime",
        "team": None,
        "headline": "Half-time",
        "description": f"The teams go into the break at {ht_home}:{ht_away}.",
        "score_after": f"{ht_home}:{ht_away}",
    })

    events.append({
        "minute": 90,
        "type": "fulltime",
        "team": None,
        "headline": "Full-time",
        "description": f"The final score finishes {final_score}.",
        "score_after": final_score,
    })

    # Sortieren: alles vor Minute 45 zuerst, Halbzeit-Event genau bei 45,
    # danach alles bis 90, Endstand-Event zuletzt.
    def sort_key(e: dict) -> tuple:
        order = {"kickoff": 0, "goal": 1, "chance": 1, "halftime": 2, "fulltime": 4}
        return (e["minute"], order.get(e["type"], 3))

    events.sort(key=sort_key)
    return events


def _differentiate(home_raw: float, away_raw: float) -> tuple[int, int]:
    """Rundet beide Werte, bricht aber Gleichstände auf, wenn die rohen
    (ungerundeten) Werte sich unterscheiden - sonst führen knapp
    unterschiedliche xG-Werte (z.B. 1.34 vs 1.38) oft zu identischen
    gerundeten Stats, was für den Leser unrealistisch wirkt.
    """
    home, away = round(home_raw), round(away_raw)
    if home == away and home_raw != away_raw:
        if home_raw > away_raw:
            home += 1
        else:
            away += 1
    return home, away


def _predicted_match_stats(home_xg: float, away_xg: float, dominance: float) -> dict:
    """Schätzt typische Spielstatistiken (Ballbesitz, Schüsse, Pässe) aus xG/Dominanz.

    Heuristische Ableitung für die Anzeige — kein eigenständiges ML-Modell,
    sondern eine plausible Skalierung passend zu den xG-Werten. `_differentiate`
    sorgt dafür, dass selbst sehr ausgeglichene Spiele (xG-Unterschied < 0.1)
    nicht auf identische Stats für beide Teams runden.
    """
    possession_home = round(50 + dominance * 18)
    possession_home = max(28, min(72, possession_home))
    if possession_home == 50 and dominance != 0:
        possession_home += 1 if dominance > 0 else -1
    possession_away = 100 - possession_home

    shots_home, shots_away = _differentiate(home_xg * 6.5 + 4, away_xg * 6.5 + 4)
    shots_home, shots_away = max(1, shots_home), max(1, shots_away)

    sot_home, sot_away = _differentiate(home_xg * 2.8 + 1, away_xg * 2.8 + 1)
    sot_home = max(0, min(shots_home, sot_home))
    sot_away = max(0, min(shots_away, sot_away))

    corners_home, corners_away = _differentiate(home_xg * 2.5 + 2, away_xg * 2.5 + 2)
    corners_home, corners_away = max(0, corners_home), max(0, corners_away)

    passes_home = round(possession_home * 5.2)
    passes_away = round(possession_away * 5.2)

    return {
        "possession": {"home": possession_home, "away": possession_away},
        "shots": {"home": shots_home, "away": shots_away},
        "shots_on_target": {"home": sot_home, "away": sot_away},
        "corners": {"home": corners_home, "away": corners_away},
        "passes": {"home": passes_home, "away": passes_away},
    }


def _expected_first_goal_minute(total_xg: float) -> int:
    """Erwartete Minute des ersten Tors (bedingt auf mind. 1 Tor)."""
    if total_xg <= 0:
        return 90
    # Rate pro Minute = total_xg / 90
    rate = total_xg / 90
    # E[X | X < 90] für Exponentialverteilung
    expected = 1 / rate
    return int(min(expected, 85))


def _score_distribution(home_xg: float, away_xg: float, max_goals: int = 4) -> dict:
    dist = {}
    for h in range(max_goals + 1):
        for a in range(max_goals + 1):
            p = poisson.pmf(h, home_xg) * poisson.pmf(a, away_xg)
            dist[(h, a)] = float(p)
    total = sum(dist.values())
    return {k: v / total for k, v in dist.items()}


def _comeback_prob(scorer_xg: float, conceder_xg: float) -> float:
    """P(Team A kommt von hinten und gewinnt noch)."""
    # P(Team B führt nach HT) * P(Team A dreht es noch)
    p_trailing_ht = sum(
        poisson.pmf(h, scorer_xg * FIRST_HALF_SHARE) *
        poisson.pmf(a, conceder_xg * FIRST_HALF_SHARE)
        for h in range(5) for a in range(1, 5) if a > h
    )
    p_win_2h = sum(
        poisson.pmf(h2, scorer_xg * SECOND_HALF_SHARE) *
        poisson.pmf(a2, conceder_xg * SECOND_HALF_SHARE)
        for h2 in range(1, 6) for a2 in range(h2) if h2 > a2 + 1
    )
    return float(p_trailing_ht * p_win_2h)


def _classify_match(home_xg: float, away_xg: float) -> tuple[str, str]:
    total = home_xg + away_xg
    diff  = abs(home_xg - away_xg)

    if total >= 3.5:
        mtype = "Goal Fest"
        desc  = "A very open game with plenty of chances expected"
    elif total >= 2.5:
        if diff >= 1.2:
            mtype = "One-Sided"
            desc  = "One team is expected to dominate clearly"
        else:
            mtype = "Balanced & Open"
            desc  = "Both teams play attacking football at an even level"
    elif total >= 1.5:
        if diff >= 0.8:
            mtype = "Controlled"
            desc  = "The favorite controls the game against little resistance"
        else:
            mtype = "Tactically Balanced"
            desc  = "A tight game where goals will make the difference"
    else:
        mtype = "Defensive Battle"
        desc  = "Few chances expected, a single goal could be decisive"

    return mtype, desc


def _build_stories(
    home: str, away: str,
    home_xg: float, away_xg: float,
    home_xg_h1: float, away_xg_h1: float,
    home_xg_h2: float, away_xg_h2: float,
) -> list[dict]:
    stories = []

    # Scoreline-Verteilung für beide Hälften
    ht = _score_distribution(home_xg_h1, away_xg_h1, max_goals=3)
    ft = _score_distribution(home_xg, away_xg, max_goals=5)

    # Geschichte 1: Spiel ist schon früh entschieden
    p_home_2_0_ht = ht.get((2, 0), 0)
    p_away_2_0_ht = ht.get((0, 2), 0)
    if p_home_2_0_ht > 0.04:
        stories.append({
            "szenario": f"{home} dominiert früh",
            "beschreibung": f"{home} geht 2:0 in Halbzeit 1, kontrolliert dann",
            "wahrscheinlichkeit": round(p_home_2_0_ht, 3),
        })
    if p_away_2_0_ht > 0.04:
        stories.append({
            "szenario": f"{away} dominiert früh",
            "beschreibung": f"{away} geht 0:2 in Halbzeit 1, kontrolliert dann",
            "wahrscheinlichkeit": round(p_away_2_0_ht, 3),
        })

    # Geschichte 2: Torloser Krimi — Entscheidung fällt erst spät
    p_0_0_ht = ht.get((0, 0), 0)
    p_0_0_ft = ft.get((0, 0), 0)
    p_late_decider = p_0_0_ht * (1 - p_0_0_ft / max(p_0_0_ht, 0.01))
    if p_late_decider > 0.05:
        stories.append({
            "szenario": "Torloser Krimi",
            "beschreibung": "0:0 zur Halbzeit — Entscheidung fällt in der 2. Hälfte",
            "wahrscheinlichkeit": round(p_late_decider, 3),
        })

    # Geschichte 3: Comeback
    p_home_comeback = _comeback_prob(home_xg, away_xg)
    p_away_comeback = _comeback_prob(away_xg, home_xg)
    if p_home_comeback > 0.04:
        stories.append({
            "szenario": f"{home} dreht es noch",
            "beschreibung": f"{home} liegt zur Halbzeit zurück, dreht das Spiel in H2",
            "wahrscheinlichkeit": round(p_home_comeback, 3),
        })
    if p_away_comeback > 0.04:
        stories.append({
            "szenario": f"{away} dreht es noch",
            "beschreibung": f"{away} liegt zur Halbzeit zurück, dreht das Spiel in H2",
            "wahrscheinlichkeit": round(p_away_comeback, 3),
        })

    # Geschichte 4: Klassisches 1:0 — Verteidigt bis zum Schluss
    p_1_0 = ft.get((1, 0), 0)
    p_0_1 = ft.get((0, 1), 0)
    dominant = home if home_xg > away_xg else away
    p_dominant_10 = p_1_0 if home_xg > away_xg else p_0_1
    if p_dominant_10 > 0.08:
        stories.append({
            "szenario": f"Knappes 1:0",
            "beschreibung": f"{dominant} trifft einmal und verteidigt das Ergebnis",
            "wahrscheinlichkeit": round(p_dominant_10, 3),
        })

    # Geschichte 5: Ausgeglichenes Duell mit Unentschieden
    p_draw = sum(ft.get((i, i), 0) for i in range(4))
    if p_draw > 0.2:
        most_likely_draw = max([(ft.get((i, i), 0), f"{i}:{i}") for i in range(4)])[1]
        stories.append({
            "szenario": "Ausgeglichenes Unentschieden",
            "beschreibung": f"Beide Teams auf Augenhöhe, wahrscheinlichstes Draw: {most_likely_draw}",
            "wahrscheinlichkeit": round(p_draw, 3),
        })

    # Sortieren nach Wahrscheinlichkeit
    stories.sort(key=lambda x: -x["wahrscheinlichkeit"])
    return stories[:4]
