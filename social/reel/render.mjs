// Renders one prediction reel from the live site's saved prediction.
//   node render.mjs <match_id>   ->  out/<match_id>.mp4 + out/<match_id>.txt (caption)
// Reads only the site's own API, so it spends no Odds API credit.
import { bundle } from '@remotion/bundler'
import { renderMedia, selectComposition } from '@remotion/renderer'
import { readFileSync, writeFileSync, mkdirSync } from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

const HERE = path.dirname(fileURLToPath(import.meta.url))
const API = process.env.SITE_API || 'https://football-prediction.fly.dev'
const SITE = 'goaliq.de'
const FRONTEND = path.join(HERE, '..', '..', 'frontend', 'src')

const COMPETITIONS = { bl: 'Bundesliga', cl: 'Champions League', nl: 'Nations League' }
const WEEKDAYS = ['So', 'Mo', 'Di', 'Mi', 'Do', 'Fr', 'Sa']

// Words that make TikTok/Instagram treat a post as gambling content (18+, off the
// For You feed) or that would promise money. The caption must not contain them.
const BLOCKED = /\b(wett\w*|quote\w*|tipp\w*|einsatz|sicher\w*|gewinn garant\w*|bet\w*|odds|tipico|bet365|bwin|interwetten|pinnacle|betano)\b/i

const json = f => JSON.parse(readFileSync(path.join(FRONTEND, f), 'utf8'))
const get = async url => {
  const r = await fetch(url)
  if (!r.ok) throw new Error(`${url} -> ${r.status}`)
  return r.json()
}

function hexDistance(a, b) {
  const n = h => [1, 3, 5].map(i => parseInt(h.slice(i, i + 2), 16))
  const [x, y] = [n(a), n(b)]
  return Math.hypot(x[0] - y[0], x[1] - y[1], x[2] - y[2])
}

async function buildProps(matchId) {
  const fixtures = await get(`${API}/fixtures`)
  const [comp, fixture] = Object.entries(fixtures)
    .flatMap(([c, list]) => list.map(f => [c, f]))
    .find(([, f]) => f.match_id === matchId) || []
  if (!fixture) throw new Error(`No fixture ${matchId}`)
  const pred = await get(`${API}/predictions/${matchId}`)

  const colors = json('team_colors.json')
  const names = json('team_names_de.json')
  const crests = json('club_crests.json')
  const side = team => ({
    name: names[team] || team,
    iso: colors[team]?.iso,
    crest: crests[team]?.logo,
    palette: colors[team]?.colors || ['#38bdf8'],
  })
  const h = side(fixture.home_team)
  const a = side(fixture.away_team)
  const homeColor = h.palette[0]
  const awayColor = a.palette.find(c => hexDistance(c, homeColor) > 120) || '#94a3b8'

  const d = new Date(`${fixture.date}T12:00:00`)
  const kickoff = `${WEEKDAYS[d.getDay()]} ${fixture.date.slice(8, 10)}.${fixture.date.slice(5, 7)}. · ${fixture.time}`
  const sp = pred.score_prediction
  const st = pred.game_flow.predicted_stats
  const top = sp.top_scorelines[0]

  return {
    matchId,
    home: h.name, away: a.name,
    homeIso: h.iso, awayIso: a.iso, homeCrest: h.crest, awayCrest: a.crest,
    homeColor, awayColor,
    competition: COMPETITIONS[comp] || comp,
    kickoff,
    pHome: pred.probability_home_win, pDraw: pred.probability_draw, pAway: pred.probability_away_win,
    score: top.score, scoreProb: top.probability,
    stats: [
      { label: 'Erwartete Tore', home: sp.home_xg, away: sp.away_xg },
      { label: 'Ballbesitz', home: st.possession.home, away: st.possession.away, suffix: '%' },
      { label: 'Schüsse', home: st.shots.home, away: st.shots.away },
      { label: 'Ecken', home: st.corners.home, away: st.corners.away },
    ],
    site: SITE,
  }
}

function caption(p) {
  const fav = p.pHome >= p.pAway ? p.home : p.away
  const favP = Math.round(Math.max(p.pHome, p.pAway) * 100)
  const tag = s => '#' + s.replace(/[^\p{L}\p{N}]/gu, '')
  const text = [
    `${p.home} vs ${p.away}: Die KI sieht ${fav} bei ${favP} %. Wahrscheinlichstes Ergebnis ${p.score}.`,
    'Liegt sie richtig? Schreib dein Ergebnis in die Kommentare 👇',
    `Alle Prognosen: goaliq.de (Link in Bio)`,
    '',
    [tag(p.competition), tag(p.home), tag(p.away), '#fußball', '#ki', '#prognose', '#goaliq'].join(' '),
  ].join('\n')
  if (BLOCKED.test(text)) throw new Error(`Caption contains a blocked word: ${text.match(BLOCKED)[0]}`)
  return text
}

const matchId = process.argv[2]
if (!matchId) { console.error('usage: node render.mjs <match_id>'); process.exit(1) }

const props = await buildProps(matchId)
const out = path.join(HERE, 'out')
mkdirSync(out, { recursive: true })
writeFileSync(path.join(out, `${matchId}.txt`), caption(props))
writeFileSync(path.join(HERE, 'src', 'sample.json'), JSON.stringify(props, null, 2))

const serveUrl = await bundle({ entryPoint: path.join(HERE, 'src', 'index.jsx') })
const composition = await selectComposition({ serveUrl, id: 'Reel', inputProps: props })
await renderMedia({
  composition, serveUrl, codec: 'h264', inputProps: props,
  outputLocation: path.join(out, `${matchId}.mp4`),
})
console.log(`Rendered out/${matchId}.mp4`)
