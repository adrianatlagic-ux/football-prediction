"""Sequential club ratings; each match date is updated as a single batch."""
from collections import defaultdict


class ClubElo:
    def __init__(self, k=20.0, home_advantage=60.0, initial=1500.0):
        self.k = k
        self.home_advantage = home_advantage
        self.initial = initial
        self.ratings = {}

    def features(self, home, away):
        h = self.ratings.get(home, self.initial)
        a = self.ratings.get(away, self.initial)
        return {"home_elo": h, "away_elo": a, "elo_diff": h - a,
                # Expected points fraction (a draw counts half), NOT P(home win).
                "elo_expected_score": 1 / (1 + 10 ** ((a - h - self.home_advantage) / 400))}

    def update_day(self, matches):
        changes = defaultdict(float)
        for row in matches.itertuples():
            expected = self.features(row.home_team, row.away_team)["elo_expected_score"]
            actual = 1.0 if row.home_goals > row.away_goals else 0.0 if row.home_goals < row.away_goals else 0.5
            delta = self.k * (actual - expected)
            changes[row.home_team] += delta
            changes[row.away_team] -= delta
        for team, delta in changes.items():
            self.ratings[team] = self.ratings.get(team, self.initial) + delta

    @classmethod
    def from_history(cls, history):
        elo = cls()
        for _, day in history.groupby("date", sort=True):
            elo.update_day(day)
        return elo
