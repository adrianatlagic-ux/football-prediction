from __future__ import annotations

import numpy as np
import pandas as pd
from scipy.stats import poisson
from scipy.optimize import minimize_scalar

MAX_GOALS = 8


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


def _team_goal_stats(df: pd.DataFrame, team: str, last_n: int = 30) -> tuple[float, float]:
    home = df[df["home_team"] == team].tail(last_n)
    away = df[df["away_team"] == team].tail(last_n)
    scored = list(home["home_goals"]) + list(away["away_goals"])
    conceded = list(home["away_goals"]) + list(away["home_goals"])
    avg_scored = float(np.mean(scored)) if scored else 1.0
    avg_conceded = float(np.mean(conceded)) if conceded else 1.0
    return avg_scored, avg_conceded


def predict_scorelines(
    df_history: pd.DataFrame,
    home_team: str,
    away_team: str,
    top_n: int = 5,
    rho: float | None = None,
) -> dict:
    league_avg = float(df_history[["home_goals", "away_goals"]].mean().mean())

    home_scored, home_conceded = _team_goal_stats(df_history, home_team)
    away_scored, away_conceded = _team_goal_stats(df_history, away_team)

    home_attack = home_scored / league_avg
    home_defense = home_conceded / league_avg
    away_attack = away_scored / league_avg
    away_defense = away_conceded / league_avg

    home_xg = home_attack * away_defense * league_avg
    away_xg = away_attack * home_defense * league_avg

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
    }
