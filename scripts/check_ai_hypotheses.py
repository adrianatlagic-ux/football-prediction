"""Offline, fixed-rule audit of rechecks and the model gate. No AI requests."""
import argparse
import json
import math
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src.bet_audit import norm, settlement, timestamp
from src.price_tip import pick_direction


def identity(e):
    return (e.get('sport_key'), norm(e['home_team']), norm(e['away_team']),
            timestamp(e['commence_time']).date().isoformat())


def summarize(cases):
    counts = Counter(c['label'] for c in cases)
    n = len(cases)
    full = counts['win'] + counts['loss']
    p = counts['win'] / full if full else None
    interval = None
    if full:
        z = 1.96
        center = (p + z*z/(2*full)) / (1+z*z/full)
        half = z * math.sqrt(p*(1-p)/full + z*z/(4*full*full)) / (1+z*z/full)
        interval = [round(100*(center-half), 1), round(100*(center+half), 1)]
    profit = sum(c['profit'] for c in cases)
    return {'n': n, 'outcomes': dict(counts), 'hit_pct': round(100*p, 1) if p is not None else None,
            'hit_wilson_95_pct': interval, 'profit_units': round(profit, 4),
            'roi_pct': round(100*profit/n, 1) if n else None}


def audit(entries, results):
    excluded, latest, finished = Counter(), {}, defaultdict(list)
    for r in results:
        if r.get('completed') and r.get('score_scope', 'regulation') == 'regulation':
            finished[identity(r)].append(r)
    for e in entries:
        try:
            if timestamp(e['logged_at']) >= timestamp(e['commence_time']):
                excluded['logged_after_kickoff'] += 1
                continue
            k = identity(e)
            if k not in latest or timestamp(e['logged_at']) > timestamp(latest[k]['logged_at']):
                latest[k] = e
        except (ValueError, KeyError, TypeError):
            excluded['invalid_identity_or_time'] += 1
    groups, paired, records = defaultdict(list), [], []
    for key, e in sorted(latest.items()):
        scores = {(r.get('home_score'), r.get('away_score')) for r in finished.get(key, [])}
        if len(scores) != 1 or None in next(iter(scores)):
            excluded['missing_or_ambiguous_result'] += 1
            continue
        score = next(iter(scores))
        a = e.get('agent_eval') or {}
        final, first = a.get('pick'), a.get('first_pick')
        if not final:
            excluded['no_final_ai_pick'] += 1
            continue
        def grade(b):
            label, profit = settlement(b, e['home_team'], e['away_team'], *score)
            return {'label': label, 'profit': profit}
        try:
            value = grade(final)
        except (ValueError, KeyError, TypeError):
            excluded['unsupported_final_settlement'] += 1
            continue
        revised = a.get('revised_from_previous')
        state = 'changed' if revised is True else 'kept' if revised is False else 'not_rechecked'
        raw, market = final.get('model_probability_raw'), final.get('market_probability')
        agreement = None if raw is None or market is None else raw >= market
        version = a.get('research_version') or 'unknown'
        regime = 'since_2026-10-11' if key[3] >= '2026-10-11' else 'before_2026-10-11'
        def add(label, val=value):
            for scope in ('ALL', e['sport_key'], regime):
                groups[(scope, label)].append(val)
        add(state)
        if agreement is not None:
            add('model_agrees' if agreement else 'model_disagrees')
        record = {'date': key[3], 'home': e['home_team'], 'away': e['away_team'],
                  'competition': e['sport_key'], 'version': version, 'recheck': state,
                  'model_agrees': agreement, 'final': final, 'result': score, **value,
                  'reasoning': a.get('bet_reasoning')}
        # Controlled comparison on the same observable base: rechecked picks,
        # price >=1.30, not marked stale, both model and market values present.
        # No fallback: isolate the two gates on the original final AI selection.
        if revised is not None and agreement is not None and final['best_odds'] >= 1.30 and final.get('quote_fresh') is not False:
            add('policy_all')
            if not revised:
                add('policy_no_change')
            if agreement:
                add('policy_model')
            if not revised and agreement:
                add('policy_both')
        if revised is True:
            if first:
                try:
                    old = grade(first)
                    direction = 'same_side' if pick_direction(first) == pick_direction(final) else 'changed_direction'
                    add(direction)
                    add('paired_first', old)
                    add('paired_final')
                    paired.append({'date': key[3], 'home': e['home_team'], 'away': e['away_team'],
                                   'competition': e['sport_key'], 'direction': direction,
                                   'first_pick': first, 'final_pick': final,
                                   'first': old, 'final': value, 'profit_delta': value['profit']-old['profit']})
                except (ValueError, KeyError, TypeError):
                    excluded['unsupported_first_settlement'] += 1
            else:
                excluded['changed_but_first_pick_missing'] += 1
        records.append(record)
    return {'exclusions': dict(excluded), 'fixtures': len(latest),
            'groups': [{'scope': k[0], 'group': k[1], **summarize(v)} for k,v in sorted(groups.items())],
            'pairs': paired, 'cases': records}


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--log', type=Path, required=True)
    p.add_argument('--results', type=Path, required=True)
    p.add_argument('--output', type=Path, required=True)
    args = p.parse_args()
    entries = [json.loads(l) for l in args.log.read_text().splitlines() if l.strip()]
    results = json.loads(args.results.read_text())
    output = audit(entries, results['results'] if isinstance(results, dict) else results)
    args.output.write_text(json.dumps(output, ensure_ascii=False, indent=2)+'\n')
    print('Exclusions:', output['exclusions'])
    for g in output['groups']:
        print(g['scope'], g['group'], 'n=',g['n'], 'hit=',g['hit_pct'], 'ROI=',g['roi_pct'], 'profit=',g['profit_units'])
    for pair in output['pairs']:
        print('PAIR', pair['date'], pair['home'], pair['direction'],pair['first'],pair['final'])

if __name__ == '__main__':
    main()
