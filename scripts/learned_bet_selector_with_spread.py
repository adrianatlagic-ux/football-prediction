"""Selektor MIT den Einzelmodell-Merkmalen - der nachgeholte Teil."""
import sys, json; sys.path.insert(0,'/Users/doublea/Desktop/football-prediction/.claude/worktrees/jolly-hypatia-32d856')
import numpy as np, importlib.util
spec=importlib.util.spec_from_file_location("lbs","scripts/learned_bet_selector.py")
lbs=importlib.util.module_from_spec(spec); spec.loader.exec_module(lbs)

spread={(r['date'],r['home'],r['away']):r for r in
        (json.loads(l) for l in open('data/model_reports/predictor_spread.jsonl'))}
OUT={'home_win':0,'draw':1,'away_win':2}

def extra(cand, row):
    """Streuung der Einzelmodelle - fuer 1X2 direkt, sonst ueber die Richtung."""
    s=spread.get((row['date'],row['home'],row['away']))
    if not s: return [0.0,0.0,0.0,0.0]
    team=cand.get('team'); mk=cand['market']
    if mk=='1X2': i=OUT.get(cand['outcome'],0)
    elif team==row['home']: i=0
    elif team==row['away']: i=2
    else: i=1
    return [s['member_std'][i], s['member_range'][i],
            float(s['members_agree_argmax']),
            float(np.std([m[i] for m in s['members'].values()]))]

def build2(scope):
    rows=[json.loads(l) for l in open('data/model_reports/selection_comparison_20260923/decisions.jsonl')]
    from src.bet_audit import settlement
    out=[]
    for r in rows:
        if r['scope']!=scope: continue
        match=[]
        for c in r['candidates']:
            try: _,u = settlement(c, r['home'], r['away'], r['home_goals'], r['away_goals'])
            except Exception: continue
            f=lbs.features(c,r)
            base=[0.0 if (isinstance(f[k],float) and np.isnan(f[k])) else f[k] for k in lbs.FEATURE_ORDER]
            match.append({'x':base+extra(c,r),'profit':u,'season':r['season'],
                          'date':r['date'],'bet':c,'baseline':r['decisions'].get('kelly_baseline')})
        if match: out.append(match)
    return out

print(f"{'Scope':24} {'Merkmale':>9} {'MSE Mittel':>11} {'bestes MSE':>11}  Urteil")
for scope in ('1x2_preclosing','all_markets_preclosing','1x2_closing','all_markets_closing'):
    m=build2(scope)
    dev=[x for x in m if x[0]['season'] in lbs.DEV_SEASONS]
    hold=[x for x in m if x[0]['season'] in lbs.HOLDOUT_SEASONS]
    X=np.array([c['x'] for g in dev for c in g]); y=np.array([c['profit'] for g in dev for c in g])
    rng=np.random.default_rng(0); idx=rng.permutation(len(X)); folds=np.array_split(idx,5)
    def cv(a):
        e=[]
        for f in folds:
            tr=np.setdiff1d(idx,f)
            if a is None: e.append(np.mean((y[tr].mean()-y[f])**2))
            else: e.append(np.mean((lbs.predict(lbs.fit_ridge(X[tr],y[tr],a),X[f])-y[f])**2))
        return float(np.mean(e))
    mean_mse=cv(None)
    best=min(((cv(a),a) for a in (1,10,50,200,1000,5000,20000,100000)),key=lambda t:t[0])
    verdict="Merkmale helfen" if best[0]<mean_mse else "Merkmale helfen NICHT"
    mdl=lbs.fit_ridge(X,y,best[1]); r=lbs.evaluate(hold,mdl,0.0); b=lbs.baseline(hold)
    print(f"  {scope:22} {X.shape[1]:9d} {mean_mse:11.4f} {best[0]:11.4f}  {verdict}")
    print(f"    {'':20} Holdout: {r['bets']:3d} Wetten, ROI {r['roi']:+.1%} (Baseline {b['roi']:+.1%})")
