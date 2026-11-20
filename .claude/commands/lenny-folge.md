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

Use the brief's facts only. Never invent a tip, odds, score or amount.

| type | What happens |
|---|---|
| `pilot` | Rock bottom. Broken flat, 3.12 EUR, no plan. Ends wanting a way out. |
| `discovery` | His friend nails three games in a row with GoalIQ. Lenny sells his console, has `bankroll_after_eur`. |
| `preview` | He is going in on GoalIQ's first tip of `matchday.label`, stake `stake_eur`. Name one `big_games` fixture for colour. The tip itself is NOT known yet; say it drops in the GoalIQ app before kickoff. |
| `result` | Reveal `tip_text`, real `score`, real `odds`. `win`: celebrate, new bankroll. `loss`: crash, show it hurts. `push`: money back, relief. |
| `skip` | GoalIQ gave no tip; he kept his money (FOMO, or discipline paying off). |
| `broke` | Bankroll gone. Side hustle, `refill_eur` scraped together, comeback vow. |
| `lifestyle` | No matchday ahead. Life scene matching `mood` (party when up, ramen when down). |

Beats: **0-2 s hook** (instantly surprising image or line), **2-8 s story**,
**8-10 s cliffhanger** to the next episode. Selfie-vlog, he talks to camera.

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
