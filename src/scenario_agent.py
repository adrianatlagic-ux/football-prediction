"""Generate the one-sentence match scenario via an LLM, strictly grounded in
our own computed stats - no web search, no outside knowledge, no invented
facts. The model only ever sees the numbers we hand it and is told to pick
the most decision-relevant ones rather than reciting everything.

Falls back to None (caller keeps the rule-based template scenario) if no API
key is configured or the call fails for any reason - this is an enhancement,
never a hard dependency.
"""
from __future__ import annotations

import json
import os
import re


def generate_ai_scenario(
    result: dict, home_team: str, away_team: str, is_knockout: bool = False,
) -> str | None:
    try:
        from dotenv import load_dotenv
        load_dotenv()
    except ImportError:
        pass

    api_key = os.getenv("GEMINI_API_KEY", "")
    if not api_key:
        return None
    try:
        from google import genai
    except ImportError:
        return None

    sp = result["score_prediction"]
    bm = sp["betting_markets"]
    flow = result["game_flow"]
    exp = result["explanation"]

    stats = {
        "win_probabilities": {
            home_team: result["probability_home_win"],
            "draw": result["probability_draw"],
            away_team: result["probability_away_win"],
        },
        "most_likely_score": sp["most_likely_score"],
        "win_by_2plus_goals_probability": {
            home_team: bm["win_margin"]["home_2plus"],
            away_team: bm["win_margin"]["away_2plus"],
        },
        "both_teams_to_score_probability": bm["btts"]["yes"],
        "over_2_5_goals_probability": bm["over_under"][1]["over"],
        "form_points_per_game_last_10": exp["form_last_10_avg_pts"],
        "win_rate_last_10": exp["win_rate_last_10"],
        "avg_goals_scored": exp["avg_goals_scored"],
        "avg_goals_conceded": exp["avg_goals_conceded"],
        "head_to_head_last_10": exp["h2h_last_10"],
        "dominance_index_positive_favors_home": flow["dominance_index"],
        "late_goal_after_75min_probability": flow["late_drama_probability"],
        "is_knockout_match": is_knockout,
    }

    prompt = f"""You are summarizing a football match prediction for {home_team} vs {away_team}.

Below is the ONLY data you may use. Do not invent any fact, statistic, player name, or piece of \
context that is not explicitly given here - this must be a strict, accurate summary of these \
numbers, nothing more.

{json.dumps(stats, indent=2)}

Pick the 2-3 most decision-relevant numbers above (not all of them) and write ONE sentence (max 30 \
words) giving a realistic, natural-sounding prognosis a football fan would find useful. Plain \
English, no jargon, don't spell out percentages woodenly - paraphrase naturally. Respond with ONLY \
the sentence, no quotes, no markdown."""

    try:
        client = genai.Client(api_key=api_key)
        response = client.models.generate_content(model="gemini-2.5-flash", contents=prompt)
        text = response.text.strip()
        text = re.sub(r'^["\']|["\']$', "", text).strip()
        return text or None
    except Exception:
        return None
