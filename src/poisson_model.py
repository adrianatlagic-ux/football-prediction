from __future__ import annotations

import numpy as np
import pandas as pd
from scipy.stats import poisson


MAX_GOALS = 8


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
) -> dict:
    league_avg = float(df_history[["home_goals", "away_goals"]].mean().mean())

    home_scored, home_conceded = _team_goal_stats(df_history, home_team)
    away_scored, away_conceded = _team_goal_stats(df_history, away_team)

    home_attack = home_scored / league_avg
    home_defense = home_conceded / league_avg
    away_attack = away_scored / league_avg
    away_defense = away_conceded / league_avg

    # Expected goals
    home_xg = home_attack * away_defense * league_avg
    away_xg = away_attack * home_defense * league_avg

    # Build scoreline probability matrix
    rows = MAX_GOALS + 1
    matrix = np.zeros((rows, rows))
    for h in range(rows):
        for a in range(rows):
            matrix[h, a] = poisson.pmf(h, home_xg) * poisson.pmf(a, away_xg)

    # Normalize
    matrix /= matrix.sum()

    # Top scorelines
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
        "most_likely_score": most_likely,
        "result": result,
        "probability_home_win": round(home_win_prob, 4),
        "probability_draw": round(draw_prob, 4),
        "probability_away_win": round(away_win_prob, 4),
        "top_scorelines": scorelines,
    }
