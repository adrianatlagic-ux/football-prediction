# Bundesliga prompt comparison, 25 October 2026

Two Sunday fixtures were evaluated once with each prompt, using the same cached
model prediction and the same odds snapshot (`2026-10-25T06:01:19Z`). Each
request used Google Search grounding and `gemini-3.8-flash`. The Main prompt
was taken from `origin/main`; only its obsolete model identifier was replaced
for this isolated test. The Branch prompt includes the full fresh candidate
set and compact model context. These test calls did not write picks into the
live application.

| Match | Main prompt | Branch prompt | Input candidates |
| --- | --- | --- | --- |
| TSG Hoffenheim – Bayer Leverkusen | Leverkusen win, 1X2 @ 2.15 | Leverkusen win, 1X2 @ 2.15 | Main 8, Branch 9 |
| SC Freiburg – Bayern Munich | Bayern win, 1X2 @ 1.45 | Over 3.5 goals @ 1.79 | Main 5, Branch 9 |

For Hoffenheim–Leverkusen, both responses pointed to Leverkusen's recent wins
and Hoffenheim's defence. For Freiburg–Bayern, the Branch response explicitly
rejected the 1.45 Bayern price in favour of the 1.79 total. The candidate list
and prompt changed together, so this two-match comparison cannot identify
which of those changes caused the different selection or which tip is better.

There were four successful paid generation requests, one per match and prompt.
The Main prompts used 1,118 and 971 input tokens; the Branch prompts used 1,322
and 1,271. An earlier Branch request using the old model name returned 404 and
no tip. At the end of the comparison, the production deployment still used
`gemini-2.5-flash` and showed `waiting_for_ai` for both fixtures. Deploying a
compatible model is necessary before Main can save its own live tips.
