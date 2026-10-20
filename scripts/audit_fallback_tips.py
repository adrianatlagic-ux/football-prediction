"""Replay fixed AI-tip policies on recorded pre-match quotes, never new prices.

Usage: python scripts/audit_fallback_tips.py --logs FILE --results FILE --out FILE
One unit per single bet. Alternatives are incomplete in legacy green/red logs.
"""
import argparse
from collections import Counter, defaultdict
import hashlib
import json
import math
from pathlib import Path
import random
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src.bet_audit import norm, timestamp, settlement

POLICIES = ('original', 'original_edge', 'fallback', 'fallback_edge')


def identity(b):
    return (b.get('market'), b.get('outcome'), b.get('team'))


def model(b):
    return b.get('model_probability_raw') if b.get('model_probability_raw') is not None else b.get('probability')


def binary(b):
    m = b.get('market', '')
    if m in ('1X2', 'BTTS'):
        return True
    try:
        return m.startswith(('Handicap ', 'Over/Under ')) and float(m.split()[-1]) % 1 == .5
    except ValueError:
        return False


def eligible(b, edge=False):
    p, q, odds = model(b), b.get('market_probability'), b.get('best_odds', 0)
    return (p is not None and q is not None and all(math.isfinite(v) for v in (p, q, odds))
            and 0 <= q <= p <= 1 and odds >= 1.30 and b.get('quote_fresh') is not False
            and (not edge or (binary(b) and p * odds - 1 > 0)))


def relaxation_distance(pick, bet):
    """Analytic implication for binary, same-direction goals/team bets only.

    Unlike a bounded score grid this cannot infer false implications above 8 goals.
    Win = team handicap -0.5; draw-no-bet and quarter/push lines excluded.
    """
    pm, bm = pick.get('market', ''), bet.get('market', '')
    if not binary(pick) or not binary(bet):
        return None
    if pm.startswith('Over/Under ') and bm.startswith('Over/Under ') and pick['outcome'] == bet['outcome']:
        a, b = float(pm.split()[-1]), float(bm.split()[-1])
        distance = b - a if pick['outcome'] == 'Under' else a - b
        return distance if distance > 0 else None
    if not pick.get('team') or norm(pick['team']) != norm(bet.get('team', '')):
        return None
    def team_line(b):
        if b['market'] == '1X2' and b['outcome'] in ('home_win', 'away_win'):
            return -.5
        if b['market'].startswith('Handicap '):
            return float(b['market'].split()[-1])
        return None
    a, b = team_line(pick), team_line(bet)
    return b - a if a is not None and b is not None and b > a else None


def select(entry, policy):
    agent = entry.get('agent_eval') or {}
    pick = agent.get('pick')
    if not pick or agent.get('revised_from_previous'):
        return None
    edge = policy.endswith('_edge')
    if eligible(pick, edge):
        return pick, False
    # Rescue only a model-below-market rejection, not low prices/missing data.
    p, q = model(pick), pick.get('market_probability')
    if not policy.startswith('fallback') or p is None or q is None or p >= q or pick.get('best_odds', 0) < 1.30:
        return None
    bets = entry.get('bets') or entry.get('green_bets', []) + entry.get('red_bets', [])
    candidates = []
    seen = set()
    for b in bets:
        key = identity(b)
        if key in seen:
            continue
        seen.add(key)
        distance = relaxation_distance(pick, b)
        if distance is not None and eligible(b, edge):
            candidates.append((distance, b))
    if not candidates:
        return None
    # Nearest qualifying relaxation first, then better price, stable identity.
    b = min(candidates, key=lambda x: (x[0], -x[1]['best_odds'], str(identity(x[1]))))[1]
    return b, True


def summary(rows):
    n = len(rows)
    wins = sum(x['settlement'] == 'win' for x in rows)
    losses = sum(x['settlement'] == 'loss' for x in rows)
    return {'bets': n, 'wins': wins, 'losses': losses, 'push_or_partial': n-wins-losses,
            'hit_rate': wins/(wins+losses) if wins+losses else None,
            'profit_units': round(sum(x['profit_units'] for x in rows), 6),
            'roi': sum(x['profit_units'] for x in rows)/n if n else None,
            'fallback_bets': sum(x['fallback'] for x in rows)}


def run(logs, results):
    def key(e):
        return (e.get('sport_key'), norm(e['home_team']), norm(e['away_team']), timestamp(e['commence_time']).isoformat())
    finished = {key(r): r for r in results if r.get('completed') and r.get('home_score') is not None
                and r.get('score_scope') == 'regulation'}
    latest, exclusions = {}, Counter()
    for e in logs:
        try:
            k = key(e)
            kickoff, logged = timestamp(e['commence_time']), timestamp(e['logged_at'])
            if logged >= kickoff:
                exclusions['logged_after_kickoff'] += 1
                continue
            evidence = ((e.get('agent_eval') or {}).get('evidence') or {}).get('researched_at')
            if evidence and timestamp(evidence) >= kickoff:
                exclusions['research_after_kickoff'] += 1
                continue
            if k not in latest or logged > timestamp(latest[k]['logged_at']):
                latest[k] = e
        except (ValueError, KeyError, TypeError):
            exclusions['invalid_identity_or_time'] += 1
    records, coverage = [], Counter()
    for k, e in sorted(latest.items()):
        if k not in finished:
            exclusions['no_completed_regulation_result'] += 1
            continue
        a = e.get('agent_eval') or {}; p = a.get('pick')
        if not p:
            exclusions['no_ai_pick'] += 1
            continue
        coverage['finished_with_ai'] += 1
        coverage['full_bets_field'] += bool(e.get('bets'))
        coverage['changed_ai'] += bool(a.get('revised_from_previous'))
        if (not a.get('revised_from_previous') and model(p) is not None
                and p.get('market_probability') is not None and model(p) < p['market_probability']
                and p.get('best_odds', 0) >= 1.30):
            coverage['fallback_triggered'] += 1
            alternatives = e.get('bets') or e.get('green_bets', []) + e.get('red_bets', [])
            relaxed = [b for b in alternatives if relaxation_distance(p, b) is not None]
            coverage['trigger_with_recorded_relaxation'] += bool(relaxed)
            coverage['trigger_with_qualifying_relaxation'] += any(eligible(b) for b in relaxed)
        r = finished[k]
        for policy in POLICIES:
            chosen = select(e, policy)
            if not chosen:
                continue
            bet, fallback = chosen
            try:
                label, profit = settlement(bet, e['home_team'], e['away_team'], r['home_score'], r['away_score'])
            except (ValueError, KeyError, TypeError):
                exclusions['ungradable_'+policy] += 1
                continue
            records.append({'policy': policy, 'fixture': list(k), 'date': k[-1][:10], 'competition': k[0],
                            'logged_at': e['logged_at'], 'score': [r['home_score'], r['away_score']],
                            'ai_pick': {x: p.get(x) for x in ('market','outcome','team')},
                            'bet': {x: bet.get(x) for x in ('market','outcome','team','best_odds','bookmaker','model_probability_raw','probability','market_probability')},
                            'fallback': fallback, 'settlement': label, 'profit_units': profit})
    report = {'policies': {p: summary([x for x in records if x['policy'] == p]) for p in POLICIES},
              'date_range': [min((x['date'] for x in records), default=None), max((x['date'] for x in records), default=None)],
              'coverage': dict(coverage), 'exclusions': dict(exclusions), 'records': records,
              'method': {'stake': 'one unit per single, no compounding or commissions',
                         'edge': 'raw model probability * recorded decimal odds - 1 > 0; binary markets only',
                         'fallback': 'only model-below-market rejections; nearest eligible strictly weaker same-direction binary bet',
                         'ai_change': 'always rejected, including same-direction changes',
                         'limitations': ['Legacy logs omit some rejected candidates; no missing quotes reconstructed.',
                                         'Retrospective exploratory replay; baseline rule already informed by this history.',
                                         'Different policies place different numbers of bets; no causal or future-profit claim.']}}
    report['by_competition'] = {c: {p: summary([x for x in records if x['policy']==p and x['competition']==c]) for p in POLICIES}
                                for c in sorted({x['competition'] for x in records})}
    # Resample whole kickoff dates, preserving correlation among same-day games.
    dates = sorted({x['date'] for x in records})
    by_day = {p: {d: [x for x in records if x['policy']==p and x['date']==d] for d in dates} for p in POLICIES}
    rng = random.Random(20261020)
    differences = defaultdict(list)
    for _ in range(4000):
        sample = rng.choices(dates, k=len(dates)) if dates else []
        vals = {p: summary([x for d in sample for x in by_day[p][d]]) for p in POLICIES}
        for p in POLICIES[1:]:
            for metric in ('roi', 'hit_rate'):
                a, b = vals[p][metric], vals['original'][metric]
                if a is not None and b is not None:
                    differences[p+':'+metric].append(a-b)
    report['date_cluster_bootstrap_delta_vs_original_95pct'] = {
        k: [sorted(v)[int(.025*len(v))], sorted(v)[min(len(v)-1,int(.975*len(v)))]] for k,v in differences.items() if v}
    return report


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--logs', required=True, type=Path)
    ap.add_argument('--results', required=True, type=Path)
    ap.add_argument('--out', required=True, type=Path)
    args=ap.parse_args()
    logs=[json.loads(l) for l in args.logs.read_text().splitlines() if l.strip()]
    data=json.loads(args.results.read_text())
    report=run(logs, data['results'] if isinstance(data,dict) else data)
    report['sources']={str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in (args.logs,args.results)}
    args.out.parent.mkdir(parents=True,exist_ok=True)
    args.out.write_text(json.dumps(report,indent=2,ensure_ascii=False)+'\n')
    print(json.dumps({k:v for k,v in report.items() if k not in ('records','sources')},indent=2))


if __name__=='__main__':
    main()
