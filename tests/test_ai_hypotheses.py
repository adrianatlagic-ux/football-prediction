from copy import deepcopy
from scripts.check_ai_hypotheses import audit, summarize


def fixture():
    bet = {'market': 'Over/Under 2.5', 'outcome': 'Over', 'best_odds': 2,
           'model_probability_raw': .6, 'market_probability': .5}
    return {'home_team': 'A', 'away_team': 'B', 'sport_key': 'test',
            'commence_time': '2026-10-20T18:00:00Z', 'logged_at': '2026-10-20T17:30:00Z',
            'agent_eval': {'pick': bet, 'first_pick': {**bet, 'outcome': 'Under'},
                           'revised_from_previous': True}}


def result(e):
    return {**e, 'completed': True, 'home_score': 2, 'away_score': 1}


def test_paired_result_and_isolated_gate_comparison():
    e = fixture(); out = audit([e], [result(e)])
    pair = out['pairs'][0]
    assert pair['first']['profit'] == -1 and pair['final']['profit'] == 1
    assert pair['profit_delta'] == 2
    groups = {g['group']: g for g in out['groups'] if g['scope'] == 'ALL'}
    assert groups['policy_all']['n'] == groups['policy_model']['n'] == 1
    assert 'policy_no_change' not in groups and 'policy_both' not in groups


def test_missing_first_pick_is_not_invented_and_dates_are_matched():
    e = fixture(); del e['agent_eval']['first_pick']
    out = audit([e], [result(e)])
    assert out['pairs'] == []
    assert out['exclusions']['changed_but_first_pick_missing'] == 1
    r = result(e); r['commence_time'] = '2026-10-21T18:00:00Z'
    assert audit([e], [r])['exclusions']['missing_or_ambiguous_result'] == 1


def test_postkickoff_and_duplicate_records_do_not_inflate_sample():
    e = fixture(); late = deepcopy(e); late['logged_at'] = '2026-10-20T18:01:00Z'
    out = audit([e, e, late], [result(e)])
    assert len(out['cases']) == 1
    assert out['exclusions']['logged_after_kickoff'] == 1


def test_pushes_count_in_roi_but_not_full_hit_rate():
    stats = summarize([{'label': 'push', 'profit': 0}, {'label': 'win', 'profit': 1}])
    assert stats['n'] == 2 and stats['roi_pct'] == 50 and stats['hit_pct'] == 100
