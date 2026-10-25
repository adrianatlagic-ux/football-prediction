from datetime import datetime, timezone
from copy import deepcopy
from src.ai_tip_review import capture, merge_history, report
from scripts.log_bets import apply
from scripts.pull_server_logs import merge_bets

NOW = datetime(2026, 10, 25, 14, 40, tzinfo=timezone.utc)

def match():
    bet = {'market': 'Over/Under 2.0', 'outcome': 'Over', 'best_odds': 2,
           'model_probability_raw': .6, 'market_probability': .5}
    return {'home_team': 'A', 'away_team': 'B', 'sport_key': 'league',
            'commence_time': '2026-10-25T15:00:00Z', 'event_id': '1',
            'agent_eval': {'pick': bet, 'research_version': 'v3'},
            'bet_tip': {'tip': bet, 'status': 'ok'}, 'bets': [bet]}

def test_capture_is_immutable_deduplicated_and_never_after_kickoff():
    m = match(); item = capture(m, NOW); entry = {}
    m['agent_eval']['pick']['best_odds'] = 9
    assert item['agent_eval']['pick']['best_odds'] == 2
    assert merge_history(entry, [item, item]) == 1
    assert capture(m, datetime(2026, 10, 25, 15, tzinfo=timezone.utc)) is None

def test_logger_keeps_late_ai_decision_and_backup_history():
    m = match(); m['agent_eval'] = None; entries = []
    apply([m], entries, NOW)
    apply([match()], entries, NOW.replace(minute=50))
    apply([match()], entries, NOW.replace(minute=55))
    assert len(entries[0]['ai_review_history']) == 2
    backup = [deepcopy(entries[0])]; backup[0]['ai_review_history'] = []
    merge_bets(backup, entries)
    assert len(backup[0]['ai_review_history']) == 2

def test_report_uses_latest_prematch_and_counts_push_correctly():
    m = match(); item = capture(m, NOW)
    future = capture(m, NOW); future['logged_at'] = '2026-10-25T16:00:00Z'
    result = {**m, 'completed': True, 'home_score': 1, 'away_score': 1}
    output = report([{'ai_review_history': [item, future]}], [result])
    ai = next(g for g in output['groups'] if g['strategy'] == 'ai')
    assert ai['settled'] == 1 and ai['roi_pct'] == 0
    assert ai['outcomes']['push'] == 1 and ai['full_win_rate_pct'] is None
    assert output['excluded']['after_kickoff'] == 1

def test_missing_results_and_versions_are_not_pooled():
    a = capture(match(), NOW); b = deepcopy(a)
    b['away_team'] = 'C'; b['agent_eval']['research_version'] = 'v4'
    output = report([a, b], [])
    assert output['fixtures'] == 2
    assert output['excluded']['missing_or_ambiguous_result'] == 2
    assert {g['version'] for g in output['groups']} == {'v3', 'v4'}
    assert all(g['roi_pct'] is None for g in output['groups'])
