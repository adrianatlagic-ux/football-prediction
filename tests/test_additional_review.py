"""Additional regression and consistency checks from the branch review."""
from datetime import datetime, timezone

import numpy as np
import pytest

from src import jobs, lineups
from src.combo_ticket import day_reports


def prediction():
    matrix = np.array([[.10,.06,.02], [.20,.12,.06], [.24,.10,.10]])
    return {"home_team":"A", "away_team":"B", "prediction":"H",
            "probability_home_win":.54, "probability_draw":.32, "probability_away_win":.14,
            "score_prediction":{"score_matrix":matrix.tolist()}}


@pytest.mark.parametrize("home,away", [(1,1),(.2,1),(1,.2),(.5,.5),(.01,1),(1,.01)])
def test_lineup_result_matrix_and_double_chance_agree(home, away):
    out = lineups.adjust(prediction(), home, away)
    m = np.array(out["score_prediction"]["score_matrix"])
    p = np.array([out[k] for k in ("probability_home_win","probability_draw","probability_away_win")])
    np.testing.assert_allclose([np.tril(m,-1).sum(),np.trace(m),np.triu(m,1).sum()],p,atol=1e-4)
    assert np.isfinite(m).all() and (m >= 0).all() and m.sum() == pytest.approx(1)
    assert out["prediction"] == ["H","D","A"][int(p.argmax())]
    dc = out["score_prediction"]["betting_markets"]["double_chance"]
    assert dc["home_or_draw"] == pytest.approx(p[0]+p[1],abs=.001)


@pytest.mark.parametrize("valued_sides", [0,1,2])
def test_lineup_job_only_finishes_with_both_valuations(monkeypatch, valued_sides):
    import scripts.refresh_squad_predictions as refresh
    import src.squad_data as squads
    fixture = {"match_id":"test", "competition":"nations_league", "home_team":"A",
               "away_team":"B", "kickoff":datetime.now(timezone.utc)}
    monkeypatch.setattr(refresh,"upcoming",lambda *args:[fixture])
    monkeypatch.setattr(refresh,"load_registry",lambda *args:{"A":"1","B":"2"})
    monkeypatch.setattr(lineups,"fetch_starters",lambda *args:{"home":[],"away":[]})
    monkeypatch.setattr(squads,"cached_squads",lambda *args:{})
    values = iter([{"share":.5} if i < valued_sides else None for i in range(2)])
    monkeypatch.setattr(lineups,"lineup_share",lambda *args:next(values))
    monkeypatch.setattr(jobs,"_cached",lambda *args:{})
    monkeypatch.setattr(jobs,"_report",lambda name,r:r)
    writes=[]
    monkeypatch.setattr(jobs,"_write",lambda f,r:writes.append(r))
    class Predictor:
        def predict_match(self,*args,**kwargs): return prediction()
    report=jobs.run_hourly(Predictor,Predictor)
    assert bool(writes) == (valued_sides == 2)
    assert bool(report["refreshed"]) == (valued_sides == 2)


def test_combo_threshold_uses_unrounded_price():
    def leg(home,away,odds):
        return {"home_team":home,"away_team":away,"team":home,"market":"1X2","outcome":"home_win",
                "commence_time":"2026-09-28T18:45:00Z","bookmaker":"Book","bookmaker_key":"book",
                "best_odds":odds,"probability":.7,"market_probability":.7,"conservative_probability":.7}
    option=day_reports([leg("A","B",1.33),leg("C","D",1.50)],2)[0]["by_size"][0]
    assert option["ticket"] is None
    assert option["near_miss"] is not None


def test_validation_reports_identical_models_as_zero_difference():
    from scripts.validate_national_blend import metrics
    rows=[{"date":f"2022-{month:02}-01","result":0,"classifier":[.6,.2,.2],"poisson":[.6,.2,.2]}
          for month in range(1,5)]
    report=metrics(rows)
    assert report["accuracy_delta_40_minus_20"]["month_block_ci95"] == [0,0]
    assert report["logloss_delta_40_minus_20"]["mean"] == pytest.approx(0)
