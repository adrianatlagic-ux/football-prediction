"""Observe existing AI decisions and grade them; never calls a model or changes picks."""
import hashlib
import json
from collections import Counter, defaultdict
from copy import deepcopy
from pathlib import Path

from src.bet_audit import norm, settlement, timestamp


def capture(match, now):
    """Immutable, deduplicated decision snapshot, strictly before kickoff."""
    try:
        if now >= timestamp(match['commence_time']) or match.get('in_play'):
            return None
    except (KeyError, ValueError, TypeError):
        return None
    fields = ('home_team', 'away_team', 'sport_key', 'event_id', 'commence_time',
              'agent_eval', 'bet_tip', 'likely_pick', 'odds_fetched_at', 'odds_stage')
    item = deepcopy({k: match.get(k) for k in fields})
    item['snapshot_id'] = hashlib.sha256(json.dumps(item, sort_keys=True).encode()).hexdigest()
    item['logged_at'] = now.isoformat()
    return item


def merge_history(old, new):
    history = old.setdefault('ai_review_history', [])
    seen = {x['snapshot_id'] for x in history}
    added = 0
    for item in new:
        if item['snapshot_id'] not in seen:
            history.append(deepcopy(item))
            seen.add(item['snapshot_id'])
            added += 1
    return added


def _key(item):
    return (item.get('sport_key') or 'unknown', norm(item['home_team']), norm(item['away_team']),
            timestamp(item['commence_time']).date().isoformat())


def report(entries, results):
    """One final pre-match observation per fixture; one unit per actual bet.

    Groups are descriptive, not optimized strategies or evidence of causality.
    Missing scores, ambiguous matches and unsupported settlements stay visible.
    """
    latest, excluded = {}, Counter()
    for entry in entries:
        for item in entry.get('ai_review_history') or [entry]:
            try:
                if timestamp(item['logged_at']) >= timestamp(item['commence_time']):
                    excluded['after_kickoff'] += 1
                    continue
                key = _key(item)
                if key not in latest or timestamp(item['logged_at']) >= timestamp(latest[key]['logged_at']):
                    latest[key] = item
            except (KeyError, ValueError, TypeError):
                excluded['invalid_time_or_identity'] += 1
    finished = defaultdict(list)
    for result in results:
        if result.get('completed') and result.get('score_scope', 'regulation') == 'regulation':
            try:
                finished[_key(result)].append(result)
            except (KeyError, ValueError, TypeError):
                continue
    buckets, decisions = {}, []
    for key, item in sorted(latest.items()):
        agent, tip = item.get('agent_eval') or {}, item.get('bet_tip') or {}
        version = agent.get('research_version') or 'legacy_unversioned'
        week = timestamp(item['commence_time']).strftime('%G-W%V')
        identity = (version, item.get('sport_key'), week)
        candidates = finished.get(key, [])
        scores = {(r.get('home_score'), r.get('away_score')) for r in candidates}
        score = next(iter(scores)) if len(scores) == 1 else None
        if score is None or None in score:
            excluded['missing_or_ambiguous_result'] += 1
        row = {**dict(zip(('version', 'competition', 'week'), identity)),
               'home_team': item['home_team'], 'away_team': item['away_team'],
               'commence_time': item['commence_time'], 'logged_at': item['logged_at'],
               'status': tip.get('status', 'unknown'), 'reasoning': agent.get('bet_reasoning'),
               'research': agent.get('research'), 'strategies': {}}
        # Model-only agreement is kept separate from other gates (changed pick,
        # minimum odds, freshness, fallback). The live selection is never altered.
        pick = agent.get('pick')
        strategies = {'ai': pick, 'published': tip.get('tip'),
                      'first_ai': agent.get('first_pick'), 'market_baseline': item.get('likely_pick')}
        if pick:
            model, market = pick.get('model_probability_raw'), pick.get('market_probability')
            if model is not None and market is not None:
                strategies['model_agrees' if model >= market else 'model_disagrees'] = pick
        for strategy, bet in strategies.items():
            market_group = (bet.get('market', '').split(' ')[0] if bet else 'no_pick')
            group = (*identity, strategy, market_group)
            bucket = buckets.setdefault(group, {'version': version, 'competition': identity[1],
                'week': week, 'strategy': strategy, 'market': market_group,
                'fixtures': 0, 'bets': 0, 'settled': 0, 'profit_units': 0., 'outcomes': Counter()})
            bucket['fixtures'] += 1
            if not bet:
                continue
            bucket['bets'] += 1
            row['strategies'][strategy] = {'pick': bet, 'settlement': None}
            if score is None or None in score:
                continue
            try:
                label, profit = settlement(bet, item['home_team'], item['away_team'], *score)
            except (ValueError, KeyError, TypeError):
                excluded['unsupported_settlement'] += 1
                continue
            bucket['settled'] += 1
            bucket['profit_units'] += profit
            bucket['outcomes'][label] += 1
            row['strategies'][strategy].update(settlement=label, profit_units=profit)
        decisions.append(row)
    for bucket in buckets.values():
        n = bucket['settled']
        bucket['roi_pct'] = round(100 * bucket['profit_units'] / n, 2) if n else None
        full = bucket['outcomes']['win'] + bucket['outcomes']['loss']
        bucket['full_win_rate_pct'] = round(100 * bucket['outcomes']['win'] / full, 2) if full else None
        bucket['profit_units'] = round(bucket['profit_units'], 4)
    return {'schema_version': 1, 'stake_units': 1, 'fixtures': len(latest),
            'notes': ['Descriptive results; small groups do not establish profitability.',
                      'ROI includes pushes and partial settlements; full win rate excludes them.',
                      'Model groups are observational; the published strategy includes other gates.',
                      'No automatic prompt changes. Validate proposed changes on future matches.'],
            'excluded': dict(excluded), 'groups': list(buckets.values()), 'decisions': decisions}


def refresh(results, root):
    root = Path(root)
    entries = []
    for path in (root / 'data/bet_log.jsonl', root / 'data/logs/bet_log.jsonl'):
        if path.exists():
            entries.extend(json.loads(line) for line in path.read_text().splitlines() if line.strip())
    output = report(entries, results.get('results', []) if isinstance(results, dict) else results)
    path = root / 'data/jobs/ai_tip_review.json'
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix('.tmp')
    temp.write_text(json.dumps(output, ensure_ascii=False, indent=2) + '\n')
    temp.replace(path)
    return output
