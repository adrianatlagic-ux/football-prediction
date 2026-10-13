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


def _poisson_prediction(home_xg=2.0, away_xg=0.8):
    import math
    pois = lambda lam, k: math.exp(-lam) * lam ** k / math.factorial(k)
    m = [[pois(home_xg, i) * pois(away_xg, j) for j in range(8)] for i in range(8)]
    total = sum(map(sum, m))
    m = [[x / total for x in row] for row in m]
    h = sum(m[i][j] for i in range(8) for j in range(8) if i > j)
    d = sum(m[i][i] for i in range(8))
    return {"home_team": "Germany", "away_team": "Greece", "probability_home_win": h, "probability_draw": d,
            "probability_away_win": 1 - h - d, "prediction": "H", "prediction_label": "Home Win",
            "score_prediction": {"score_matrix": m, "most_likely_score": "2:0", "result": "H",
                                 "betting_markets": {"scenario": "Deutschland kontrolliert das Spiel.",
                                                     "scenario_lang": "de"}}}


def test_a_flipped_favourite_rebuilds_every_derived_field():
    out = adjust(_poisson_prediction(), 0.2, 1.0)
    h, d, a = out["probability_home_win"], out["probability_draw"], out["probability_away_win"]
    assert a > h and out["prediction"] == "A" and out["prediction_label"] == "Away Win"
    sp = out["score_prediction"]
    assert sp["result"] == "A"
    home_goals, away_goals = map(int, sp["most_likely_score"].split(":"))
    assert away_goals > home_goals
    assert all(int(s["score"].split(":")[1]) > int(s["score"].split(":")[0]) for s in sp["top_scorelines"])
    markets = sp["betting_markets"]
    # The written scenario described a home win; it must not survive the flip.
    assert "scenario" not in markets or markets["scenario"] != "Deutschland kontrolliert das Spiel."
    # Double chance and the result probabilities agree.
    dc = markets["double_chance"]
    assert abs(dc["draw_or_away"] - (a + d)) < 0.01
    assert sp["away_xg"] > 0.8


def test_an_unchanged_favourite_keeps_its_scenario():
    out = adjust(_poisson_prediction(), 0.9, 1.0)
    assert out["prediction"] == "H"
    assert out["score_prediction"]["betting_markets"]["scenario"] == "Deutschland kontrolliert das Spiel."


def test_an_english_scenario_is_not_kept():
    # Written before the site went German: replaced by the German template.
    before = _poisson_prediction()
    before["score_prediction"]["betting_markets"] = {"scenario": "Germany control the game."}
    out = adjust(before, 0.9, 1.0)
    markets = out["score_prediction"]["betting_markets"]
    assert markets["scenario"] != "Germany control the game."
    assert markets["scenario_lang"] == "de" and "Deutschland" in markets["scenario"]


def test_espn_names_and_nordic_letters_match_ours():
    from src.lineups import _norm, _team_words, matched_count
    assert _team_words("Türkiye") & _team_words("Turkey")
    assert _team_words("Czechia") & _team_words("Czech Republic")
    assert _team_words("Bosnia-Herzegovina") & _team_words("Bosnia and Herzegovina")
    assert _norm("Odmar Færø") == "odmar faero"
    assert matched_count(["Odmar Færø"], [{"name": "Odmar Faero"}]) == 1
