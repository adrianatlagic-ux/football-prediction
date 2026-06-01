import random
import pandas as pd
from pathlib import Path
from datetime import date, timedelta

random.seed(42)

TEAMS = [
    "Bayern", "Dortmund", "Leipzig", "Leverkusen", "Frankfurt",
    "Wolfsburg", "Freiburg", "Union Berlin", "Mainz", "Hoffenheim",
    "Augsburg", "Bochum", "Bremen", "Koeln", "Stuttgart",
    "Gladbach", "Hertha", "Schalke", "Hamburg", "Hannover",
]

TEAM_STRENGTH = {t: random.uniform(0.8, 2.0) for t in TEAMS}


def simulate_goals(strength: float) -> int:
    lam = max(0.3, strength * 1.2)
    return min(int(random.expovariate(1 / lam)), 7)


def generate(n_seasons: int = 5) -> pd.DataFrame:
    rows = []
    current_date = date(2019, 8, 10)
    for season in range(n_seasons):
        matchdays = [(h, a) for h in TEAMS for a in TEAMS if h != a]
        random.shuffle(matchdays)
        for home, away in matchdays:
            rows.append({
                "date": current_date.isoformat(),
                "home_team": home,
                "away_team": away,
                "home_goals": simulate_goals(TEAM_STRENGTH[home] * 1.1),
                "away_goals": simulate_goals(TEAM_STRENGTH[away]),
                "competition": "BL1",
                "season": 2019 + season,
            })
            current_date += timedelta(days=3)
    return pd.DataFrame(rows)


if __name__ == "__main__":
    out = Path(__file__).parent.parent / "data" / "sample_matches.csv"
    out.parent.mkdir(exist_ok=True)
    df = generate()
    df.to_csv(out, index=False)
    print(f"Generated {len(df)} matches -> {out}")
