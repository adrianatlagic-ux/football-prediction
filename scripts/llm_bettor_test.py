"""Can a language model, given every signal we have, pick better than the market?

The proposal: hand an LLM all our numbers - the model's probabilities, how far
the individual models disagree, the market's prices, where a bookmaker sits
above Pinnacle, the clubs' squad values - and let it weigh them the way an
experienced bettor would, instead of following either the model or the price.

    python3 scripts/llm_bettor_test.py                 # run (cached answers reused)
    python3 scripts/llm_bettor_test.py --report-only   # evaluate saved answers

Two things make this fair.

The teams are hidden. Every match here was played before the model's training
cut-off, so a model shown "Bayern v Dortmund, 2024-03-30" may simply remember
who won and look brilliant for it. Here it sees "home side" and "away side",
no date, no competition name - only the numbers. It has to reason from them.

The protocol is fixed before any answer is read: the 2023-24 and 2025-26
seasons (455 matches), two prompts run on identical inputs, judged on
closing-line value against Pinnacle's margin-free close and on the Brier score
of the probabilities it states. Baselines on the same matches: a random pick,
the market favourite, our model's highest-EV pick.

Two prompts, because the second is the hypothesis being tested: a neutral
quantitative analyst, and an agent written as the most successful professional
football bettor alive, with his record and principles as its biography. If the
persona carries anything, it shows up as a difference between the two.

What is not in here: short-term news research. There is no archive of it from
before these matches were played, and reconstructing it now would leak the
outcome through every match report written since.
"""
from __future__ import annotations

import argparse
import json
import os
import random
import re
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))
from pinnacle_plus_model_test import load_odds, DECISIONS

OUT = ROOT / "data/model_reports/llm_bettor"
CACHE = OUT / "responses.jsonl"
HOLD = ("2023-24", "2025-26")
OUTCOMES = ("home", "draw", "away")
IDX = {"home_win": 0, "draw": 1, "away_win": 2}
SPREAD = ROOT / "data/model_reports/predictor_spread.jsonl"

ANALYST = """You are a careful quantitative football betting analyst. You are given
the numbers available before one match and must decide whether any 1X2 bet is
worth placing, and if so which. Judge only from the numbers provided."""

LEGEND = """You are the most successful professional football bettor alive.

Your record: three decades of profit. You began as a mathematician who noticed
that football prices were set by instinct, built your own ratings, and turned a
small bankroll into a syndicate that now moves millions a season. Bookmakers
have closed more accounts of yours than you can count - the surest sign you
were right. You have lived through long losing runs and never changed your
method because of them.

Your principles, earned the hard way:
- You never bet on who will win. You bet on prices that are wrong.
- The closing price of the sharpest bookmaker is the best estimate of truth
  there is. Beating it consistently is the only proof of skill; results in the
  short run are noise.
- Your own ratings are one opinion. When they disagree sharply with a sharp
  market, the market is usually right and you check your ratings.
- Most matches offer nothing. Passing is a decision, and usually the right one.
- Favourites are overbet by the public, draws are underbet, long shots are
  priced for dreamers.
- Size bets to your edge. No edge, no bet.

You are given the numbers available before one match. Decide as you always
have."""

PROMPTS = {"analyst": ANALYST, "legend": LEGEND}


def pct(x):
    return f"{x * 100:.1f}%"


def build_matches():
    odds = load_odds()
    spread = {}
    if SPREAD.exists():
        for line in SPREAD.open():
            r = json.loads(line)
            spread[(r["date"], r["home"], r["away"])] = r
    from src.club_market_value_policy import MarketValueHistory
    history = MarketValueHistory()

    matches = []
    for row in (json.loads(l) for l in DECISIONS.open()):
        if row["scope"] != "1x2_preclosing" or row["season"] not in HOLD:
            continue
        key = (row["date"], row["home"], row["away"])
        o = odds.get(key)
        if not o:
            continue
        model = [None, None, None]
        for c in row["candidates"]:
            if c["outcome"] in IDX:
                model[IDX[c["outcome"]]] = float(c["probability"])
        if None in model:
            continue
        s = spread.get(key)
        try:
            hv = history.value(row["home"], row["date"])
            av = history.value(row["away"], row["date"])
        except Exception:
            hv = av = None
        matches.append({"id": f"{row['date']}|{row['home']}|{row['away']}", "season": row["season"],
                        "model": model, "fair": o["fair"], "close": o["close"], "max": o["max"],
                        "result": {"H": 0, "D": 1, "A": 2}[o["result"]],
                        "spread": s["member_std"] if s else None,
                        "agree": s.get("members_agree_argmax") if s else None,
                        "home_value": hv, "away_value": av})
    return matches


def describe(m):
    """The match as the model sees it: numbers only, no names, no date."""
    lines = ["Match: home side vs away side (identities withheld).", ""]
    lines.append("Our statistical model's probabilities:")
    for i, name in enumerate(OUTCOMES):
        lines.append(f"  {name}: {pct(m['model'][i])}")
    if m["spread"]:
        lines.append(f"Disagreement between the model's three internal members (std dev): "
                     + ", ".join(f"{n} {pct(v)}" for n, v in zip(OUTCOMES, m["spread"])))
        if m["agree"] is not None:
            lines.append(f"Members agree on the favourite: {'yes' if m['agree'] else 'no'}")
    lines.append("")
    lines.append("Sharp market (Pinnacle), margin removed - the market's probability:")
    for i, name in enumerate(OUTCOMES):
        lines.append(f"  {name}: {pct(m['fair'][i])}  (fair odds {1 / m['fair'][i]:.2f})")
    lines.append("Best price available at any bookmaker:")
    for i, name in enumerate(OUTCOMES):
        gap = m["max"][i] * m["fair"][i] - 1
        lines.append(f"  {name}: {m['max'][i]:.2f}  ({gap:+.1%} against the sharp fair price)")
    if m["home_value"] and m["away_value"]:
        lines.append("")
        lines.append(f"Squad market value: home {m['home_value'] / 1e6:.0f}m EUR, "
                     f"away {m['away_value'] / 1e6:.0f}m EUR")
    lines.append("")
    lines.append('Reply with raw JSON only: {"probabilities": {"home": 0.0, "draw": 0.0, "away": 0.0}, '
                 '"pick": "home|draw|away|none", "reason": "one sentence"}. '
                 'Probabilities must sum to 1. "pick" is the bet you would place at the best '
                 'price listed, or "none".')
    return "\n".join(lines)


def ask(client, types, persona, prompt):
    response = client.models.generate_content(
        model="gemini-2.5-flash", contents=prompt,
        config=types.GenerateContentConfig(system_instruction=PROMPTS[persona],
                                           response_mime_type="application/json"))
    text = re.sub(r"^```(?:json)?|```$", "", (response.text or "").strip(), flags=re.M).strip()
    parsed = json.loads(text)
    probs = parsed.get("probabilities") or {}
    p = [float(probs.get(k, 0) or 0) for k in OUTCOMES]
    total = sum(p)
    if total <= 0:
        raise ValueError("no probabilities")
    pick = parsed.get("pick")
    return {"probabilities": [x / total for x in p],
            "pick": pick if pick in OUTCOMES else "none",
            "reason": (parsed.get("reason") or "")[:200]}


def collect(matches):
    done = {}
    if CACHE.exists():
        for line in CACHE.open():
            r = json.loads(line)
            done[(r["id"], r["persona"])] = r
    todo = [(m, p) for m in matches for p in PROMPTS if (m["id"], p) not in done]
    print(f"{len(done)} Antworten gespeichert, {len(todo)} offen")
    if not todo:
        return done

    from google import genai
    from google.genai import types
    client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])

    def work(item):
        m, persona = item
        for attempt in range(3):
            try:
                return {"id": m["id"], "persona": persona, **ask(client, types, persona, describe(m))}
            except Exception as exc:
                last = exc
        return {"id": m["id"], "persona": persona, "error": f"{type(last).__name__}: {last}"[:200]}

    with CACHE.open("a") as fh, ThreadPoolExecutor(8) as pool:
        for n, result in enumerate(pool.map(work, todo), 1):
            fh.write(json.dumps(result) + "\n"); fh.flush()
            done[(result["id"], result["persona"])] = result
            if n % 100 == 0:
                print(f"  {n}/{len(todo)}", flush=True)
    return done


def evaluate(matches, answers):
    rng = np.random.default_rng(0)
    rand = random.Random(0)

    def outcome(m, i):
        price = m["max"][i]
        return {"clv": price * m["close"][i] - 1,
                "profit": price - 1 if m["result"] == i else -1.0}

    def stats(label, bets, n_matches):
        if not bets:
            print(f"  {label:34} {0:5}"); return None
        c = np.array([b["clv"] for b in bets]); p = np.array([b["profit"] for b in bets])
        ci = np.percentile(c[rng.integers(0, len(c), (4000, len(c)))].mean(1), [2.5, 97.5])
        pci = np.percentile(p[rng.integers(0, len(p), (4000, len(p)))].mean(1), [2.5, 97.5])
        print(f"  {label:34} {len(bets):5} {len(bets) / n_matches:6.0%}  "
              f"CLV {c.mean():+6.2%} [{ci[0]:+6.2%},{ci[1]:+6.2%}]  "
              f"ROI {p.mean():+6.1%} [{pci[0]:+6.1%},{pci[1]:+6.1%}]")
        return {"bets": len(bets), "clv": float(c.mean()), "clv_ci": list(map(float, ci)),
                "roi": float(p.mean()), "roi_ci": list(map(float, pci))}

    def brier(probs, m):
        return sum((probs[i] - (1 if m["result"] == i else 0)) ** 2 for i in range(3))

    report = {}
    n = len(matches)
    print(f"\n{n} Spiele, Pruefjahre {', '.join(HOLD)}. Wettpreis: bester verfuegbarer.\n")
    print(f"  {'Verfahren':34} {'Wetten':>5} {'Anteil':>6}  CLV (95%)                  ROI (95%)")
    report["random"] = stats("Zufall", [outcome(m, rand.randrange(3)) for m in matches], n)
    report["market_favourite"] = stats("Marktfavorit", [outcome(m, int(np.argmax(m["fair"]))) for m in matches], n)
    report["model_best_ev"] = stats("Modell, hoechster EV",
                                    [outcome(m, int(np.argmax([m["model"][i] * m["max"][i] for i in range(3)])))
                                     for m in matches], n)
    report["pinnacle_gap_2pct"] = stats("Preis >2% ueber Pinnacle",
                                        [outcome(m, i) for m in matches for i in range(3)
                                         if m["max"][i] * m["fair"][i] - 1 > 0.02], n)
    print()
    errors = {}
    for persona in PROMPTS:
        bets, errs = [], 0
        for m in matches:
            a = answers.get((m["id"], persona))
            if not a or "error" in a:
                errs += 1; continue
            if a["pick"] != "none":
                bets.append(outcome(m, OUTCOMES.index(a["pick"])))
        errors[persona] = errs
        label = {"analyst": "KI: nuechterner Analyst", "legend": "KI: bester Wetter der Welt"}[persona]
        report[f"llm_{persona}"] = stats(label, bets, n)

    print("\n  Wie gut sagt jeder den AUSGANG vorher? (Brier, kleiner ist besser)")
    rows = [("Pinnacle-Schlussquote (Markt)", [m["close"] for m in matches], matches),
            ("Pinnacle vor Schluss", [m["fair"] for m in matches], matches),
            ("unser Modell", [m["model"] for m in matches], matches)]
    for persona in PROMPTS:
        ok = [(answers[(m["id"], persona)]["probabilities"], m) for m in matches
              if (m["id"], persona) in answers and "error" not in answers[(m["id"], persona)]]
        label = {"analyst": "KI: nuechterner Analyst", "legend": "KI: bester Wetter der Welt"}[persona]
        rows.append((label, [p for p, _ in ok], [m for _, m in ok]))
    for label, probs, ms in rows:
        b = np.mean([brier(p, m) for p, m in zip(probs, ms)])
        report[f"brier|{label}"] = float(b)
        print(f"    {label:34} {b:.4f}   ({len(ms)} Spiele)")
    if any(errors.values()):
        print(f"\n  Fehlgeschlagene Antworten: {errors}")
    (OUT / "results.json").write_text(json.dumps({"matches": n, "results": report,
                                                  "errors": errors}, indent=2) + "\n")
    print(f"\ngeschrieben: {(OUT / 'results.json').relative_to(ROOT)}")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--report-only", action="store_true")
    args = ap.parse_args()
    matches = build_matches()
    OUT.mkdir(parents=True, exist_ok=True)
    answers = {}
    if CACHE.exists():
        for line in CACHE.open():
            r = json.loads(line); answers[(r["id"], r["persona"])] = r
    if not args.report_only:
        answers = collect(matches)
    evaluate(matches, answers)


if __name__ == "__main__":
    main()
