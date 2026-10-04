#!/usr/bin/env python3
"""Live editorial shortlist and transactional credit ledger. No paid API calls."""
import argparse
import json
import math
from pathlib import Path
import re
import sqlite3
from datetime import datetime, timedelta, timezone
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

HERE = Path(__file__).resolve().parent
CONFIG = json.loads((HERE / 'config.json').read_text())
TZ = ZoneInfo(CONFIG['timezone'])


def now():
    return datetime.now(timezone.utc)


def fetch(path):
    req = Request(CONFIG['api_base'] + path, headers={'User-Agent': 'Goalfiq-Content/1.0'})
    with urlopen(req, timeout=30) as response:
        return json.load(response)


def validate(fixture, prediction, at):
    kickoff = datetime.fromisoformat(f"{fixture['date']}T{fixture['time']}").replace(tzinfo=TZ)
    if kickoff.date() != at.astimezone(TZ).date():
        raise ValueError('not_today')
    if kickoff < at + timedelta(hours=CONFIG['minimum_lead_hours']):
        raise ValueError('too_close_to_kickoff')
    for key in ('match_id', 'home_team', 'away_team', 'date', 'time'):
        if prediction.get(key) != fixture.get(key):
            raise ValueError('prediction_fixture_mismatch:' + key)
    timestamp = prediction.get('generated_at') or prediction.get('updated_at') or prediction.get('history_refreshed_at')
    if not timestamp:
        raise ValueError('missing_freshness_timestamp')
    stamp = datetime.fromisoformat(timestamp.replace('Z', '+00:00'))
    if stamp.tzinfo is None:
        raise ValueError('ambiguous_freshness_timezone')
    age = (at - stamp).total_seconds() / 3600
    if age < -0.1 or age > CONFIG['prediction_max_age_hours']:
        raise ValueError('stale_prediction')
    probs = [prediction.get('probability_' + x) for x in ('home_win', 'draw', 'away_win')]
    if any(isinstance(p, bool) or not isinstance(p, (int, float)) or not math.isfinite(p) or not 0 <= p <= 1 for p in probs):
        raise ValueError('invalid_probabilities')
    if abs(sum(probs) - 1) > 0.015:
        raise ValueError('probabilities_do_not_sum_to_one')
    return probs, timestamp


def rank(fixture, prediction, at):
    probs, stamp = validate(fixture, prediction, at)
    h, d, a = probs
    home, away = fixture['home_team'], fixture['away_team']
    relevance = sum(CONFIG['team_relevance'].get(t, 0.35) for t in (home, away)) / 2
    closeness = 1 - abs(h - a)
    # Editorial heuristic, not a prediction model or a claim of virality.
    tension = 1 - max(h, a)
    score = round(100 * (0.5 * relevance + 0.3 * closeness + 0.2 * tension), 1)
    favorite = home if h >= a else away
    angle = 'open_duel' if abs(h-a) < 0.15 else 'favorite_under_pressure'
    return {**fixture, 'editorial_score': score, 'angle': angle,
            'favorite': favorite, 'favorite_probability': max(h, a),
            'probabilities': {'home': h, 'draw': d, 'away': a},
            'freshness_timestamp': stamp,
            'freshness_field': next(k for k in ('generated_at', 'updated_at', 'history_refreshed_at') if prediction.get(k)),
            'source': CONFIG['api_base'] + '/predictions/' + fixture['match_id'],
            'prediction': prediction}


def collect():
    at = now()
    live = fetch('/fixtures')
    if not isinstance(live, dict) or not {'bl','cl','nl'}.issubset(live) or any(not isinstance(live[k], list) for k in ('bl','cl','nl')):
        raise ValueError('unexpected_fixture_schema')
    candidates, excluded = [], []
    for competition, fixtures in live.items():
        if not isinstance(fixtures, list):
            continue
        for fixture in fixtures:
            if fixture.get('date') != at.astimezone(TZ).date().isoformat():
                continue
            try:
                match_id = fixture['match_id']
                if not re.fullmatch(r'[\w-]+', match_id):
                    raise ValueError('invalid_match_id')
                candidates.append({**rank(fixture, fetch('/predictions/' + match_id), at), 'competition': competition})
            except Exception as exc:
                excluded.append({'match_id': fixture.get('match_id'), 'reason': str(exc)})
    candidates.sort(key=lambda c: (-c['editorial_score'], c['time'], c['match_id']))
    eligible = [c for c in candidates if c['editorial_score'] >= CONFIG['minimum_editorial_score']]
    selection = eligible[:1]
    # Only group matches when both score similarly and share a narrative.
    if len(eligible) >= 2 and eligible[0]['editorial_score'] - eligible[1]['editorial_score'] <= 5 and eligible[0]['angle'] == eligible[1]['angle']:
        selection = eligible[:2]
    return {'date': at.astimezone(TZ).date().isoformat(), 'fetched_at': at.isoformat(),
            'api_base': CONFIG['api_base'], 'format': 'roundup' if len(selection) > 1 else 'single',
            'candidates': candidates, 'excluded': excluded,
            'suggested_match_ids': [c['match_id'] for c in selection]}


def database(path):
    path.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(path, timeout=30, isolation_level=None)
    con.row_factory = sqlite3.Row
    con.executescript('''
      CREATE TABLE IF NOT EXISTS posts (id TEXT PRIMARY KEY, created TEXT NOT NULL,
        state TEXT NOT NULL, manifest TEXT NOT NULL);
      CREATE TABLE IF NOT EXISTS charges (id TEXT PRIMARY KEY, post_id TEXT NOT NULL,
        created TEXT NOT NULL, credits REAL NOT NULL, job_id TEXT, state TEXT NOT NULL);
    ''')
    return con


def reserve(con, post_id, charge_id, credits, balance, at=None):
    at = at or now()
    if not math.isfinite(credits) or credits <= 0 or not math.isfinite(balance):
        raise ValueError('invalid_cost_or_balance')
    con.execute('BEGIN IMMEDIATE')
    try:
        if con.execute('SELECT 1 FROM charges WHERE id=?', (charge_id,)).fetchone():
            raise ValueError('reservation_exists_do_not_resubmit')
        post = con.execute('SELECT state FROM posts WHERE id=?', (post_id,)).fetchone()
        if not post or post['state'] != 'planned':
            raise ValueError('post_not_planned')
        rows = con.execute("SELECT * FROM charges WHERE state != 'released'").fetchall()
        local_month = at.astimezone(TZ).strftime('%Y-%m')
        monthly = sum(r['credits'] for r in rows if datetime.fromisoformat(r['created']).astimezone(TZ).strftime('%Y-%m') == local_month)
        rolling = lambda days: sum(r['credits'] for r in rows if datetime.fromisoformat(r['created']) >= at - timedelta(days=days))
        post_total = sum(r['credits'] for r in rows if r['post_id'] == post_id)
        outstanding = sum(r['credits'] for r in rows if r['state'] == 'reserved')
        for spent, limit, label in ((monthly, CONFIG['monthly_credit_limit'], 'month'),
                                   (rolling(30), CONFIG['rolling_30_day_credit_limit'], '30_days'),
                                   (rolling(7), CONFIG['rolling_7_day_credit_limit'], '7_days'),
                                   (post_total, CONFIG['post_credit_limit'], 'post')):
            if spent + credits > limit + 1e-9:
                raise ValueError('budget_exceeded:' + label)
        if balance - outstanding - credits < CONFIG['credit_floor']:
            raise ValueError('credit_floor')
        con.execute('INSERT INTO charges VALUES (?,?,?,?,NULL,?)', (charge_id, post_id, at.isoformat(), credits, 'reserved'))
        con.commit()
    except Exception:
        con.rollback()
        raise


def plan(con, packet_path, chosen=None):
    packet = json.loads(packet_path.read_text())
    at = now()
    if at - datetime.fromisoformat(packet['fetched_at']) > timedelta(minutes=30):
        raise ValueError('refetch_packet_older_than_30_minutes')
    chosen = chosen or packet['suggested_match_ids']
    candidates = {c['match_id']: c for c in packet['candidates']}
    if not 1 <= len(chosen) <= 3 or len(set(chosen)) != len(chosen):
        raise ValueError('choose_one_to_three_distinct_matches')
    selected = [candidates[x] for x in chosen]
    for item in selected:
        validate(item, item['prediction'], at)
        if item['editorial_score'] < CONFIG['minimum_editorial_score']:
            raise ValueError('insufficient_editorial_score')
    post_id = packet['date'] + '-preview'
    con.execute('BEGIN IMMEDIATE')
    try:
        existing = con.execute('SELECT manifest FROM posts WHERE id=?', (post_id,)).fetchone()
        if existing:
            raise ValueError('daily_post_exists_resume:' + existing['manifest'])
        month = at.astimezone(TZ).strftime('%Y-%m')
        n = sum(datetime.fromisoformat(r['created']).astimezone(TZ).strftime('%Y-%m') == month
                for r in con.execute("SELECT created FROM posts WHERE state != 'seed'"))
        if n >= CONFIG['monthly_post_limit']:
            raise ValueError('monthly_post_limit')
        dest = packet_path.parent / post_id
        dest.mkdir(exist_ok=True)
        manifest = dest / 'manifest.json'
        payload = {'id': post_id, 'format': 'single' if len(selected) == 1 else 'roundup',
                   'created_at': at.isoformat(), 'selected': selected, 'scenes': [],
                   'caption': '', 'review': 'pending', 'publish_enabled': False}
        manifest.write_text(json.dumps(payload, ensure_ascii=False, indent=2))
        con.execute('INSERT INTO posts VALUES (?,?,?,?)', (post_id, at.isoformat(), 'planned', str(manifest)))
        con.commit()
        return str(manifest)
    except Exception:
        con.rollback()
        raise


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--db', type=Path, default=HERE / 'runtime/ledger.sqlite3')
    sub = parser.add_subparsers(dest='cmd', required=True)
    p = sub.add_parser('collect'); p.add_argument('--out', type=Path, required=True)
    p = sub.add_parser('plan'); p.add_argument('packet', type=Path); p.add_argument('--matches', nargs='+')
    p = sub.add_parser('reserve'); p.add_argument('post'); p.add_argument('charge'); p.add_argument('credits', type=float); p.add_argument('balance', type=float)
    p = sub.add_parser('submitted'); p.add_argument('charge'); p.add_argument('job')
    p = sub.add_parser('ready'); p.add_argument('post')
    sub.add_parser('status')
    sub.add_parser('seed-pilot')
    args = parser.parse_args()
    if args.cmd == 'collect':
        packet = collect(); args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(packet, ensure_ascii=False, indent=2))
        print(json.dumps({k: v for k, v in packet.items() if k != 'candidates'}, ensure_ascii=False)); return
    con = database(args.db)
    if args.cmd == 'plan':
        print(plan(con, args.packet, args.matches))
    elif args.cmd == 'reserve':
        reserve(con, args.post, args.charge, args.credits, args.balance); print('RESERVED: submit exactly once')
    elif args.cmd == 'submitted':
        cur = con.execute("UPDATE charges SET job_id=?, state='submitted' WHERE id=? AND state='reserved'", (args.job, args.charge))
        if cur.rowcount != 1: raise ValueError('not_reserved')
        print('job recorded')
    elif args.cmd == 'ready':
        row = con.execute('SELECT * FROM posts WHERE id=?', (args.post,)).fetchone()
        if not row or row['state'] != 'planned': raise ValueError('not_planned')
        manifest = Path(row['manifest']); data = json.loads(manifest.read_text())
        if data.get('review') != 'passed' or not (manifest.parent / 'final.mp4').is_file():
            raise ValueError('render_and_visual_review_required')
        fixtures = fetch('/fixtures')
        current = {f['match_id']:f for group in fixtures.values() if isinstance(group,list) for f in group}
        for selected in data['selected']:
            fresh_fixture = current[selected['match_id']]
            fresh_prediction = fetch('/predictions/' + selected['match_id'])
            probabilities, _ = validate(fresh_fixture, fresh_prediction, now())
            old = selected['probabilities']
            if any(abs(a-b)>1e-8 for a,b in zip(probabilities,[old['home'],old['draw'],old['away']])):
                raise ValueError('probabilities_changed_rebuild_video')
            if any(fresh_fixture[k] != selected[k] for k in ('date','time','home_team','away_team')):
                raise ValueError('fixture_changed_rebuild_video')
        con.execute("UPDATE posts SET state='ready' WHERE id=?", (args.post,)); print('ready, not published')
    elif args.cmd == 'seed-pilot':
        con.execute("INSERT OR IGNORE INTO posts VALUES ('pilot-2026-10-03', '2026-10-03T10:35:54+00:00', 'seed', '')")
        con.execute("INSERT OR IGNORE INTO charges VALUES ('pilot-3817c6b6', 'pilot-2026-10-03', '2026-10-03T10:35:54+00:00', 15, '3817c6b6-c34e-47d7-99c3-c761b929d06e', 'submitted')")
        print('Existing pilot budgeted conservatively at quoted 15 credits')
    else:
        print(json.dumps({table: [dict(r) for r in con.execute('SELECT * FROM ' + table)] for table in ('posts', 'charges')}, indent=2))


if __name__ == '__main__':
    main()
