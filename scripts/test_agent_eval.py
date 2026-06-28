"""Local test: ask Gemini (with Google Search grounding) for an independent match
evaluation, to see if it can catch context the stats model misses (table
constellation, motivation, lineups) - NOT a profit guarantee, just a sanity
check on whether the idea is even feasible before building it into the app.

Usage:
    python3 scripts/test_agent_eval.py
"""
import json
import os

from dotenv import load_dotenv
from google import genai
from google.genai import types

load_dotenv()

client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])

PROMPT_TEMPLATE = """You are a football betting analyst evaluating a World Cup 2026 match.

Match: {home} vs {away}
Our statistical model's prediction: Home win {ph:.0%}, Draw {pd:.0%}, Away win {pa:.0%}
Model's over/under 2.5 goals: Over {over:.0%}, Under {under:.0%}

Use web search to check for CURRENT context our stats model (which only uses historical
results) cannot see: lineups/injuries, recent form, and crucially the GROUP TABLE
SITUATION - is this a "dead rubber" (both teams already qualified/eliminated, nothing
to play for) or does the result matter for qualification? Tactical dead rubbers often
have fewer goals and more draws than a pure stats model expects, or vice versa if a
team needs a specific scoreline.

Give a short, concrete answer:
1. Does the table situation/motivation change anything? (yes/no + why, 2-3 sentences)
2. Your own independent prediction: most likely outcome and most likely
   over/under 2.5 lean.
3. Does your prediction AGREE or DISAGREE with the model's prediction above?
"""

MATCHES = [
    {
        "home": "Japan", "away": "Sweden",
        "ph": 0.5232, "pd": 0.253, "pa": 0.2238,
        "over": 0.81, "under": 0.19,
    },
    {
        "home": "Paraguay", "away": "Australia",
        "ph": 0.2951, "pd": 0.3267, "pa": 0.3782,
        "over": 0.68, "under": 0.32,
    },
]

for m in MATCHES:
    prompt = PROMPT_TEMPLATE.format(**m)
    print(f"\n{'='*70}\n{m['home']} vs {m['away']}\n{'='*70}")
    response = client.models.generate_content(
        model="gemini-2.5-flash",
        contents=prompt,
        config=types.GenerateContentConfig(
            tools=[types.Tool(google_search=types.GoogleSearch())],
        ),
    )
    print(response.text)
