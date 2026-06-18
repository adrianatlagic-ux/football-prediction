from __future__ import annotations

import numpy as np
import pandas as pd
from scipy.stats import poisson
from scipy.optimize import minimize_scalar

from .fifa_rankings import get_points

MAX_GOALS = 8

# How strongly the FIFA-points gap between two teams shifts the xG
# towards the stronger side. 0 = no effect, 1 = very strong effect.
RANK_ADJUSTMENT_STRENGTH = 0.6


def _rank_adjustment_factors(home_team: str, away_team: str) -> tuple[float, float]:
    """Shift xG shares towards the team with the higher FIFA points total.

    Historical goal stats alone don't capture the quality gap between, say,
    a top-10 nation and a World Cup debutant whose data mostly comes from
    matches against similarly weak opponents. This rebalances the data-driven
    xG using each team's FIFA ranking points.
    """
    home_points = get_points(home_team)
    away_points = get_points(away_team)
    total = home_points + away_points
    if total <= 0:
        return 1.0, 1.0

    # 0.5 = evenly matched, towards 0/1 = big quality gap
    home_share = home_points / total
    shift = (home_share - 0.5) * 2  # range roughly -1..1

    home_factor = 1 + RANK_ADJUSTMENT_STRENGTH * shift
    away_factor = 1 - RANK_ADJUSTMENT_STRENGTH * shift
    return max(home_factor, 0.2), max(away_factor, 0.2)


def _tau(home_goals: int, away_goals: int, home_xg: float, away_xg: float, rho: float) -> float:
    """Dixon-Coles correction factor for low-scoring results."""
    if home_goals == 0 and away_goals == 0:
        return 1 - home_xg * away_xg * rho
    if home_goals == 1 and away_goals == 0:
        return 1 + away_xg * rho
    if home_goals == 0 and away_goals == 1:
        return 1 + home_xg * rho
    if home_goals == 1 and away_goals == 1:
        return 1 - rho
    return 1.0


def _estimate_rho(df: pd.DataFrame) -> float:
    """Estimate Dixon-Coles rho from historical data via MLE."""
    avg = float(df[["home_goals", "away_goals"]].mean().mean())

    def neg_log_likelihood(rho: float) -> float:
        ll = 0.0
        for _, row in df.iterrows():
            h, a = int(row["home_goals"]), int(row["away_goals"])
            lam = avg
            mu = avg
            t = _tau(h, a, lam, mu, rho)
            if t <= 0:
                return 1e9
            ll += np.log(max(t, 1e-10))
        return -ll

    result = minimize_scalar(neg_log_likelihood, bounds=(-0.5, 0.0), method="bounded")
    return float(result.x)


def compute_betting_markets(
    all_scorelines: list[dict],
    home_team: str,
    away_team: str,
    home_win_prob: float,
    draw_prob: float,
    away_win_prob: float,
) -> dict:
    """Derive common sports-betting markets from the scoreline distribution."""

    def goals(score: str) -> tuple[int, int]:
        h, a = score.split(":")
        return int(h), int(a)

    over_under = []
    for line in (1.5, 2.5, 3.5):
        over = sum(s["probability"] for s in all_scorelines if sum(goals(s["score"])) > line)
        over_under.append({"line": line, "over": round(over, 4), "under": round(1 - over, 4)})

    btts_yes = sum(
        s["probability"] for s in all_scorelines
        if all(g > 0 for g in goals(s["score"]))
    )

    home_2plus = sum(
        s["probability"] for s in all_scorelines
        if (lambda h, a: h - a >= 2)(*goals(s["score"]))
    )
    home_3plus = sum(
        s["probability"] for s in all_scorelines
        if (lambda h, a: h - a >= 3)(*goals(s["score"]))
    )
    away_2plus = sum(
        s["probability"] for s in all_scorelines
        if (lambda h, a: a - h >= 2)(*goals(s["score"]))
    )
    away_3plus = sum(
        s["probability"] for s in all_scorelines
        if (lambda h, a: a - h >= 3)(*goals(s["score"]))
    )

    over_2_5 = over_under[1]["over"]

    if draw_prob >= home_win_prob and draw_prob >= away_win_prob:
        scenario = "A close match — a draw is the single most likely outcome."
    else:
        if home_win_prob >= away_win_prob:
            favorite, fav_prob, margin_2plus = home_team, home_win_prob, home_2plus
        else:
            favorite, fav_prob, margin_2plus = away_team, away_win_prob, away_2plus

        margin_share = margin_2plus / fav_prob if fav_prob > 0 else 0.0
        sentence = f"{favorite} are favored to win"
        if margin_share > 0.55:
            sentence += ", likely by 2+ goals"
        sentence += ", in a high-scoring game." if over_2_5 > 0.55 \
            else ", in a low-scoring game." if over_2_5 < 0.45 \
            else "."
        scenario = sentence

    return {
        "double_chance": {
            "home_or_draw": round(home_win_prob + draw_prob, 4),
            "home_or_away": round(home_win_prob + away_win_prob, 4),
            "draw_or_away": round(draw_prob + away_win_prob, 4),
        },
        "over_under": over_under,
        "btts": {"yes": round(btts_yes, 4), "no": round(1 - btts_yes, 4)},
        "win_margin": {
            "home_1plus": round(home_win_prob, 4),
            "home_2plus": round(home_2plus, 4),
            "home_3plus": round(home_3plus, 4),
            "away_1plus": round(away_win_prob, 4),
            "away_2plus": round(away_2plus, 4),
            "away_3plus": round(away_3plus, 4),
        },
        "scenario": scenario,
    }


RATING_WINDOW_YEARS = 3
RATING_ITERATIONS = 10
RATING_SHRINKAGE_K = 8  # shrinks ratings of teams with few matches towards 1.0


def _compute_team_ratings(df: pd.DataFrame, window_years: int = RATING_WINDOW_YEARS) -> dict[str, tuple[float, float]]:
    """Opponent-strength-adjusted attack/defense ratings.

    Plain "goals scored/conceded per game" overrates teams whose recent
    opponents were weak and underrates teams who mostly played strong
    opponents (e.g. Brazil's tougher schedule vs. Morocco's). This iterates
        attack_i  = goals_scored_by_i  / (league_avg * defense_of_opponents)
        defense_i = goals_conceded_by_i / (league_avg * attack_of_opponents)
    until convergence, so a team's rating reflects results relative to the
    quality of opponents faced - similar to Dixon-Coles team-strength fits.
    Teams with few matches are shrunk towards the neutral rating (1.0).
    """
    cutoff = df["date"].max() - pd.Timedelta(days=365 * window_years)
    recent = df[df["date"] >= cutoff]
    if recent.empty:
        recent = df
    if recent.empty:
        return {}

    league_avg = float(recent[["home_goals", "away_goals"]].mean().mean())
    teams = pd.unique(pd.concat([recent["home_team"], recent["away_team"]]))
    attack = {t: 1.0 for t in teams}
    defense = {t: 1.0 for t in teams}

    matches = list(zip(
        recent["home_team"], recent["away_team"],
        recent["home_goals"].astype(float), recent["away_goals"].astype(float),
    ))
    match_count = {t: 0 for t in teams}
    for h, a, _, _ in matches:
        match_count[h] += 1
        match_count[a] += 1

    for _ in range(RATING_ITERATIONS):
        attack_sums = {t: [0.0, 0.0] for t in teams}
        defense_sums = {t: [0.0, 0.0] for t in teams}

        for h, a, hg, ag in matches:
            attack_sums[h][0] += hg
            attack_sums[h][1] += league_avg * defense[a]
            defense_sums[a][0] += hg
            defense_sums[a][1] += league_avg * attack[h]

            attack_sums[a][0] += ag
            attack_sums[a][1] += league_avg * defense[h]
            defense_sums[h][0] += ag
            defense_sums[h][1] += league_avg * attack[a]

        for t in teams:
            if attack_sums[t][1] > 0:
                attack[t] = attack_sums[t][0] / attack_sums[t][1]
            if defense_sums[t][1] > 0:
                defense[t] = defense_sums[t][0] / defense_sums[t][1]

    ratings = {}
    for t in teams:
        shrink = match_count[t] / (match_count[t] + RATING_SHRINKAGE_K)
        ratings[t] = (
            1.0 + shrink * (attack[t] - 1.0),
            1.0 + shrink * (defense[t] - 1.0),
        )
    return ratings


def _rescale_to_target_result_probs(
    matrix: np.ndarray, target_home: float, target_draw: float, target_away: float
) -> np.ndarray:
    """Rescale a scoreline matrix so its H/D/A sums match the given targets.

    The relative shape within each H/D/A group (which scorelines are more
    or less likely) is preserved; only the overall weight of each group is
    shifted. Used to align the Poisson scoreline distribution with the
    classification model's H/D/A probabilities, so the headline result and
    the detailed scoreline/betting-market breakdown agree with each other.
    """
    rows = matrix.shape[0]
    home_mask = np.tril(np.ones((rows, rows), dtype=bool), -1)
    draw_mask = np.eye(rows, dtype=bool)
    away_mask = np.triu(np.ones((rows, rows), dtype=bool), 1)

    rescaled = matrix.copy()
    for mask, target in ((home_mask, target_home), (draw_mask, target_draw), (away_mask, target_away)):
        current = matrix[mask].sum()
        if current > 0:
            rescaled[mask] *= target / current

    rescaled /= rescaled.sum()
    return rescaled


def predict_scorelines(
    df_history: pd.DataFrame,
    home_team: str,
    away_team: str,
    top_n: int = 5,
    rho: float | None = None,
    target_result_probs: tuple[float, float, float] | None = None,
) -> dict:
    league_avg = float(df_history[["home_goals", "away_goals"]].mean().mean())

    ratings = _compute_team_ratings(df_history)
    home_attack, home_defense = ratings.get(home_team, (1.0, 1.0))
    away_attack, away_defense = ratings.get(away_team, (1.0, 1.0))

    home_xg = home_attack * away_defense * league_avg
    away_xg = away_attack * home_defense * league_avg

    # Rebalance xG towards the stronger team based on FIFA ranking points
    home_factor, away_factor = _rank_adjustment_factors(home_team, away_team)
    home_xg *= home_factor
    away_xg *= away_factor

    # WC group stage produces ~15% more goals than historical average
    home_xg *= 1.15
    away_xg *= 1.15

    # Use typical rho value (-0.13) — well-established in literature
    if rho is None:
        rho = -0.13

    # Dixon-Coles corrected probability matrix
    rows = MAX_GOALS + 1
    matrix = np.zeros((rows, rows))
    for h in range(rows):
        for a in range(rows):
            tau = _tau(h, a, home_xg, away_xg, rho)
            matrix[h, a] = poisson.pmf(h, home_xg) * poisson.pmf(a, away_xg) * tau

    matrix = np.clip(matrix, 0, None)
    matrix /= matrix.sum()

    # Align with the classification model's H/D/A probabilities, if given,
    # so the headline result and the scoreline/betting-market details agree.
    if target_result_probs is not None:
        matrix = _rescale_to_target_result_probs(matrix, *target_result_probs)

    flat = [(matrix[h, a], h, a) for h in range(rows) for a in range(rows)]
    flat.sort(reverse=True)

    scorelines = [
        {"score": f"{h}:{a}", "probability": round(float(p), 4)}
        for p, h, a in flat[:top_n]
    ]

    home_win_prob = float(np.tril(matrix, -1).sum())
    draw_prob = float(np.trace(matrix))
    away_win_prob = float(np.triu(matrix, 1).sum())

    most_likely = scorelines[0]["score"]
    h_goals, a_goals = map(int, most_likely.split(":"))
    result = "H" if h_goals > a_goals else ("A" if h_goals < a_goals else "D")

    all_scorelines = [
        {
            "score": f"{h}:{a}",
            "probability": round(float(p), 4),
            "result": "H" if h > a else ("A" if h < a else "D"),
        }
        for p, h, a in flat
    ]

    betting_markets = compute_betting_markets(
        all_scorelines, home_team, away_team,
        home_win_prob, draw_prob, away_win_prob,
    )

    return {
        "home_xg": round(home_xg, 2),
        "away_xg": round(away_xg, 2),
        "rho": round(rho, 4),
        "most_likely_score": most_likely,
        "result": result,
        "probability_home_win": round(home_win_prob, 4),
        "probability_draw": round(draw_prob, 4),
        "probability_away_win": round(away_win_prob, 4),
        "top_scorelines": scorelines,
        "betting_markets": betting_markets,
        "_all_scorelines": all_scorelines,
    }
