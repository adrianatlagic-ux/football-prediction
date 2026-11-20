Produce the next Lenny Zero episode from GoalIQ's real tips and results.

Usage: `/lenny-folge`

Lenny Zero is a fictional, photorealistic AI influencer (English, light German
accent). The story is decided by `social/lenny/lenny.py` from the real logs;
you only write and produce it. Concept and decisions: `social/influencer/KONZEPT.md`.

## 1. Ask the bot

```bash
git pull --ff-only
python3 social/lenny/lenny.py next > /tmp/lenny-brief.json
cat /tmp/lenny-brief.json
```

If `type` is `none`: stop. Report the `reason` in one line. Spend nothing.

## 2. Write the script (10 seconds, about 22-26 spoken words, English)

**Every episode is about Lenny's life, not about betting.** The viewer must *see*
his life change from episode to episode. The bet is the engine in the background:
at most **one short line**, said in passing.

Build the scene from the brief's `life_stage` (`home`, `transport`, `outfit`,
`food`, `social`). Use these exact settings so the progression stays consistent
across episodes. If `life_change` is:
- `up`: the episode is about the upgrade itself (moving in, first ride in the car, new crowd).
- `down`: the episode is about losing it (moving back, selling the car, friends gone quiet).
- `same`: an everyday moment in his current life that shows its texture.

What the bet contributes per `type` (the one side line):

| type | Side line about money / the bet |
|---|---|
| `pilot` | None. Rock bottom, 3.12 EUR, no plan, wants a way out. |
| `discovery` | His mate keeps being right with the GoalIQ app; Lenny sold his console for a stake. |
| `preview` | He is in on GoalIQ's tip for `matchday.label` this weekend (tip not known yet, never invent it). |
| `result` | The real outcome in a few words: `tip_text`, `score`, won or lost. |
| `skip` | GoalIQ had no tip, so he sat it out. |
| `broke` | The money is gone; side hustle, scraped `refill_eur` together. |
| `lifestyle` | None, or a passing mention of the bankroll. |

Never invent a tip, odds, score or amount; use only the brief's facts.

Beats: **0-2 s hook** (an instantly surprising image or line from his life),
**2-8 s life scene**, **8-10 s cliffhanger**. Selfie-vlog, he talks to camera.

Hard rules:
- Never say or imply "guaranteed", "sure win", "easy money", "this is how you get rich".
- No bookmaker names, no odds links, no call to bet. GoalIQ is mentioned as the app he follows.
- Real footballers only in the background (stadium, pitch, TV), never interacting with Lenny, never near betting or the app.
- Losses are shown honestly. They are part of the story.

## 3. Voice (ElevenLabs)

- Voice: `character.elevenlabs_voice_id` from `social/lenny/config.json`. If it is null, stop and ask the user to design and save the voice first.
- Generate the line with `creative_generate_speech`, poll until done, keep the audio URL.

## 4. Video (Higgsfield, one attempt, budget from config)

- `balance` first; stop if credits < `video.max_credits`.
- Import the audio with `media_import_url`.
- Model `seedance_2_0_mini`, `duration` 10, `resolution` 720p, `aspect_ratio` 9:16,
  `image_references` = the character sheet job (`character.higgsfield_sheet_job_id`),
  `audio_references` = the imported audio so the lips follow the voice.
- `estimate_video_cost` with exactly these params; if it is above `video.max_credits`, stop and report.
- Generate once. Never retry automatically; a failed run is reported, not repeated.

## 5. Record and hand over

- Save the brief, script, audio URL, video job id and credits to
  `social/lenny/episodes/<episode>.json`, and the caption to `social/lenny/episodes/<episode>.txt`
  (English, 1-2 lines, matchday + hook, `goaliq.de`, max 4 hashtags).
- Only after the video succeeded: `python3 social/lenny/lenny.py commit /tmp/lenny-brief.json`
- Commit `social/lenny/` and push.
- Tell the user: episode number and type, the video link, the caption, credits left.
  Remind them to switch on Instagram's AI label when posting.
