from src.lineups import adjust, lineup_share

SQUAD = ([{"name": "Keeper One", "marketValueEur": 30e6, "positionName": "Goalkeeper"},
          {"name": "Keeper Two", "marketValueEur": 5e6, "positionName": "Goalkeeper"}]
         + [{"name": f"Star {i}", "marketValueEur": 50e6, "positionName": "Midfield"} for i in range(10)]
         + [{"name": f"Reserve {i}", "marketValueEur": 10e6, "positionName": "Defender"} for i in range(10)])


def test_a_reserve_eleven_is_valued_against_the_best_eleven():
    best = lineup_share(["Keeper One"] + [f"Star {i}" for i in range(10)], SQUAD)
    b_team = lineup_share(["Keeper Two"] + [f"Reserve {i}" for i in range(10)], SQUAD)
    full = 530e6 + 25 / 90 * 50e6          # best eleven + next five best (5 reserves)
    assert abs(best["share"] - 530e6 / full) < 1e-9
    assert abs(b_team["share"] - (5e6 + 100e6) / full) < 1e-9


def test_the_bench_counts_by_playing_time():
    b_team = ["Keeper Two"] + [f"Reserve {i}" for i in range(10)]
    with_stars = lineup_share(b_team, SQUAD, bench=[f"Star {i}" for i in range(6)])
    without = lineup_share(b_team, SQUAD, bench=[])
    assert abs(with_stars["bench_value"] - 25 / 90 * 5 * 50e6) < 1e-6
    assert with_stars["share"] > without["share"]


def test_too_few_known_starters_are_not_valued():
    assert lineup_share([f"Unknown {i}" for i in range(11)], SQUAD) is None


def test_a_weaker_home_eleven_moves_the_prediction_toward_the_away_side():
    p = {"probability_home_win": .64, "probability_draw": .24, "probability_away_win": .12,
         "score_prediction": {"score_matrix": [[.2, .1], [.4, .3]]}}
    out = adjust(p, 0.47, 0.67)
    assert out["probability_home_win"] < .64 and out["probability_away_win"] > .12
    assert abs(sum(out[k] for k in ("probability_home_win", "probability_draw", "probability_away_win")) - 1) < 1e-3
    assert abs(sum(map(sum, out["score_prediction"]["score_matrix"])) - 1) < 1e-9
    assert adjust(p, 1.0, 1.0)["probability_home_win"] == .64
