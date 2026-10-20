from scripts.audit_fallback_tips import select, relaxation_distance, run


def bet(line, p=.75, q=.70, odds=1.5):
    return {'market': f'Over/Under {line}', 'outcome': 'Under', 'team': None,
            'model_probability_raw': p, 'market_probability': q, 'best_odds': odds, 'quote_fresh': True}


def test_fallback_preserves_direction_and_prefers_nearest_qualifying_line():
    pick = bet(2.5, .49, .53, 2)
    near, far = bet(3.5), bet(4.5, .9, .85, 1.31)
    entry = {'agent_eval': {'pick': pick, 'revised_from_previous': False}, 'green_bets': [far, near]}
    assert select(entry, 'original') is None
    assert select(entry, 'fallback') == (near, True)
    assert select(entry, 'fallback_edge') == (near, True)
    entry['agent_eval']['revised_from_previous'] = True
    assert select(entry, 'fallback') is None


def test_edge_filters_original_and_replacement_without_inventing_quotes():
    pick = bet(2.5, .51, .49, 1.5)
    entry = {'agent_eval': {'pick': pick}, 'red_bets': [bet(3.5)]}
    assert select(entry, 'original') == (pick, False)
    assert select(entry, 'original_edge') is None
    # An original rejected only on EV does not activate the rescue rule.
    assert select(entry, 'fallback_edge') is None
    pick['market_probability'] = .55
    entry['red_bets'] = [bet(3.5, .72, .71, 1.30)]
    assert select(entry, 'fallback') is not None
    assert select(entry, 'fallback_edge') is None
    entry['red_bets'] = []
    assert select(entry, 'fallback') is None


def test_team_relaxation_and_goals_have_no_cross_family_implications():
    win = {'market': '1X2', 'outcome': 'home_win', 'team': 'A'}
    dc = {'market': 'Handicap +0.5', 'outcome': 'handicap', 'team': 'A'}
    assert relaxation_distance(win, dc) == 1
    assert relaxation_distance(dc, win) is None
    assert relaxation_distance(win, {**dc, 'team': 'B'}) is None
    assert relaxation_distance(win, bet(3.5)) is None
    assert relaxation_distance(bet(9.5), bet(10.5)) == 1
    assert relaxation_distance(win, {**dc, 'market': 'Handicap 0.0'}) is None


def test_replay_excludes_postmatch_log_and_uses_one_snapshot_per_fixture():
    entry = {'sport_key': 'soccer_test', 'home_team': 'A', 'away_team': 'B',
             'commence_time': '2026-10-01T18:00:00Z', 'logged_at': '2026-10-01T17:30:00Z',
             'agent_eval': {'pick': bet(2.5)}}
    result = {**entry, 'completed': True, 'score_scope': 'regulation', 'home_score': 1, 'away_score': 0}
    late = {**entry, 'logged_at': '2026-10-01T18:01:00Z'}
    report = run([entry, entry, late], [result])
    assert report['policies']['original']['bets'] == 1
    assert report['policies']['original']['profit_units'] == .5
    assert report['exclusions']['logged_after_kickoff'] == 1
