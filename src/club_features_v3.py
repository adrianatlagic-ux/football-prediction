"""Fast chronological features shared by training and prediction (date batches)."""
from collections import defaultdict, deque
import numpy as np
import pandas as pd
from .feature_engineering import _decay_weights, encode_result
from .club_market_value_policy import MarketValueHistory

FEATURE_VERSION = 3


class ClubFeatureState:
    def __init__(self, market_values=None, policy="verified_only"):
        self.teams = defaultdict(lambda: deque(maxlen=10))
        self.h2h = defaultdict(lambda: deque(maxlen=10))
        self.market_values = market_values or MarketValueHistory()
        self.policy = policy

    def row(self, home, away, date):
        f = {}
        for side, team in (("home", home), ("away", away)):
            games = list(self.teams[team])
            if games:
                goals = np.array(games, dtype=float)
                w = _decay_weights(len(games))
                points = np.where(goals[:, 0] > goals[:, 1], 3, np.where(goals[:, 0] == goals[:, 1], 1, 0))
                vals = [w @ points, w @ (points == 3), w @ (points == 1), len(games),
                        w @ goals[:, 0], w @ goals[:, 1], w @ (goals[:, 1] == 0), w @ (goals[:, 0] - goals[:, 1])]
            else:
                vals = [0.0] * 8
            names = ["form_pts", "form_wins", "form_draws", "games_played", "avg_scored", "avg_conceded", "clean_sheets", "avg_goal_diff"]
            f.update({f"{side}_{n}": float(v) for n, v in zip(names, vals)})
        pairs = self.h2h[tuple(sorted((home, away)))]
        winners = [winner for winner in pairs]
        n = len(winners)
        f.update(h2h_home_wins=winners.count(home) / n if n else 0,
                 h2h_draws=winners.count(None) / n if n else 0,
                 h2h_away_wins=winners.count(away) / n if n else 0, h2h_games=float(n))
        f.update(self.market_values.features(home, away, date, self.policy))
        return f

    def update(self, day):
        for r in day.itertuples():
            self.teams[r.home_team].append((r.home_goals, r.away_goals))
            self.teams[r.away_team].append((r.away_goals, r.home_goals))
            winner = r.home_team if r.home_goals > r.away_goals else r.away_team if r.home_goals < r.away_goals else None
            self.h2h[tuple(sorted((r.home_team, r.away_team)))].append(winner)


def prepare_history(history):
    history = history.copy()
    history["date"] = pd.to_datetime(history.date).dt.normalize()
    history = history.sort_values(["date", "home_team", "away_team"], kind="stable").reset_index(drop=True)
    history["result"] = [encode_result(h, a) for h, a in zip(history.home_goals, history.away_goals)]
    return history


def build_features(history, policy="verified_only", market_values=None):
    history = prepare_history(history)
    state = ClubFeatureState(market_values, policy)
    records = []
    for date, day in history.groupby("date", sort=True):
        for r in day.itertuples():
            records.append(state.row(r.home_team, r.away_team, date))
        state.update(day)
    return pd.DataFrame(records)


def prediction_row(history, home, away, as_of, policy="verified_only"):
    history = prepare_history(history)
    state = ClubFeatureState(policy=policy)
    history = history[history.date < pd.Timestamp(as_of).normalize()]
    for _, day in history.groupby("date", sort=True):
        state.update(day)
    return pd.DataFrame([state.row(home, away, as_of)])
