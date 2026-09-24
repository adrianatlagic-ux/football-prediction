"""Which selection criterion beats the others? None - random wins.

EV = model probability x odds - 1 is fully determined by the distance to the
market price, so ranking by EV ranks by disagreement with the market. That
disagreement turned out to be anti-predictive, which raises the obvious
question: does some other criterion carry the information instead?

This compares every criterion available from the numbers we hold, choosing
among the same three 1X2 candidates per match and judged by closing line
value rather than profit, because profit is far too noisy here.

    python3 scripts/compare_selection_criteria.py

Random choice is in the list on purpose: it is the bar a criterion has to
clear to be worth anything, and none of them clear it.
"""
import sys, json; sys.path.insert(0,'.')
import numpy as np, importlib.util
spec=importlib.util.spec_from_file_location("c","scripts/clv_target_selector.py")
m=importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
matches=m.build()
rng=np.random.default_rng(0)

def run(name, key):
    picks=[g[int(key(g))] for g in matches]
    clv=np.array([p['clv'] for p in picks])
    sims=clv[rng.integers(0,len(clv),(4000,len(clv)))].mean(1)
    print(f"  {name:38} n={len(clv):4d}  CLV {clv.mean():+.2%}  "
          f"[{np.percentile(sims,2.5):+.2%}, {np.percentile(sims,97.5):+.2%}]  "
          f"> Schluss {(clv>0).mean():5.1%}")

print("Auswahl unter denselben drei Kandidaten je Spiel:\n")
run("hoechster EV (heutige Regel)",      lambda g: np.argmax([c['x'][4] for c in g]))
run("NIEDRIGSTER EV (umgekehrt)",        lambda g: np.argmin([c['x'][4] for c in g]))
run("hoechste Modellwahrscheinlichkeit", lambda g: np.argmax([c['x'][0] for c in g]))
run("Marktfavorit (hoechste Marktwkt.)", lambda g: np.argmax([c['x'][1] for c in g]))
run("Zufall",                            lambda g: rng.integers(0,len(g)))
