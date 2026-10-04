import { useState, useEffect, useRef } from 'react'
import axios from 'axios'
import './App.css'
import CL_FIXTURES from './cl_fixtures.json'
import BL_FIXTURES from './bl_fixtures.json'
import NL_FIXTURES from './nl_fixtures.json'
import CLUB_CRESTS from './club_crests.json'
import TEAM_COLORS from './team_colors.json'
import TEAM_NAMES_DE from './team_names_de.json'

const API_BASE = import.meta.env.VITE_API_BASE ?? (import.meta.env.DEV ? 'http://127.0.0.1:8000' : '')
// The one bookmaker the user bets with (api/app.py USER_BOOK_KEY).
const USER_BOOK_KEY = 'betathome'

// Champions League stages in tournament order (2024/25+ format: a single
// 36-team league phase, then a knockout bracket) - a plain alphabetical sort
// would misorder these, so sort explicitly.
const STAGE_ORDER = ['League Phase', 'Knockout Playoffs', 'Round of 16', 'Quarter-finals', 'Semi-finals', 'Final']
const GROUPS = [...new Set(CL_FIXTURES.map(f => f.group))].sort((a, b) => {
  const ai = STAGE_ORDER.indexOf(a)
  const bi = STAGE_ORDER.indexOf(b)
  if (ai !== -1 && bi !== -1) return ai - bi
  if (ai !== -1) return -1
  if (bi !== -1) return 1
  return a.localeCompare(b)
})

function fixtureDateTime(f) {
  return new Date(`${f.date}T${f.time}:00`)
}

// The page's language: German by default, English on request (the switch at
// the top right), remembered in the browser. Every text a visitor reads goes
// through tr(german, english); changing LANG re-renders the whole app.
let LANG = (() => { try { return localStorage.getItem('goaliq-lang') === 'en' ? 'en' : 'de' } catch { return 'de' } })()
const tr = (de, en) => (LANG === 'en' ? en : de)
const LOCALE = () => (LANG === 'en' ? 'en-GB' : 'de-DE')
const DEC = () => (LANG === 'en' ? '.' : ',')

// Teams keep their English key everywhere (fixtures, odds, colours); only
// the name a visitor reads is German - in English the key itself.
const teamName = name => (LANG === 'en' ? name : (TEAM_NAMES_DE[name] || name))
// 1.79 -> "1,79" in German, unchanged in English
const deNum = v => String(v ?? '').replace('.', DEC())

// "Do 01.10. · 20:45" / "Thu 01/10 · 20:45"
function fixtureWhen(f) {
  const d = new Date(`${f.date}T12:00:00`)
  const weekday = d.toLocaleDateString(LOCALE(), { weekday: 'short' }).replace('.', '')
  return LANG === 'en'
    ? `${weekday} ${f.date.slice(8, 10)}/${f.date.slice(5, 7)} · ${f.time}`
    : `${weekday} ${f.date.slice(8, 10)}.${f.date.slice(5, 7)}. · ${f.time}`
}

const STAGE_NAMES_DE = {
  'League Phase': 'Ligaphase', 'Knockout Playoffs': 'K.-o.-Playoffs', 'Round of 16': 'Achtelfinale',
  'Quarter-finals': 'Viertelfinale', 'Semi-finals': 'Halbfinale', 'Final': 'Finale',
}
const WEEKDAYS_DE = { Mon: 'Mo', Tue: 'Di', Wed: 'Mi', Thu: 'Do', Fri: 'Fr', Sat: 'Sa', Sun: 'So' }
const MONTHS_DE = { Jan: 'Jan', Feb: 'Feb', Mar: 'März', Apr: 'Apr', May: 'Mai', Jun: 'Juni', Jul: 'Juli',
                    Aug: 'Aug', Sep: 'Sep', Oct: 'Okt', Nov: 'Nov', Dec: 'Dez' }

// Tab names come from the fixture feed: "Matchday 3", "Fri 02 Oct", "League Phase".
function groupLabel(g) {
  if (LANG === 'en') return g.length === 1 ? `Group ${g}` : g
  if (g.length === 1) return `Gruppe ${g}`
  if (STAGE_NAMES_DE[g]) return STAGE_NAMES_DE[g]
  const md = g.match(/^Matchday (\d+)$/)
  if (md) return `Spieltag ${md[1]}`
  const day = g.match(/^(\w{3}) (\d{2}) (\w{3})$/)
  if (day && WEEKDAYS_DE[day[1]]) return `${WEEKDAYS_DE[day[1]]} ${day[2]}. ${MONTHS_DE[day[3]] || day[3]}`
  return g
}

// The game-flow engine labels matches in English (src/game_flow.py).
const MATCH_TYPES_DE = {
  'Goal Fest': 'Torfestival', 'One-Sided': 'Einseitig', 'Balanced & Open': 'Offen & ausgeglichen',
  'Controlled': 'Kontrolliert', 'Tactically Balanced': 'Taktisch ausgeglichen', 'Defensive Battle': 'Abwehrschlacht',
}
const MATCH_DESCRIPTIONS_DE = {
  'A very open game with plenty of chances expected': 'Ein sehr offenes Spiel mit vielen Chancen erwartet',
  'One team is expected to dominate clearly': 'Ein Team dürfte das Spiel klar dominieren',
  'Both teams play attacking football at an even level': 'Beide Teams spielen offensiv auf Augenhöhe',
  'The favorite controls the game against little resistance': 'Der Favorit kontrolliert das Spiel gegen wenig Widerstand',
  'A tight game where goals will make the difference': 'Ein enges Spiel, in dem einzelne Tore entscheiden',
  'Few chances expected, a single goal could be decisive': 'Wenige Chancen erwartet, ein Tor könnte entscheiden',
}

// "Next Games" = the current matchday window: 15:00 until 06:00 the next morning.
// Before 06:00 we're still inside last evening's window; otherwise it's today's.
function nextGamesWindow(now = new Date()) {
  const start = new Date(now)
  const end = new Date(now)
  if (now.getHours() < 6) {
    start.setDate(start.getDate() - 1)
    start.setHours(15, 0, 0, 0)
    end.setHours(6, 0, 0, 0)
  } else {
    start.setHours(15, 0, 0, 0)
    end.setDate(end.getDate() + 1)
    end.setHours(6, 0, 0, 0)
  }
  return [start, end]
}

const [_NG_START, _NG_END] = nextGamesWindow()
const BL_GROUPS = [...new Set(BL_FIXTURES.map(f => f.group))]
const NL_GROUPS = [...new Set(NL_FIXTURES.map(f => f.group))]

const COMPETITIONS = {
  cl: { label: 'Champions League', fixtures: CL_FIXTURES, groups: GROUPS,
        sportKey: 'soccer_uefa_champs_league',
        logo: 'https://a.espncdn.com/i/leaguelogos/soccer/500-dark/2.png' },
  bl: { label: 'Bundesliga', fixtures: BL_FIXTURES, groups: BL_GROUPS,
        sportKey: 'soccer_germany_bundesliga', emoji: '\u{1F1E9}\u{1F1EA}' },
  nl: { label: 'Nations League', fixtures: NL_FIXTURES, groups: NL_GROUPS,
        sportKey: 'soccer_uefa_nations_league', emoji: '\u{1F30D}' },
}

// Fixtures come from the server (GET /fixtures, rebuilt daily from ESPN), so
// a new matchday appears without a redeploy; the bundled files above are only
// the fallback. The whole season is listed, but a prediction is shown from
// PREDICTION_LEAD_HOURS before kickoff - the window the daily job predicts in
// with every result up to then. Tabs cover the matchdays around today.
const PREDICTION_LEAD_HOURS = 48
// A played matchday stays a week for its results, then leaves the list.
const TAB_PAST_DAYS = 7
const TAB_AHEAD_DAYS = 21
const MAX_TABS = 8

function groupsAroundToday(fixtures, now = new Date()) {
  const byGroup = new Map()
  for (const f of fixtures) {
    const t = fixtureDateTime(f)
    const g = byGroup.get(f.group) || { first: t, last: t }
    byGroup.set(f.group, { first: t < g.first ? t : g.first, last: t > g.last ? t : g.last })
  }
  const from = new Date(now.getTime() - TAB_PAST_DAYS * 86400000)
  const to = new Date(now.getTime() + TAB_AHEAD_DAYS * 86400000)
  const ordered = [...byGroup.entries()].sort((a, b) => a[1].first - b[1].first)
  const distance = g => Math.min(Math.abs(g.first - now), Math.abs(g.last - now))
  const inWindow = ordered.filter(([, g]) => g.last >= from && g.first <= to)
  // The Nations League has a tab per day; keep the ones closest to today.
  const kept = new Set([...inWindow].sort((a, b) => distance(a[1]) - distance(b[1])).slice(0, MAX_TABS).map(([n]) => n))
  const near = ordered.map(([name]) => name).filter(name => kept.has(name))
  // Between seasons nothing is near: show the next groups instead.
  return near.length ? near : ordered.filter(([, g]) => g.last >= now).slice(0, 2).map(([name]) => name)
}

function applyServerFixtures(data) {
  for (const [key, competition] of Object.entries(COMPETITIONS)) {
    const fixtures = data?.[key]
    if (Array.isArray(fixtures) && fixtures.length) {
      competition.fixtures = fixtures
      competition.groups = groupsAroundToday(fixtures)
    }
  }
}

function predictionOpensAt(fixture) {
  return new Date(fixtureDateTime(fixture).getTime() - PREDICTION_LEAD_HOURS * 3600000)
}

// "Next games" follows whichever competition is on screen: showing Champions
// League kickoffs while the Nations League tab is open would just look broken.
function nextGamesFor(fixtures) {
  return fixtures
    .filter(f => { const d = fixtureDateTime(f); return d >= _NG_START && d < _NG_END })
    .sort((a, b) => fixtureDateTime(a) - fixtureDateTime(b))
}

function excitementScore(data) {
  const probs = [data.probability_home_win, data.probability_draw, data.probability_away_win]
  const balance = 1 - Math.max(...probs)
  const drama = data.game_flow?.late_drama_probability || 0
  const totalXg = data.game_flow?.total_xg
    ?? ((data.score_prediction?.home_xg || 0) + (data.score_prediction?.away_xg || 0))
  return balance * 2 + drama + totalXg * 0.3
}

// "Hot Game" = the matchup of the day with the most star power (top-ranked
// teams facing each other), with the AI excitement score as a tiebreaker.
// The day's top games: the two most exciting by the model (one when only
// one game is on).
function getHotFixtures(predictionsById, fixtures, count = 2) {
  return [...fixtures]
    .map(f => ({ f, score: predictionsById[f.match_id] ? excitementScore(predictionsById[f.match_id]) : -1 }))
    .sort((a, b) => b.score - a.score)
    .slice(0, count)
    .map(x => x.f)
}

const TEAM_FLAGS = {
  'Algeria': '🇩🇿',
  'Argentina': '🇦🇷',
  'Australia': '🇦🇺',
  'Austria': '🇦🇹',
  'Belgium': '🇧🇪',
  'Bosnia and Herzegovina': '🇧🇦',
  'Brazil': '🇧🇷',
  'Canada': '🇨🇦',
  'Cape Verde': '🇨🇻',
  'Colombia': '🇨🇴',
  'Croatia': '🇭🇷',
  'Curacao': '🇨🇼',
  'Czech Republic': '🇨🇿',
  'DR Congo': '🇨🇩',
  'Ecuador': '🇪🇨',
  'Egypt': '🇪🇬',
  'England': '🏴󠁧󠁢󠁥󠁮󠁧󠁿',
  'France': '🇫🇷',
  'Germany': '🇩🇪',
  'Ghana': '🇬🇭',
  'Haiti': '🇭🇹',
  'Iran': '🇮🇷',
  'Iraq': '🇮🇶',
  'Ivory Coast': '🇨🇮',
  'Japan': '🇯🇵',
  'Jordan': '🇯🇴',
  'Mexico': '🇲🇽',
  'Morocco': '🇲🇦',
  'Netherlands': '🇳🇱',
  'New Zealand': '🇳🇿',
  'Norway': '🇳🇴',
  'Panama': '🇵🇦',
  'Paraguay': '🇵🇾',
  'Portugal': '🇵🇹',
  'Qatar': '🇶🇦',
  'Saudi Arabia': '🇸🇦',
  'Scotland': '🏴󠁧󠁢󠁳󠁣󠁴󠁿',
  'Senegal': '🇸🇳',
  'South Africa': '🇿🇦',
  'South Korea': '🇰🇷',
  'Spain': '🇪🇸',
  'Sweden': '🇸🇪',
  'Switzerland': '🇨🇭',
  'Tunisia': '🇹🇳',
  'Turkey': '🇹🇷',
  'United States': '🇺🇸',
  'Uruguay': '🇺🇾',
  'Uzbekistan': '🇺🇿',
}

function TeamLabel({ name }) {
  const iso = TEAM_COLORS[name]?.iso
  if (iso) {
    return (
      <>
        <img src={`https://flagcdn.com/w40/${iso}.png`} alt="" className="team-crest team-flag"
             onError={(e) => { e.currentTarget.style.display = 'none' }} />
        {teamName(name)}
      </>
    )
  }
  const crest = CLUB_CRESTS[name]
  if (crest) {
    return (
      <>
        <img
          src={crest.logo}
          alt=""
          className="team-crest"
          onError={(e) => { e.currentTarget.style.display = 'none' }}
        />
        {teamName(name)}
      </>
    )
  }
  const flag = TEAM_FLAGS[name]
  return <>{flag && <span style={{ marginRight: '0.4em' }}>{flag}</span>}{teamName(name)}</>
}


// Team colours come from team_colors.json (scripts/build_team_colors.py): a
// nation's flag colours, a club's own colour plus its crest's. The draw is
// always grey, so neither team may take a colour close to it.
const DRAW_GREY = '#6b7280'

function hexColorDistance(a, b) {
  if (!/^#[0-9a-f]{6}$/i.test(a) || !/^#[0-9a-f]{6}$/i.test(b)) return Infinity
  const pa = parseInt(a.slice(1), 16), pb = parseInt(b.slice(1), 16)
  const dr = ((pa >> 16) & 255) - ((pb >> 16) & 255)
  const dg = ((pa >> 8) & 255) - ((pb >> 8) & 255)
  const db = (pa & 255) - (pb & 255)
  return Math.sqrt(dr * dr + dg * dg + db * db)
}

// Navy or black would vanish on the dark page; lift them toward white.
function readableColor(hex) {
  const n = parseInt(hex.slice(1), 16)
  const rgb = [(n >> 16) & 255, (n >> 8) & 255, n & 255]
  const luminance = (0.2126 * rgb[0] + 0.7152 * rgb[1] + 0.0722 * rgb[2]) / 255
  if (luminance >= 0.18) return hex
  const lifted = rgb.map(c => Math.round(c + (255 - c) * 0.35))
  return '#' + lifted.map(c => c.toString(16).padStart(2, '0')).join('')
}

function teamColors(name) {
  return (TEAM_COLORS[name]?.colors || []).map(readableColor)
}

// Each side takes its first colour that is clearly not the draw grey; the
// away side also skips colours too close to the home side's, falling back to
// its flag's or crest's next colour (Germany red vs England red: Germany gold).
function getMatchColors(homeTeam, awayTeam) {
  const clear = c => hexColorDistance(c, DRAW_GREY) > 80
  const home = teamColors(homeTeam).find(clear) || '#e6b64c'
  const away = teamColors(awayTeam).find(c => clear(c) && hexColorDistance(c, home) > 120)
    || ['#22d3ee', '#f97316', '#a855f7'].find(c => hexColorDistance(c, home) > 120)
  return { home, draw: DRAW_GREY, away }
}

function TeamCrest({ name, className = 'team-crest' }) {
  const crest = CLUB_CRESTS[name]
  if (!crest) return null
  return (
    <img
      src={crest.logo}
      alt=""
      className={className}
      onError={(e) => { e.currentTarget.style.display = 'none' }}
    />
  )
}

function AnimatedNumber({ value, decimals = 0, suffix = '', duration = 1500 }) {
  const [display, setDisplay] = useState(0)

  useEffect(() => {
    let start = null
    let raf
    function step(ts) {
      if (start === null) start = ts
      const progress = Math.min((ts - start) / duration, 1)
      setDisplay(value * progress)
      if (progress < 1) raf = requestAnimationFrame(step)
    }
    raf = requestAnimationFrame(step)
    return () => cancelAnimationFrame(raf)
  }, [value, duration])

  return <>{display.toFixed(decimals).replace('.', DEC())}{suffix}</>
}

function AnimatedBarFill({ className, targetPct, style }) {
  const [pct, setPct] = useState(0)

  useEffect(() => {
    const frame = requestAnimationFrame(() => setPct(targetPct))
    return () => cancelAnimationFrame(frame)
  }, [targetPct])

  return <div className={className} style={{ ...style, width: `${pct}%` }} />
}

function ProbabilityBar({ label, value, color, animate, valueColor }) {
  const [width, setWidth] = useState(animate ? 0 : value * 100)

  useEffect(() => {
    if (!animate) return
    const frame = requestAnimationFrame(() => setWidth(value * 100))
    return () => cancelAnimationFrame(frame)
  }, [animate, value])

  return (
    <div className="prob-row">
      <span className="prob-label">{label}</span>
      <div className="prob-bar-track">
        <div className="prob-bar-fill" style={{ width: `${width}%`, background: color }} />
      </div>
      <span className="prob-value" style={valueColor ? { color: valueColor } : undefined}>
        {animate ? <AnimatedNumber value={value * 100} decimals={1} suffix="%" /> : `${(value * 100).toFixed(1).replace('.', DEC())}%`}
      </span>
    </div>
  )
}

function renderBoldMarkdown(text, highlightClass) {
  if (!text) return text
  const parts = text.split(/(\*\*[^*]+\*\*)/g)
  return parts.map((part, i) =>
    part.startsWith('**') && part.endsWith('**')
      ? <strong className={highlightClass} key={i}>{part.slice(2, -2)}</strong>
      : <span key={i}>{part}</span>
  )
}

function renderScenario(text, home, away, highlightClass = 'smart-bet-highlight-gold') {
  const terms = [teamName(home), teamName(away), '2+ Toren', '3+ Toren', 'torreichen Spiel', 'torarmen Spiel',
                 '2+ goals', '3+ goals', 'high-scoring', 'low-scoring']
  const escaped = terms.map(t => t.replace(/[.*+?^${}()|[\]\\]/g, '\\$&'))
  // Also highlight standalone numbers - win rates, probabilities, scorelines
  // (e.g. "94%", "55%", "0:1") - these are the figures a reader actually
  // scans for, same treatment as the highlighted numbers in the other boxes.
  const numberPattern = String.raw`\d+(?:[.,]\d+)?\s?%|\d+:\d+`
  const parts = text.split(new RegExp(`(${escaped.join('|')}|${numberPattern})`, 'g'))
  return parts.map((part, i) =>
    terms.includes(part)
      ? <span className="scenario-highlight" key={i}>{part}</span>
      : /^(\d+(?:[.,]\d+)?\s?%|\d+:\d+)$/.test(part)
        ? <strong className={highlightClass} key={i}>{part}</strong>
        : <span key={i}>{part}</span>
  )
}

function computeFormRating(explanation, team) {
  const formPts = explanation.form_last_10_avg_pts?.[team] ?? 0
  const winRate = parseFloat(explanation.win_rate_last_10?.[team] ?? '0') || 0
  const scored = explanation.avg_goals_scored?.[team] ?? 0
  const conceded = explanation.avg_goals_conceded?.[team] ?? 0
  const goalDiffScore = Math.min(100, Math.max(0, ((scored - conceded) + 2) / 4 * 100))
  const formPtsScore = Math.min(100, Math.max(0, (formPts / 3) * 100))
  return Math.round((formPtsScore + winRate + goalDiffScore) / 3)
}

// Set an hour before kickoff (src/lineups.py): how much of each squad's best
// eleven actually starts, and how far that moved the prediction.
function LineupStrength({ data }) {
  const l = data.lineup
  const before = data.probabilities_before_lineup
  if (!l || !before) return null
  const side = (info, team) => info
    ? <><TeamLabel name={team} />: <strong>{Math.round(info.share * 100)}%</strong> {tr('der stärkstmöglichen Aufstellung (Bank nach Spielzeit gewichtet)', 'of the strongest possible line-up (bench weighted by playing time)')}</>
    : <><TeamLabel name={team} />: {tr('Aufstellung nicht bewertet', 'line-up not rated')}</>
  const moved = k => `${Math.round(before[k] * 100)}% → ${Math.round(data[k] * 100)}%`
  return (
    <div className="lineup-box">
      <h4>{tr('Aufstellungen', 'Line-ups')}</h4>
      <p>{side(l.home, data.home_team)}</p>
      <p>{side(l.away, data.away_team)}</p>
      <p className="lineup-effect">
        {tr('Siegchancen angepasst', 'Win chances adjusted')}: {teamName(data.home_team)} {moved('probability_home_win')}, {tr('Remis', 'Draw')} {moved('probability_draw')},
        {' '}{teamName(data.away_team)} {moved('probability_away_win')}.
      </p>
    </div>
  )
}

function FormRating({ data, compact = false }) {
  const explanation = data.explanation
  if (!explanation) return null

  const home = data.home_team
  const away = data.away_team
  const homeRating = computeFormRating(explanation, home)
  const awayRating = computeFormRating(explanation, away)
  const homeBetter = homeRating >= awayRating
  // Each bar is that team's own 0-100 rating, pulled in from its own edge -
  // the two numbers are independent (not shares of one shared 100), so they
  // are never normalized against each other. Bars can undershoot (gap in the
  // middle) or overshoot into each other (overlap, blended via opacity) -
  // both are honest outcomes, not something to force into summing to 100.
  let homePct = Math.max(0, Math.min(100, homeRating))
  let awayPct = Math.max(0, Math.min(100, awayRating))
  // When both teams are in form (70 and 71) the bars would run into each
  // other, and the semi-transparent overlap mixed gold and orange into a
  // third colour in the middle. They meet in proportion instead; the numbers
  // shown stay the teams' own ratings.
  if (homePct + awayPct > 100) {
    const total = homePct + awayPct
    homePct = (homePct / total) * 100
    awayPct = 100 - homePct
  }

  // The tug of war: both bars start together from their edges at the same
  // speed; the weaker side stops at its value, the stronger one pushes on to
  // its own, then its flame lights up.
  const meet = Math.min(homePct, awayPct)
  const colors = getMatchColors(home, away)
  const tug = (end, color) => ({ '--tug-meet': `${meet}%`, '--tug-end': `${end}%`, width: `${end}%`, background: color })

  return (
    <div className="form-rating-box form-rating-top">
      <h4>{tr('Formkurve', 'Form')} <span className="wm-subtle">· {tr('letzte 10 Spiele', 'last 10 games')}</span></h4>

      <div className="form-tug">
        <div className="form-tug-header">
          <span className="form-tug-name">
            <TeamLabel name={home} />{homeBetter && <span className="form-rating-flame">🔥</span>}
          </span>
          <span className="form-tug-name away">
            {!homeBetter && <span className="form-rating-flame">🔥</span>}<TeamLabel name={away} />
          </span>
        </div>
        <div className="form-tug-track">
          <div className="form-tug-scale-mark" />
          <div className="form-tug-fill-home tug-animate" style={tug(homePct, colors.home)} />
          <div className="form-tug-fill-away tug-animate" style={tug(awayPct, colors.away)} />
        </div>
        <div className="form-tug-values">
          <span className="form-tug-value home">{homeRating}</span>
          <span className="form-tug-value away">{awayRating}</span>
        </div>
      </div>

      {!compact && <>
      <p className="form-rating-detail">
        <strong><TeamLabel name={home} /></strong> — {deNum(explanation.form_last_10_avg_pts[home])} {tr('Pkt./Spiel', 'pts/game')} &middot; {deNum(explanation.avg_goals_scored[home])} {tr('Tore', 'goals')} &middot; {deNum(explanation.avg_goals_conceded[home])} {tr('Gegentore', 'conceded')} &middot; {explanation.clean_sheet_rate[home]} {tr('zu null', 'clean sheets')}
      </p>
      <p className="form-rating-detail">
        <strong><TeamLabel name={away} /></strong> — {deNum(explanation.form_last_10_avg_pts[away])} {tr('Pkt./Spiel', 'pts/game')} &middot; {deNum(explanation.avg_goals_scored[away])} {tr('Tore', 'goals')} &middot; {deNum(explanation.avg_goals_conceded[away])} {tr('Gegentore', 'conceded')} &middot; {explanation.clean_sheet_rate[away]} {tr('zu null', 'clean sheets')}
      </p>
      </>}
    </div>
  )
}

// In English, the AI's German texts (scenario, AI tip, KI-Scout) come from
// GET /ai-texts-en, translated once on the server and kept; fetched once per
// match here too. Until they arrive the German text shows.
const AI_TEXTS_EN = {}
function useAiTextsEn(home, away) {
  const key = `${home}__${away}`
  const [, redraw] = useState(0)
  useEffect(() => {
    if (LANG !== 'en' || !home || !away || AI_TEXTS_EN[key] !== undefined) return
    AI_TEXTS_EN[key] = null
    axios.get(`${API_BASE}/ai-texts-en`, { params: { home_team: home, away_team: away } })
      .then(r => { AI_TEXTS_EN[key] = r.data; redraw(x => x + 1) })
      .catch(() => { delete AI_TEXTS_EN[key] })
  })
  return LANG === 'en' ? AI_TEXTS_EN[key] || null : null
}

function MatchScenario({ data }) {
  const bm = (data.score_prediction || {}).betting_markets
  if (!bm) return null
  const home = data.home_team
  const away = data.away_team
  const en = useAiTextsEn(home, away)
  return (
    <div className="betting-markets">
      <div className="scenario-box">
        <h4>{tr('Wahrscheinlichstes Szenario', 'Most likely scenario')}</h4>
        <p>{renderScenario(en?.scenario || bm.scenario, home, away)}</p>
      </div>
    </div>
  )
}

function BettingMarkets({ data }) {
  const bm = (data.score_prediction || {}).betting_markets
  if (!bm) return null

  const home = data.home_team
  const away = data.away_team
  const { over_under: ou = [], win_margin: wm, btts, double_chance: dc } = bm

  const favoriteIsHome = data.probability_home_win >= data.probability_away_win
  const favorite = favoriteIsHome ? home : away
  const margin1 = favoriteIsHome ? wm.home_1plus : wm.away_1plus
  const margin2 = favoriteIsHome ? wm.home_2plus : wm.away_2plus
  const margin3 = favoriteIsHome ? wm.home_3plus : wm.away_3plus

  return (
    <div className="betting-markets">
      {dc && (() => {
        const dcMax = Math.max(dc.home_or_draw, dc.home_or_away, dc.draw_or_away)
        return (
          <div>
            <h4>{tr('Doppelte Chance', 'Double chance')}</h4>
            <div className="market-grid">
              <div className={`market-card market-card-fillable${dc.home_or_draw === dcMax ? ' is-leader' : ''}`}>
                <AnimatedBarFill className="market-card-fill" targetPct={dc.home_or_draw * 100} />
                <div className="market-card-content">
                  <div className="market-card-label"><TeamLabel name={home} /> {tr('oder Remis', 'or draw')}</div>
                  <div className="market-card-value"><AnimatedNumber value={dc.home_or_draw * 100} decimals={1} suffix="%" /></div>
                </div>
              </div>
              <div className={`market-card market-card-fillable${dc.home_or_away === dcMax ? ' is-leader' : ''}`}>
                <AnimatedBarFill className="market-card-fill" targetPct={dc.home_or_away * 100} />
                <div className="market-card-content">
                  <div className="market-card-label"><TeamLabel name={home} /> {tr('oder', 'or')} <TeamLabel name={away} /></div>
                  <div className="market-card-value"><AnimatedNumber value={dc.home_or_away * 100} decimals={1} suffix="%" /></div>
                </div>
              </div>
              <div className={`market-card market-card-fillable${dc.draw_or_away === dcMax ? ' is-leader' : ''}`}>
                <AnimatedBarFill className="market-card-fill" targetPct={dc.draw_or_away * 100} />
                <div className="market-card-content">
                  <div className="market-card-label">{tr('Remis oder', 'Draw or')} <TeamLabel name={away} /></div>
                  <div className="market-card-value"><AnimatedNumber value={dc.draw_or_away * 100} decimals={1} suffix="%" /></div>
                </div>
              </div>
            </div>
          </div>
        )
      })()}

      <div>
        <h4>{tr('Tore gesamt (Über / Unter)', 'Total goals (over / under)')}</h4>
        {ou.map(o => (
          <div className="over-under-row" key={o.line}>
            <span className="over-under-line">{deNum(o.line)}</span>
            <div className="over-under-track">
              <AnimatedBarFill className="over-under-fill" targetPct={o.over * 100} />
            </div>
            <span className="over-under-value">{tr('über', 'over')} <AnimatedNumber value={o.over * 100} decimals={1} suffix="%" /></span>
          </div>
        ))}
      </div>

      <div className="market-card btts-card">
        <div className="market-card-label">{tr('Beide Teams treffen', 'Both teams score')}</div>
        <div className="btts-split">
          <div className="btts-half">
            <div className="market-card-value"><AnimatedNumber value={btts.yes * 100} decimals={1} suffix="%" /></div>
            <div className="market-card-sub">{tr('Ja', 'Yes')}</div>
          </div>
          <div className="btts-half">
            <div className="market-card-value"><AnimatedNumber value={btts.no * 100} decimals={1} suffix="%" /></div>
            <div className="market-card-sub">{tr('Nein', 'No')}</div>
          </div>
        </div>
      </div>

      <div>
        <h4>{tr('Wenn', 'If')} <TeamLabel name={favorite} /> {tr('gewinnt', 'win')} (<AnimatedNumber value={margin1 * 100} decimals={1} suffix="%" />) – {tr('wie hoch?', 'by how much?')}</h4>
        <div className="market-grid">
          <div className="market-card">
            <div className="market-card-label">{tr('1+ Tor', '1+ goal')}</div>
            <div className="market-card-value"><AnimatedNumber value={margin1 * 100} decimals={1} suffix="%" /></div>
          </div>
          <div className="market-card">
            <div className="market-card-label">{tr('2+ Tore', '2+ goals')}</div>
            <div className="market-card-value"><AnimatedNumber value={margin2 * 100} decimals={1} suffix="%" /></div>
          </div>
          <div className="market-card">
            <div className="market-card-label">{tr('3+ Tore', '3+ goals')}</div>
            <div className="market-card-value"><AnimatedNumber value={margin3 * 100} decimals={1} suffix="%" /></div>
          </div>
        </div>
      </div>
    </div>
  )
}

function betPercent(value, signed = false) {
  return Number.isFinite(value) ? `${signed && value > 0 ? '+' : ''}${(value * 100).toFixed(1).replace('.', DEC())}%` : '—'
}

function BetMetric({ label, value, detail, emphasis = false }) {
  return (
    <div className={`bet-metric${emphasis ? ' is-emphasized' : ''}`}>
      <dt>{label}</dt>
      <dd>{value}<small>{detail}</small></dd>
    </div>
  )
}

function ComboLegRow({ leg, index, onOpenLeg }) {
  return (
    <div className={`combo-leg ${onOpenLeg ? 'is-clickable' : ''}`} role={onOpenLeg ? 'button' : undefined}
         tabIndex={onOpenLeg ? 0 : undefined} onClick={onOpenLeg ? () => onOpenLeg(leg) : undefined}
         title={onOpenLeg ? tr('Dieses Spiel mit der Wette öffnen', 'Open this match with the bet') : undefined}>
      <span className="combo-leg-num">{index + 1}</span>
      <div className="combo-leg-body">
        <div className="combo-leg-match">
          <TeamLabel name={leg.home_team} /> <span className="combo-leg-vs">vs</span> <TeamLabel name={leg.away_team} />
        </div>
        <div className="combo-leg-pick">{plainBetPhrase(leg)}</div>
        <div className="combo-leg-meta">
          {marketGroupLabel(leg.market)} · {leg.bookmaker}
        </div>
        <div className="smart-bet-agree-row combo-leg-agree">
          {leg.policy === 'agree' && <span className="smart-bet-agree-chip yes">◆ {tr('Modell stimmt zu', 'Model agrees')} ✓</span>}
          {leg.ki_agrees && <span className="smart-bet-agree-chip yes">✨ {tr('KI stimmt zu', 'AI agrees')} ✓</span>}
          {leg.is_likely && <span className="smart-bet-agree-chip yes">🎯 {tr('Wahrscheinlichster Tipp', 'Most likely bet')}</span>}
          {leg.likely_pick && (
            <span className="smart-bet-agree-chip muted"
                  title={`${tr('🎯 dieses Spiels', "🎯 of this match")}: ${plainBetPhrase(leg.likely_pick)} ${tr('zu', 'at')} ${leg.likely_pick.best_odds?.toFixed(2)}`}>
              🎯 {tr('Nicht der wahrscheinlichste', 'Not the most likely')}
            </span>
          )}
        </div>
      </div>
      <div className="combo-leg-numbers">
        <span className="combo-leg-odds">{leg.best_odds.toFixed(2)}</span>
        <span className="combo-leg-prob">{betPercent(leg.probability)} {tr('Modell', 'model')}</span>
      </div>
    </div>
  )
}

function ComboTicketCard({ ticket, primary, onOpenLeg }) {
  return (
    <div className={`combo-ticket ${primary ? 'is-primary' : ''}`}>
      <div className="combo-ticket-head">
        <span className="combo-ticket-legs">{tr(`${ticket.leg_count}er-Kombi`, `${ticket.leg_count}-fold`)} · {ticket.bookmaker}</span>
        <div className="combo-quote">
          <span className="combo-quote-label">{tr('Geschätzte Gesamtquote', 'Estimated combined odds')}</span>
          <span className="combo-ticket-odds">{ticket.combined_odds.toFixed(2)}</span>
        </div>
      </div>
      <div className="combo-legs">
        {ticket.legs.map((leg, i) => <ComboLegRow key={i} leg={leg} index={i} onOpenLeg={onOpenLeg} />)}
      </div>
      <dl className="bet-metrics probability-metrics">
        <BetMetric label={tr('Chance, dass alle treffen', 'Chance all of them land')} value={betPercent(ticket.conservative_probability)}
                   detail={tr('Nach Marktpreisen, ohne Marge', "By the market's prices, margin removed")} emphasis />
        <BetMetric label={tr('Unser Modell allein', 'Our model on its own')} value={betPercent(ticket.probability)} detail={tr('Vor dem Abgleich mit dem Preis', 'Before checking against the price')} />
      </dl>
      <dl className="bet-metrics decision-metrics">
        <BetMetric label={tr('Gewinn pro 1 € Einsatz', 'Profit per 1 staked')} value={ticket.returns_per_unit.toFixed(2)} detail={tr('Wenn jeder Tipp trifft', 'If every selection wins')} />
      </dl>
      {primary && (
        <p className="combo-ticket-note">
          {tr(`Die Wahrscheinlichkeiten nehmen an, dass die Ergebnisse unabhängig voneinander sind. Die Quoten
          stammen aus den Einzelmärkten von ${ticket.bookmaker}; das Kombi-Angebot selbst wurde nicht
          geprüft. Wir erwarten mit dieser Wette keinen Gewinn – es ist nur der wahrscheinlichste Schein
          über der Zielquote.`, `Probabilities assume the results are independent of one another. Prices come from
          ${ticket.bookmaker}'s individual markets; the combined offer itself has not been checked. This is not
          a bet we expect to profit from - it is the likeliest ticket above the target odds.`)}
        </p>
      )}
    </div>
  )
}

// A combo of the day's price tips: every leg is a bet where bet-at-home pays
// more than Pinnacle's fair price, so the edges multiply.
function PriceTipComboCard({ ticket, onOpenLeg }) {
  return (
    <div className="combo-ticket is-primary price-tip-combo">
      <div className="combo-ticket-head">
        <span className="combo-ticket-legs">💰 {tr(`${ticket.leg_count}er-Kombi`, `${ticket.leg_count}-fold`)} · bet-at-home</span>
        <div className="combo-quote">
          <span className="combo-quote-label">{tr('Gesamtquote', 'Combined odds')}</span>
          <span className="combo-ticket-odds">{ticket.combined_odds.toFixed(2)}</span>
        </div>
      </div>
      <div className="combo-legs">
        {ticket.legs.map((leg, i) => (
          <div className={`combo-leg ${onOpenLeg ? 'is-clickable' : ''}`} key={i} role="button" tabIndex={0}
               onClick={onOpenLeg ? () => onOpenLeg(leg) : undefined}>
            <span className="combo-leg-num">{i + 1}</span>
            <div className="combo-leg-body">
              <div className="combo-leg-match">
                <TeamLabel name={leg.home_team} /> <span className="combo-leg-vs">vs</span> <TeamLabel name={leg.away_team} />
              </div>
              <div className="combo-leg-pick">{betOutcomeLabel(leg)}</div>
              <div className="combo-leg-meta">{marketGroupLabel(leg.market)} · fair {leg.fair_odds.toFixed(2)} · {tr('Vorteil', 'edge')} {(leg.edge * 100).toFixed(1)}%</div>
            </div>
            <div className="combo-leg-numbers">
              <span className="combo-leg-odds">{leg.book_odds.toFixed(2)}</span>
              <span className="combo-leg-prob">{betPercent(leg.probability)} Pinnacle</span>
            </div>
          </div>
        ))}
      </div>
      <dl className="bet-metrics probability-metrics">
        <BetMetric label={tr('Chance, dass alle treffen', 'Chance all of them land')} value={betPercent(ticket.probability)} detail={tr('Nach Pinnacles fairen Preisen', "By Pinnacle's fair prices")} emphasis />
        <BetMetric label={tr('Vorteil', 'Edge')} value={`${ticket.edge >= 0 ? '+' : ''}${(ticket.edge * 100).toFixed(1)}%`} detail={tr('Pro 1 € Einsatz, im Schnitt über viele Scheine', 'Per 1 staked, on average over many tickets')} />
      </dl>
      <p className="combo-ticket-note">
        {tr('Nur Preis-Tipps, alle in der Stunde vor Anpfiff gelesen. Ergebnisse gelten als unabhängig; das Kombi-Angebot bei bet-at-home wurde nicht geprüft. Ein Vorteil ist ein Durchschnitt, kein Versprechen für diesen Schein.',
            'Only price tips, all read in the hour before kickoff. Results are assumed independent; the combined offer at bet-at-home has not been checked. An edge is an average, not a promise for this ticket.')}
      </p>
    </div>
  )
}

function ComboTicketView({ combo, loading, onOpenLeg }) {
  if (loading) {
    return (
      <div className="analyzing-status loading-inline">
        <span className="analyzing-spinner" />
        <span>{tr('Kombinationen werden gebaut…', 'Building combinations…')}</span>
      </div>
    )
  }
  if (!combo) return null
  if (combo.error) {
    return <p className="wm-subtle">{tr('Kombi-Vorschlag gerade nicht verfügbar (keine aktuellen Quoten).', 'Combo suggestion unavailable right now (no current odds).')}</p>
  }

  return (
    <div className="combo-view">
      {combo.price_tip_combos?.length > 0 && (
        <div className="combo-day">
          <span className="combo-section-label">💰 {tr('Preis-Tipp-Kombi', 'Price tip combo')}</span>
          {combo.price_tip_combos.map(t => <PriceTipComboCard key={t.date} ticket={t} onOpenLeg={onOpenLeg} />)}
        </div>
      )}

      <p className="best-bets-intro">
        {LANG === 'en' ? <>
          Every selection must win. All prices are <strong>bet-at-home's</strong>; each ticket uses <strong>one matchday</strong>
          {' '}and at most one selection per match. Only selections <strong>our model agrees with</strong> are used;
          {' '}those the <strong>AI</strong> also backs after its research come first. A ticket pays at least
          {' '}<strong>{(combo.min_combined_odds || 3).toFixed(2)}</strong>. Compare the best 2-, 3- and 4-folds for each day.
        </> : <>
          Jeder Tipp muss treffen. Alle Quoten sind von <strong>bet-at-home</strong>; jeder Schein nutzt <strong>einen Spieltag</strong>
          {' '}und höchstens einen Tipp pro Spiel. Genommen werden nur Tipps, denen <strong>unser Modell zustimmt</strong>;
          {' '}Tipps, die auch die <strong>KI</strong> nach ihrer Recherche stützt, kommen zuerst. Ein Schein zahlt mindestens
          {' '}<strong>{(combo.min_combined_odds || 3).toFixed(2).replace('.', DEC())}</strong>. Vergleiche die besten 2er-, 3er- und 4er-Kombis pro Tag.
        </>}
      </p>

      {!combo.recommended && (
        <p className="smart-bet-notip">
          <strong>{tr('Heute kein Kombi-Schein.', 'No combo ticket today.')}</strong><br />
          {LANG === 'en' ? 'No same-day ticket at bet-at-home passes all checks.' : combo.reason}
        </p>
      )}

      {combo.days?.map(day => (
        <div className="combo-day" key={day.date}>
          <span className="combo-section-label">
            {new Date(day.date + 'T12:00:00').toLocaleDateString(LOCALE(), { weekday: 'long', day: 'numeric', month: 'short' })}
            {' · '}{day.eligible_legs} {day.eligible_legs === 1 ? tr('passendes Spiel', 'eligible match') : tr('passende Spiele', 'eligible matches')}
          </span>

          <div className="combo-size-grid">
            {(day.by_size || []).map(option => (
              <section className="combo-size-option" key={option.leg_count}
                       aria-label={tr(`${option.leg_count}er-Kombi`, `${option.leg_count}-fold combo`)}>
                <h3 className="combo-size-title">{tr(`${option.leg_count}er-Kombi`, `${option.leg_count}-fold combo`)}</h3>
                {option.ticket ? (
                  <>
                    <ComboTicketCard ticket={option.ticket} onOpenLeg={onOpenLeg} />
                    {option.near_miss && (
                      <details className="combo-near-miss">
                        <summary>
                          {tr('Wahrscheinlicher, knapp unter', 'Likelier, just under')} {(combo.min_combined_odds || 2).toFixed(2).replace('.', DEC())}: {betPercent(option.near_miss.conservative_probability)} {tr('zu', 'at')}
                          {' '}{option.near_miss.combined_odds.toFixed(2)}
                          {' '}({tr('statt', 'vs')} {betPercent(option.ticket.conservative_probability)} {tr('zu', 'at')} {option.ticket.combined_odds.toFixed(2)})
                        </summary>
                        <ComboTicketCard ticket={option.near_miss} onOpenLeg={onOpenLeg} />
                      </details>
                    )}
                  </>
                ) : (
                  <div className="combo-size-empty">
                    <strong>{tr('Nicht verfügbar', 'Not available')}</strong>
                    <p>{LANG === 'en'
                      ? `No ${option.leg_count}-fold available: it needs ${option.leg_count} qualifying matches and the target combined odds.`
                      : option.reason}</p>
                  </div>
                )}
              </section>
            ))}
          </div>
        </div>
      ))}

      <p className="smart-bet-finePrint">
        {tr('Unter den Scheinen mit den meisten KI-gestützten Tipps gewinnt der laut Markt wahrscheinlichste. Die Wahrscheinlichkeiten nehmen unabhängige Ergebnisse an; die Gesamtquoten sind aus Einzelquoten berechnet und nicht als Buchmacher-Schein geprüft. Eine höhere geschätzte Trefferquote heißt nicht, dass sich die Wette lohnt. Scheine können sich überschneiden und sind keine unabhängigen Wetten.',
            "Among the tickets with the most AI-backed selections, the market's likeliest wins. Probabilities assume independent results; combined odds are calculated from individual prices and have not been verified as a bookmaker ticket. A higher estimated hit rate does not mean the bet is worth it. Tickets can overlap and are not independent bets.")}
      </p>
    </div>
  )
}

function FixtureRow({ fixture }) {
  const opens = predictionOpensAt(fixture)
  const label = opens > new Date()
    ? `${tr('Analyse ab', 'Analysis from')} ${opens.toLocaleDateString(LOCALE(), { weekday: 'short', day: 'numeric', month: 'short' })}`
    : tr('Analyse folgt', 'Analysis coming')
  return (
    <div className="fixture-row fixture-pending">
      <div className="fixture-meta">
        <span className="fixture-date">{fixtureWhen(fixture)}</span>
        <span className="fixture-pending-badge">{label}</span>
      </div>
      <div className="fixture-teams">
        <span><TeamLabel name={fixture.home_team} /></span>
        <span className="fixture-vs">vs</span>
        <span><TeamLabel name={fixture.away_team} /></span>
      </div>
    </div>
  )
}

function FixtureReadyRow({ fixture, onGenerate, onBets }) {
  return (
    <div className="fixture-row fixture-ready">
      <div className="fixture-meta">
        <span className="fixture-date">{fixtureWhen(fixture)}</span>
        <span className="fixture-ready-badge">{tr('Analyse bereit', 'Analysis ready')}</span>
      </div>
      <div className="fixture-teams">
        <span><TeamLabel name={fixture.home_team} /></span>
        <span className="fixture-vs">vs</span>
        <span><TeamLabel name={fixture.away_team} /></span>
      </div>
      <button className="fixture-generate-btn" onClick={onGenerate}>
        {tr('KI-Analyse starten', 'Start AI analysis')}
      </button>
      {onBets && (
        <button className="fixture-generate-btn fixture-bets-btn" onClick={onBets}>
          {tr('Wett-Tipps zeigen', 'Show bet tips')}
        </button>
      )}
    </div>
  )
}

const ANALYZING_STEPS = [
  ['Aktuelle Spieldaten werden gelesen…', 'Reading the latest match data…'],
  ['Stärke, Form & direkte Duelle werden analysiert…', 'Analysing strength, form & head-to-head…'],
  ['Sieg-, Remis- und Niederlagen-Chancen werden berechnet…', 'Calculating win, draw and loss chances…'],
  ['Märkte & Quoten werden berechnet…', 'Calculating markets & odds…'],
  ['Wahrscheinlichste Ergebnisse werden ermittelt…', 'Finding the most likely scores…'],
  ['Spielverlauf wird erstellt…', 'Building the game flow…'],
]

const BET_STEPS = [
  ['Aktuelle Quoten werden geladen…', 'Loading the current odds…'],
  ['Abgleich mit den Modell-Wahrscheinlichkeiten…', 'Comparing with the model probabilities…'],
  ['Erwartungswert wird berechnet…', 'Calculating expected value…'],
  ['Beste Wette wird gesucht…', 'Finding the best bet…'],
]

const lineOf = m => deNum(m.replace('Over/Under ', '').replace('Handicap ', ''))

function betOutcomeLabel(b) {
  if (b.market === 'Handicap +0.5') return <><TeamLabel name={b.team} /> {tr('oder Remis', 'or draw')}</>
  if (b.market === 'Handicap 0.0') return <><TeamLabel name={b.team} /> {tr('(Remis = Einsatz zurück)', '(draw no bet)')}</>
  if (b.outcome === 'handicap') return <>{lineOf(b.market)} <TeamLabel name={b.team} /></>
  if (b.outcome === 'home_win' || b.outcome === 'away_win') return <>{tr('Sieg', 'Win')} <TeamLabel name={b.team} /></>
  if (b.team) return <TeamLabel name={b.team} />
  if (b.outcome === 'draw') return tr('Remis', 'Draw')
  if (b.market === 'BTTS') return tr(`Beide treffen: ${String(b.outcome).toLowerCase() === 'yes' ? 'Ja' : 'Nein'}`,
                                     `Both teams score: ${String(b.outcome).toLowerCase() === 'yes' ? 'Yes' : 'No'}`)
  if (b.outcome === 'Over') return `${tr('Über', 'Over')} ${lineOf(b.market)}`
  if (b.outcome === 'Under') return `${tr('Unter', 'Under')} ${lineOf(b.market)}`
  return b.outcome
}

function marketGroupLabel(market) {
  if (market === '1X2') return tr('Ergebnis', 'Result')
  if (market === 'Handicap +0.5') return tr('Doppelte Chance', 'Double chance')
  if (market === 'Handicap 0.0') return tr('Remis = Einsatz zurück', 'Draw no bet')
  if (market.startsWith('Handicap')) return 'Asian Handicap'
  if (market === 'BTTS') return tr('Beide treffen', 'Both score')
  return tr('Tore', 'Goals')
}

// Plain-language phrasing of a bet for the combo legs.
function plainBetPhrase(b) {
  if (b.outcome === 'home_win' || b.outcome === 'away_win') return <><TeamLabel name={b.team} /> {tr('gewinnt', 'to win')}</>
  if (b.outcome === 'draw') return tr('Remis', 'Draw')
  if (b.outcome === 'Over') return tr(`Über ${lineOf(b.market)} Tore`, `Over ${lineOf(b.market)} goals`)
  if (b.outcome === 'Under') return tr(`Unter ${lineOf(b.market)} Tore`, `Under ${lineOf(b.market)} goals`)
  if (b.market === 'Handicap +0.5') return <><TeamLabel name={b.team} /> {tr('oder Remis (Doppelte Chance)', 'or draw (double chance)')}</>
  if (b.market === 'Handicap 0.0') return <><TeamLabel name={b.team} /> {tr('gewinnt (Remis = Einsatz zurück)', 'to win (draw no bet)')}</>
  if (b.outcome === 'handicap') return <><TeamLabel name={b.team} /> {lineOf(b.market)} Handicap</>
  if (b.market === 'BTTS') return tr(`Beide treffen: ${String(b.outcome).toLowerCase() === 'yes' ? 'Ja' : 'Nein'}`,
                                     `Both teams score: ${String(b.outcome).toLowerCase() === 'yes' ? 'Yes' : 'No'}`)
  return b.market
}

// 1X2 always, plus the three other bets closest to paying off.
function priceTipRows(outcomes) {
  const main = outcomes.filter(o => o.market === '1X2')
  const others = outcomes.filter(o => o.market !== '1X2').sort((a, b) => b.edge - a.edge).slice(0, 3)
  return [...main, ...others]
}

// Must match src/price_tip.py MODEL_TOLERANCE.
const MODEL_TOLERANCE = 0.05
const pct = (x, digits = 0) => `${(x * 100).toFixed(digits)}%`
const signedPct = (x) => `${x >= 0 ? '+' : ''}${(x * 100).toFixed(1).replace('.', DEC())}%`
const bookName = (b) => (b || 'bet-at-home').replace(/\.de$/, '')

// The headline tip: where bet-at-home pays more than Pinnacle's margin-free
// price (src/price_tip.py). Model and AI are shown beside it, not used by it.
// Every tip box in the KI-Tipp's design: a headline with the bet, one
// sentence with the numbers in bold. `tone` picks the colour.
function TipCard({ tone, headline, children, className = '' }) {
  return (
    <div className={`tip-card tip-card-${tone} ${className}`}>
      <div className="tip-card-headline">{headline}</div>
      <div className="tip-card-text">{children}</div>
    </div>
  )
}

const deOdds = x => x.toFixed(2).replace('.', DEC())

function PriceTipBox({ priceTip }) {
  if (!priceTip) {
    return (
      <p className="smart-bet-notip">
        <strong>{tr('Kein Preis-Tipp für dieses Spiel.', 'No price tip for this match.')}</strong><br />
        {tr('Hier gibt es keinen verlässlichen Referenzpreis.', 'There is no reliable reference price here.')}
      </p>
    )
  }
  const tip = priceTip.tip
  const book = bookName(priceTip.bookmaker)
  if (!tip) {
    return (
      <TipCard tone="gold" className="is-empty" headline={<>💰 {tr('Preis-Tipp: keiner', 'Price tip: none')}</>}>
        {priceTip.waiting
          ? tr('Entscheidet sich in der Stunde vor Anpfiff, wenn Pinnacles Quote gelesen wird.', "Decided in the hour before kickoff, when Pinnacle's price is read.")
          : (LANG === 'en'
            ? `${book} pays no more than Pinnacle's fair price anywhere here.`
            : (priceTip.reason || `${book} zahlt nirgends mehr als Pinnacles fairer Preis.`))}
        <details className="price-tip-more">
          <summary>{tr('Vergleich ansehen', 'See the comparison')}</summary>
        {priceTip.outcomes.length > 0 && (
          <div className="price-tip-table">
            <div className="price-tip-table-head">
              <span>{tr('Ausgang', 'Outcome')}</span><span>Pinnacle</span><span>{book}</span><span>{tr('Chance', 'Chance')}</span><span>{tr('Vorteil', 'Edge')}</span>
            </div>
            {priceTipRows(priceTip.outcomes).map((o) => (
              <div className="price-tip-table-row" key={`${o.market}-${o.outcome}-${o.side}`}>
                <span>{betOutcomeLabel(o)}</span>
                <span>{o.pinnacle_odds ? o.pinnacle_odds.toFixed(2) : <em title={tr('faire Quote aus Pinnacles 1X2', "fair price from Pinnacle's 1X2")}>{o.fair_odds.toFixed(2)}</em>}</span>
                <span>{o.book_odds.toFixed(2)}</span>
                <span title={o.refund_probability > 0 ? tr(`Sieg ${pct(o.win_probability)} · Remis erstattet ${pct(o.refund_probability)} · Niederlage ${pct(o.loss_probability)}`, `Win ${pct(o.win_probability)} · draw refunded ${pct(o.refund_probability)} · loss ${pct(o.loss_probability)}`) : undefined}>
                  {pct(o.win_probability ?? o.probability)}{o.refund_probability > 0 ? '*' : ''}
                </span>
                <span className={o.edge >= priceTip.threshold ? 'positive' : 'negative'}>{signedPct(o.edge)}</span>
              </div>
            ))}
          </div>
        )}
        <p className="price-tip-footnote">
          {priceTip.outcomes.some(o => o.refund_probability > 0) && <>{tr('* Remis = Einsatz zurück: Chance auf Sieg; bei Remis gibt es den Einsatz zurück. ', '* Draw no bet: chance of a win; a draw returns the stake. ')}</>}
          {tr(`Ein Tipp erscheint, wenn ${book} mindestens ${pct(priceTip.threshold)} über Pinnacles fairem Preis zahlt. Das passiert meist in der letzten Stunde vor Anpfiff, wenn Pinnacle zuerst reagiert.`,
              `A tip appears when ${book} pays at least ${pct(priceTip.threshold)} more than Pinnacle's fair price. That usually happens in the last hour before kickoff, when Pinnacle moves first.`)}
        </p>
        </details>
      </TipCard>
    )
  }
  return (
    <TipCard tone="gold" headline={<>💰 {tr('Preis-Tipp', 'Price tip')}: {betOutcomeLabel(tip)}</>}>
      {LANG === 'en' ? <>
        {book} pays <strong>{deOdds(tip.book_odds)}</strong>, Pinnacle's fair price is
        {' '}<strong>{deOdds(tip.fair_odds)}</strong> – an edge of <strong>{signedPct(tip.edge)}</strong> per unit
        {' '}at <strong>{pct(tip.win_probability ?? tip.probability)}</strong> chance
        {tip.refund_probability > 0 ? <> ({pct(tip.refund_probability)} stake back on a draw)</> : null}.
        {' '}Chosen by price only: the edge is an average over many bets, not a promise for this one.
      </> : <>
        {book} zahlt <strong>{deOdds(tip.book_odds)}</strong>, fair wären laut Pinnacle
        {' '}<strong>{deOdds(tip.fair_odds)}</strong> – ein Vorteil von <strong>{signedPct(tip.edge)}</strong> pro Euro
        {' '}bei <strong>{pct(tip.win_probability ?? tip.probability)}</strong> Chance
        {tip.refund_probability > 0 ? <> (bei Remis {pct(tip.refund_probability)} Einsatz zurück)</> : null}.
        {' '}Nur nach Preis gewählt: Der Vorteil ist ein Durchschnitt über viele Wetten, kein Versprechen für diese.
      </>}
    </TipCard>
  )
}

// The AI's research, closed until the reader asks for it.
function AgentFactors({ research: researchDe, home, away }) {
  const [open, setOpen] = useState(false)
  const en = useAiTextsEn(home, away)
  const research = en ? Object.fromEntries(Object.entries(researchDe).map(([k, v]) => [k, en.research?.[k] || v])) : researchDe
  const rows = [
    ['⚕', tr('Aufstellung & Verletzungen', 'Line-ups & injuries'), research.lineups_injuries],
    ['📈', tr('Form', 'Form'), research.form],
    ['🏆', tr('Tabellensituation', 'Table situation'), research.table_situation],
    ['💬', tr('Sonstiges', 'Other'), research.other],
  ].filter(([, , text]) => text)
  if (rows.length === 0) return null
  return (
    <div className="wm-reveal agent-factors">
      <button className={`scout-btn${open ? ' is-open' : ''}`} onClick={() => setOpen(v => !v)} aria-expanded={open}>
        <span className="scout-btn-icon">🛰️</span>
        <span className="scout-btn-text">
          <span className="scout-btn-title">{tr('KI-Scout', 'AI Scout')}</span>
          <span className="scout-btn-sub">{tr('Was die Zahlen nicht sehen: Verletzungen, Aufstellung, Form, Tabelle – live recherchiert', "What the numbers don't see: injuries, line-ups, form, table – researched live")}</span>
        </span>
        <span className="scout-btn-chevron">{open ? '▲' : '▼'}</span>
      </button>
      {open && rows.map(([icon, label, text]) => (
        <div className="agent-factors-row" key={label}>
          <span className="agent-factors-cat">{icon} {label}</span>
          <p className="agent-factors-text">{text}</p>
        </div>
      ))}
    </div>
  )
}

// Whether a bet wins at a final score (null for a market we cannot settle).
function betWins(b, home, away, hs, as) {
  const margin = team => team === home ? hs - as : team === away ? as - hs : null
  const line = () => parseFloat(String(b.market).split(' ').pop())
  if (b.market === '1X2') {
    if (b.outcome === 'draw') return hs === as
    const m = margin(b.team)
    return m == null ? null : m > 0
  }
  if (b.market === 'BTTS') return (hs > 0 && as > 0) === (String(b.outcome).toLowerCase() === 'yes')
  if (String(b.market).startsWith('Over/Under ')) return b.outcome === 'Over' ? hs + as > line() : hs + as < line()
  if (String(b.market).startsWith('Handicap ')) {
    const m = margin(b.team)
    return m == null ? null : m + line() > 0
  }
  return null
}

// The AI "agrees" when our tip wins in every result its own pick wins: its
// "Spain to win" backs our "Spain or draw". Mirrors src/price_tip.py implies.
function impliesBet(pick, tip, home, away, sameBet) {
  for (let hs = 0; hs <= 8; hs++) {
    for (let as = 0; as <= 8; as++) {
      const a = betWins(pick, home, away, hs, as)
      const b = betWins(tip, home, away, hs, as)
      if (a === null || b === null) return sameBet(pick, tip)
      if (a && !b) return false
    }
  }
  return true
}

// How often the model was right when it rated a bet above the market by
// about this much (GET /model-track-record, scripts/build_model_track_record.py).
// Loaded once; the ★ box reads it.
let MODEL_TRACK_RECORD = null

const TRACK_VERDICTS = {
  better: ['is-better', 'Hier lag das Modell öfter richtig als der Markt.'],
  worse: ['is-worse', 'Besser dem Markt vertrauen.'],
  same: ['is-same', 'Besser dem Markt vertrauen.'],
}

const COMPETITION_NAMES = {
  soccer_germany_bundesliga: 'Bundesliga',
  soccer_uefa_champs_league: 'Champions League',
  soccer_uefa_nations_league: 'Nations League',
}

// How the model did in the past when it disagreed with the market this much -
// in this competition only, since a Nations League tip is a different model
// and a different market from a Bundesliga one.
function ModelTrackRecord({ bet, bets = [], competition }) {
  const record = MODEL_TRACK_RECORD
  if (!record) return null
  // A handicap on a team (Draw No Bet, +/-0.5) is judged on the same team's
  // 1X2 win, which is what the past cases measure.
  let basis = bet
  if ((bet.model_probability_raw == null || bet.market_probability == null) && bet.team
      && String(bet.market).startsWith('Handicap')) {
    const win = bets.find(b => b.market === '1X2' && b.team === bet.team)
    if (win && win.model_probability_raw != null && win.market_probability != null) basis = win
  }
  if (basis.model_probability_raw == null || basis.market_probability == null) return null
  const name = COMPETITION_NAMES[competition] || 'diesem Wettbewerb'
  const rows = record.by_competition?.[competition] || []
  const gap = basis.model_probability_raw - basis.market_probability
  const row = rows.find(r => gap >= r.from && gap < r.to)
  const minCases = record.min_cases || 30
  const optimism = `Das Modell ist hier ${gap >= 0.1 ? 'deutlich ' : ''}optimistischer als der Markt `
    + `(${pct(basis.model_probability_raw)} gegenüber ${pct(basis.market_probability)}).`
  if (!row || row.n < minCases) {
    return (
      <div className="model-track is-same">
        <span className="model-track-label">Kann man dem Modell hier trauen?</span>
        <p>{optimism} Es gibt noch zu wenige vergleichbare Fälle ({name}), um das zu sagen
          ({row ? row.n : 0} von {minCases}); die Bilanz wächst mit jedem Spiel.</p>
      </div>
    )
  }
  const [cls, advice] = TRACK_VERDICTS[row.verdict] || TRACK_VERDICTS.same
  return (
    <div className={`model-track ${cls}`}>
      <span className="model-track-label">Kann man dem Modell hier trauen?</span>
      <p>
        {optimism} Bei {row.n} ähnlichen Wetten ({name}) trafen {pct(row.hit_rate)}: Der Markt hatte
        {pct(row.market_expected)} erwartet, das Modell {pct(row.model_expected)}.
      </p>
      <p className="model-track-advice">→ {advice}</p>
    </div>
  )
}

// The second headline: what the market thinks will most likely land, at
// odds still worth taking. No edge is claimed - that is the price tip's job.
// The headline tip: the likeliest bet both the model and the AI back (the
// combo's rule). The server computes it (bet_tip); computed here the same
// way when it is missing.
function computeBetTip(betInfo, agentPick, sameBet) {
  if (betInfo.bet_tip) return betInfo.bet_tip
  if (!agentPick) return { tip: null, status: 'waiting_for_ai' }
  const ok = (betInfo.bets || []).filter(b => b.market !== 'Handicap 0.0' && b.market_probability != null
    && b.best_odds >= 1.30 && b.market_probability >= 0.5
    && (b.model_probability_raw ?? b.probability) >= b.market_probability - MODEL_TOLERANCE
    && impliesBet(agentPick, b, betInfo.home_team, betInfo.away_team, sameBet))
  if (!ok.length) return { tip: null, status: 'no_agreement' }
  // One bet in two markets ("-0.5" and "to win"): keep the better price.
  const same = (x, y) => impliesBet(x, y, betInfo.home_team, betInfo.away_team, sameBet)
    && impliesBet(y, x, betInfo.home_team, betInfo.away_team, sameBet)
  const best = ok.filter(b => !ok.some(o => same(b, o) && o.best_odds > b.best_odds))
  const tip = best.reduce((x, y) => (y.market_probability > x.market_probability
    || (y.market_probability === x.market_probability && y.best_odds > x.best_odds)) ? y : x)
  return { tip, status: 'ok' }
}

function BetTipBox({ betTip }) {
  const tip = betTip?.tip
  if (!tip) {
    return (
      <div className="bet-tip is-empty">
        <span className="smart-bet-label bet-tip-label">{tr('Wett-Tipp', 'Bet tip')}</span>
        <div className="bet-tip-none">
          {betTip?.status === 'waiting_for_ai'
            ? tr('Folgt, sobald die KI das Spiel geprüft hat (in den 15 Stunden vor Anpfiff).', 'Coming once the AI has checked the match (in the 15 hours before kickoff).')
            : tr('Kein Wett-Tipp – Modell und KI sind sich bei diesem Spiel nicht einig.', 'No bet tip – the model and the AI do not agree on this match.')}
        </div>
      </div>
    )
  }
  return (
    <div className="bet-tip">
      <span className="smart-bet-label bet-tip-label">{tr('Wett-Tipp', 'Bet tip')}</span>
      <div className="likely-tip-row">
        <span className="bet-tip-pick">{betOutcomeLabel(tip)}</span>
        <span className="likely-tip-odds">{tip.best_odds.toFixed(2)}</span>
        <span className="likely-tip-chance">{pct(tip.market_probability)} {tr('Chance', 'chance')}</span>
      </div>
      <div className="smart-bet-agree-row">
        <span className="smart-bet-agree-chip yes">◆ {tr('Modell stimmt zu', 'Model agrees')} ✓</span>
        <span className="smart-bet-agree-chip yes">✨ {tr('KI stimmt zu', 'AI agrees')} ✓</span>
      </div>
    </div>
  )
}

function LikelyTipBox({ pick }) {
  if (!pick) return null
  return (
    <TipCard tone="red" headline={<>🎯 {tr('Am wahrscheinlichsten', 'Most likely')}: {betOutcomeLabel(pick)}</>}>
      {LANG === 'en' ? <>
        By the market the likeliest bet at odds between 1.30 and 2.00:
        {' '}<strong>{pct(pick.market_probability)}</strong> chance at odds of <strong>{deOdds(pick.best_odds)}</strong>.
        {' '}Likely does not mean worth it – the bookmaker's margin is built in.
      </> : <>
        Laut Markt die wahrscheinlichste Wette mit Quote zwischen 1,30 und 2,00:
        {' '}<strong>{pct(pick.market_probability)}</strong> Chance zur Quote <strong>{deOdds(pick.best_odds)}</strong>.
        {' '}Wahrscheinlich heißt nicht lohnend – die Marge des Buchmachers steckt drin.
      </>}
    </TipCard>
  )
}

function SmartBetCard({ betStep, betInfo, data }) {
  const [showAllMarkets, setShowAllMarkets] = useState(false)
  const aiEn = useAiTextsEn(data?.home_team, data?.away_team)

  const analyzing = betStep < BET_STEPS.length
  if (analyzing) {
    return (
      <div className="analyzing-status">
        <span className="analyzing-spinner" />
        <span>{tr(...BET_STEPS[betStep])}</span>
      </div>
    )
  }
  if (!betInfo || !betInfo.odds_found) {
    return (
      <div className="wm-reveal">
        <p className="wm-subtle">{tr('Für dieses Spiel gibt es gerade keine Quoten.', 'There are no odds for this match right now.')}</p>
      </div>
    )
  }

  if (betInfo.in_play) {
    return (
      <div className="wm-reveal">
        <p className="smart-bet-notip">
          <strong>{tr('Dieses Spiel läuft bereits.', 'This match is already in play.')}</strong><br />
          {tr('Die Quoten sind jetzt live und bewegen sich mit dem Spielstand – unser Vorab-Modell lässt sich nicht mehr sinnvoll damit vergleichen. Kein Tipp für dieses Spiel.',
              'The odds are live now and move with the score – our pre-match model can no longer be compared with them meaningfully. No tip for this match.')}
        </p>
      </div>
    )
  }

  // A recommendation with a warning means nothing cleared the clean/above-
  // threshold bar (see MIN_KELLY_FOR_RECOMMENDATION in the backend) - it's a
  // thin fallback, not a real tip, so it must not be promoted to a ★ signal
  // status just because it was the least-bad green available.
  const recWarning = betInfo.recommendation_warning
  const best = recWarning ? null : betInfo.recommendation
  const agentEval = betInfo.agent_eval
  const agentPick = agentEval && agentEval.pick
  const combined = betInfo.combined
  const priceTipPick = betInfo.price_tip && betInfo.price_tip.tip
  const modelFavorite = betInfo.model_favorite
  const likelyPick = betInfo.likely_pick
  const scenarioText = data?.score_prediction?.betting_markets?.scenario
  const sameBet = (a, b) => a.market === b.market && a.outcome === b.outcome && a.team === b.team
  const greens = betInfo.green_bets || []
  const reds = betInfo.red_bets || []
  // One list of every bet: the marked ones first (price tip, then the other
  // signals), then the rest by stake size and edge. Only the first
  // TABLE_ROWS are shown; the others sit behind "Show all markets".
  const TABLE_ROWS = 6
  // Draw No Bet ("Remis = Einsatz zurück", Handicap 0.0) stays out of the table.
  const allBets = ((betInfo.bets && betInfo.bets.length) ? betInfo.bets : [...greens, ...reds])
    .filter(b => b.market !== 'Handicap 0.0')
  // Table order: the price tip, the market's likeliest bet, the model's
  // biggest gap to the market (★, explained in its box below), the AI's pick.
  // The model's favourite is no longer marked.
  const signals = [priceTipPick, likelyPick, agentPick].filter(Boolean)
  const signalRank = b => { const i = signals.findIndex(x => sameBet(x, b)); return i === -1 ? signals.length : i }
  // After the marked bets, the same order the combo uses: bets both the
  // model and the AI back, then bets only the model backs (each by the
  // market's chance); greyed out at the end, bets the model rates more than
  // MODEL_TOLERANCE below the market. The model's own edge and stake are no
  // longer the measure - they turned out to be gaps, not value.
  const modelBacks = b => b.market_probability == null
    || (b.model_probability_raw ?? b.probability) >= b.market_probability - MODEL_TOLERANCE
  const aiBacks = b => !!agentPick && impliesBet(agentPick, b, betInfo.home_team, betInfo.away_team, sameBet)
  // Under 1.30 a bet pays too little to be worth it (the 🎯 and combo floor).
  const tooShort = b => b.best_odds < 1.30
  // Under 50% by the market it is more likely to lose than to win.
  const unlikely = b => b.market_probability != null && b.market_probability < 0.5
  const backingGroup = b => (modelBacks(b) && !tooShort(b) && !unlikely(b)) ? (aiBacks(b) ? 0 : 1) : 2
  const ordered = [...allBets].sort((a, b) =>
    signalRank(a) - signalRank(b)
    || backingGroup(a) - backingGroup(b)
    || (b.market_probability ?? 0) - (a.market_probability ?? 0))
  const visibleRows = showAllMarkets ? ordered : ordered.slice(0, TABLE_ROWS)
  const hiddenCount = ordered.length - TABLE_ROWS
  const hasUserBook = (betInfo.bets || []).some(b => b.bookmaker_key === USER_BOOK_KEY)

  // Greyed out: the model does not back the bet, or it pays under 1.30.
  const dimmed = b => !modelBacks(b) || tooShort(b) || unlikely(b)

  const renderRow = (b, i, kind) => {
    const isRec = best && sameBet(b, best)
    const isPriceTip = priceTipPick && sameBet(b, priceTipPick)
    const isAgentPick = agentPick && sameBet(b, agentPick)
    const isLikelyPick = likelyPick && sameBet(b, likelyPick)
    // A marked tip (💰 🎯 ✨ ★) is a headline of its own: never greyed.
    const keepFullOpacity = isPriceTip || isAgentPick || isLikelyPick
    return (
      <div className={`smart-bet-table-row ${dimmed(b) && !keepFullOpacity ? 'is-red' : ''} ${isPriceTip ? 'is-rec' : ''}`}
           key={`${kind}-${i}`}>
        <span className="smart-bet-col-market">{marketGroupLabel(b.market)}{b.suspicious ? ' ⚠' : ''}</span>
        <span className="smart-bet-col-pick">
          {isPriceTip ? '💰 ' : ''}{isLikelyPick ? '🎯 ' : ''}{isAgentPick ? '✨ ' : ''}{betOutcomeLabel(b)}
          {aiBacks(b) && !isAgentPick && <span className="smart-bet-backing" title={tr('KI stimmt zu', 'AI agrees')}>✨</span>}
        </span>
        <span className="smart-bet-col-odds" title={b.bookmaker}>
          {b.best_odds.toFixed(2)}{b.bookmaker_key !== USER_BOOK_KEY && hasUserBook ? '*' : ''}
        </span>
        <span className="smart-bet-col-chance">
          {b.market_probability != null ? `${Math.round(b.market_probability * 100)}%` : '–'}
        </span>
      </div>
    )
  }

  return (
    <div className="wm-reveal smart-bet-card">
      <BetTipBox betTip={computeBetTip(betInfo, agentPick, sameBet)} />

      {(greens.length > 0 || reds.length > 0) && (
        <div className="smart-bet-table">
          <div className="smart-bet-table-head">
            <span>{tr('Markt', 'Market')}</span>
            <span>{tr('Tipp', 'Pick')}</span>
            <span>{tr('Quote', 'Odds')}</span>
            <span>{tr('Chance', 'Chance')}</span>
          </div>
          {visibleRows.map((b, i) => renderRow(b, i, 'row'))}
          {hiddenCount > 0 && (
            <button className="smart-bet-more" onClick={() => setShowAllMarkets(v => !v)}>
              {showAllMarkets ? tr('Weniger Märkte ▲', 'Fewer markets ▲') : tr(`Alle Märkte zeigen (${hiddenCount} weitere) ▼`, `Show all markets (${hiddenCount} more) ▼`)}
            </button>
          )}
          <p className="smart-bet-table-note">
            {hasUserBook
              ? tr('Quoten von bet-at-home. * = bei bet-at-home nicht im Angebot, beste andere Quote gezeigt.', "Odds from bet-at-home. * = not offered by bet-at-home, best other price shown.")
              : tr('Die vollen Märkte von bet-at-home werden in der Stunde vor Anpfiff gelesen; bis dahin zeigen wir die besten verfügbaren Quoten.', "bet-at-home's full markets are read in the hour before kickoff; until then we show the best available prices.")}
          </p>
        </div>
      )}

      {agentEval && (
        <div className="smart-bet-agent">
          <div className="smart-bet-agent-headtitle">
            <span className="smart-bet-agent-headline">✨ {tr('KI-Tipp', 'AI tip')}: {aiEn?.bet_headline || agentEval.bet_headline}</span>
          </div>
          <p className="smart-bet-agent-text">
            {renderBoldMarkdown(aiEn?.bet_reasoning || agentEval.bet_reasoning, 'smart-bet-highlight-purple')}
            {agentPick && (
              <> {tr('Unser Modell sieht das bei', 'Our model puts this at')} <strong className="smart-bet-highlight-purple">{(agentPick.probability * 100).toFixed(0)}%</strong>.</>
            )}
          </p>
        </div>
      )}

      <PriceTipBox priceTip={betInfo.price_tip} />
      <LikelyTipBox pick={likelyPick} />

      <LineupStrength data={data} />

      <div className="smart-bet-finePrint">
        {LANG === 'en' ? (
          <p>
            <strong>Bet tip</strong> = the likeliest bet both the model and the AI agree with (odds from 1.30, chance from 50%) ·
            {' '}<strong>💰</strong> bet-at-home pays more than Pinnacle's fair price · <strong>🎯</strong> the market's
            likeliest bet (odds 1.30–2.00; no edge, the margin is built in) · <strong>✨</strong> the AI's pick after research ·
            {' '}<strong>⚠</strong> more likely a model error · <strong>✨</strong> after a pick: the AI agrees; grey = the model
            does not agree, odds under 1.30 or chance under 50%. <strong>+0.5</strong> = double chance, <strong>0.0</strong> = draw no bet,
            other numbers = Asian handicap.
          </p>
        ) : (
          <p>
            <strong>Wett-Tipp</strong> = wahrscheinlichste Wette, der Modell und KI zustimmen (Quote ab 1,30, Chance ab 50 %) ·
            {' '}<strong>💰</strong> bet-at-home zahlt mehr als Pinnacles fairer Preis · <strong>🎯</strong> laut Markt
            wahrscheinlichste Wette (Quote 1,30–2,00; kein Vorteil, die Marge steckt drin) · <strong>✨</strong> Tipp der KI
            nach Recherche · <strong>⚠</strong> eher ein
            Modellfehler · <strong>✨</strong> hinter einem Tipp: die KI stimmt zu; grau = Modell stimmt nicht zu, Quote unter 1,30 oder Chance unter 50 %. <strong>+0,5</strong> = Doppelte Chance, <strong>0,0</strong> = Einsatz zurück bei Remis,
            andere Zahlen = Asian Handicap.
          </p>
        )}

      <p className="smart-bet-disclaimer">
        {tr('Nur zur Unterhaltung und Information. Das ist ein statistisches Modell, keine Wettberatung – es garantiert keinen Gewinn und hat keinen nachgewiesenen Vorteil gegenüber den Quoten der Buchmacher. Wetten kann zu finanziellen Verlusten führen; wenn du wettest, dann verantwortungsvoll und nur mit Geld, dessen Verlust du verkraften kannst. 18+. Hilfe bei Glücksspielproblemen: check-dein-spiel.de, Tel. 0800 1 37 27 00 (kostenlos).',
            'For entertainment and information only. This is a statistical model, not betting advice – it guarantees no profit and has no proven edge over the bookmakers\' odds. Betting can lead to financial losses; if you bet, do so responsibly and only with money you can afford to lose. 18+. Help with gambling problems: check-dein-spiel.de, tel. 0800 1 37 27 00 (free, Germany).')}
      </p>
      </div>
    </div>
  )
}

function HeadToHeadStat({ label, home, away, suffix = '' }) {
  const total = home + away
  const homePct = total > 0 ? (home / total) * 100 : 50
  return (
    <div className="h2h-row">
      <span className="h2h-value h2h-home"><AnimatedNumber value={home} suffix={suffix} /></span>
      <div className="h2h-mid">
        <span className="h2h-label">{label}</span>
        <div className="h2h-bar-track">
          <AnimatedBarFill className="h2h-bar-home" targetPct={homePct} />
          <AnimatedBarFill className="h2h-bar-away" targetPct={100 - homePct} />
        </div>
      </div>
      <span className="h2h-value h2h-away"><AnimatedNumber value={away} suffix={suffix} /></span>
    </div>
  )
}

function RevealSection({ visible, className = '', children }) {
  if (!visible) return null
  return <div className={`wm-reveal ${className}`}>{children}</div>
}

function WmPredictionCard({ matchId, data, fixture, onCollapse, revealStep = Infinity, betStep, onStartBetCheck, betInfo }) {
  const sp = data.score_prediction || {}
  const gf = data.game_flow || {}
  const ps = gf.predicted_stats || {}
  // Real kit colours per side, with a guard so two similar ones stay apart.
  const matchColors = getMatchColors(data.home_team, data.away_team)

  const analyzing = revealStep < ANALYZING_STEPS.length
  const show = (n) => revealStep >= n

  return (
    <div className="card wm-card" id={`match-${matchId}`}>
      <div className="wm-card-header">
        <span className="wm-match-id">
          {fixture ? fixtureWhen(fixture) : matchId}
        </span>
        <div className="wm-card-header-right">
          {onCollapse && !analyzing && (
            <button className="wm-collapse-btn" onClick={onCollapse}>
              {tr('Einklappen ▲', 'Collapse ▲')}
            </button>
          )}
        </div>
      </div>

      <div className="result-header">
        <span className="team-name"><TeamLabel name={data.home_team} /></span>
        <div className="prediction-badge">
          {data.prediction === 'H' ? tr(`${teamName(data.home_team)} gewinnt`, `${teamName(data.home_team)} to win`) :
           data.prediction === 'A' ? tr(`${teamName(data.away_team)} gewinnt`, `${teamName(data.away_team)} to win`) : tr('Remis', 'Draw')}
        </div>
        <span className="team-name"><TeamLabel name={data.away_team} /></span>
      </div>

      <FormRating data={data} />

      {analyzing && (
        <div className="analyzing-status">
          <span className="analyzing-spinner" />
          <span>{tr(...ANALYZING_STEPS[revealStep])}</span>
        </div>
      )}

      <div className="wm-cluster">

        <RevealSection visible={show(1)} className="probabilities-donut">
          <ResultDonut
            home={data.probability_home_win}
            draw={data.probability_draw}
            away={data.probability_away_win}
            score={sp.most_likely_score}
            colors={matchColors}
          />
          <div className="probabilities-legend">
            <span className="legend-title">{tr('Siegwahrscheinlichkeit', 'Win probability')}</span>
            <div className="legend-row">
              <span className="legend-dot" style={{ background: matchColors.home }} />
              <span className="legend-name"><TeamLabel name={data.home_team} /></span>
              <span className="legend-value"><AnimatedNumber value={data.probability_home_win * 100} decimals={1} suffix="%" /></span>
            </div>
            <div className="legend-row">
              <span className="legend-dot gray" />
              <span className="legend-name">{tr('Remis', 'Draw')}</span>
              <span className="legend-value"><AnimatedNumber value={data.probability_draw * 100} decimals={1} suffix="%" /></span>
            </div>
            <div className="legend-row">
              <span className="legend-dot" style={{ background: matchColors.away }} />
              <span className="legend-name"><TeamLabel name={data.away_team} /></span>
              <span className="legend-value"><AnimatedNumber value={data.probability_away_win * 100} decimals={1} suffix="%" /></span>
            </div>
          </div>
        </RevealSection>

        <RevealSection visible={show(2)}>
          <MatchScenario data={data} />
        </RevealSection>
      </div>

      {!analyzing && (
        <details className="wm-details">
          <summary>{tr('Mehr Details: Märkte, Ergebnisse & Halbzeit', 'More details: markets, scores & half time')}</summary>
          <div className="wm-cluster">
            <BettingMarkets data={data} />
            <div className="explanation-grid wm-grid">
              <div className="stat-card">
                <h4>{tr('Wahrscheinlichste Ergebnisse', 'Most likely scores')}</h4>
                <p className="wm-subtle wm-scoreboard-xg">
                  xG: {Number(sp.home_xg).toFixed(2)} : {Number(sp.away_xg).toFixed(2)}
                </p>
                {(sp.top_scorelines || []).slice(0, 3).map((s, i) => (
                  <div className={`score-row${i === 0 ? ' is-leader' : ''}`} key={i}>
                    <span className="score-row-rank">{i === 0 ? '★' : i + 1}</span>
                    <span className="score-row-label">{s.score}</span>
                    <span className="score-row-value">{(s.probability * 100).toFixed(1).replace('.', DEC())}%</span>
                  </div>
                ))}
              </div>
              <div className="stat-card">
                <h4>{tr('Halbzeit', 'Half time')}</h4>
                {(gf.top_halftime_scores || []).slice(0, 3).map((h, i) => (
                  <div className={`score-row${i === 0 ? ' is-leader' : ''}`} key={i}>
                    <span className="score-row-rank">{i === 0 ? '★' : i + 1}</span>
                    <span className="score-row-label">{h.score}</span>
                    <span className="score-row-value">{(h.probability * 100).toFixed(1).replace('.', DEC())}%</span>
                  </div>
                ))}
                <div className="score-row is-drama">
                  <span className="score-row-rank">⚡</span>
                  <span className="score-row-label score-row-label-wide">{tr("Spätes Drama (75'+)", "Late drama (75'+)")}</span>
                  <span className="score-row-value">{((gf.late_drama_probability || 0) * 100).toFixed(0)}%</span>
                </div>
              </div>
            </div>
          </div>
        </details>
      )}

      {!analyzing && betInfo && betInfo.agent_eval && betInfo.agent_eval.research && (
        <div className="wm-cluster wm-cluster-scout">
          <AgentFactors research={betInfo.agent_eval.research} home={data.home_team} away={data.away_team} />
        </div>
      )}

      {!analyzing && onStartBetCheck && (
        <div className="wm-cluster wm-cluster-bet">
          <span className="wm-cluster-label">{tr('Wett-Analyse', 'Bet analysis')}</span>

          {onStartBetCheck && (
            <div className="smart-bet-section" id={`bets-${matchId}`}>
              {betStep === undefined ? (
                <div className="smart-bet-cta">
                  <span className="smart-bet-cta-icon">🎯</span>
                  <h4 className="smart-bet-cta-title">{tr('Modell gegen Buchmacher-Quoten?', "Model vs the bookmakers' odds?")}</h4>
                  <p className="smart-bet-cta-sub">
                    {tr('Wo Modell und Markt übereinstimmen, wo nicht – mit einem Tipp.', "Where the model and the market agree, where they don't – with a tip.")}
                  </p>
                  <button className="smart-bet-btn" onClick={onStartBetCheck}>
                    {tr('Quoten-Vergleich zeigen', 'Show the odds comparison')}
                  </button>
                </div>
              ) : (
                <SmartBetCard betStep={betStep} betInfo={betInfo} data={data} />
              )}
            </div>
          )}
        </div>
      )}
    </div>
  )
}

function IconDataPoints() {
  return (
    <svg viewBox="0 0 40 40" fill="none" xmlns="http://www.w3.org/2000/svg">
      <circle cx="8" cy="8" r="3" fill="currentColor" opacity="0.35" />
      <circle cx="20" cy="8" r="3" fill="currentColor" opacity="0.6" />
      <circle cx="32" cy="8" r="3" fill="currentColor" opacity="0.35" />
      <circle cx="8" cy="20" r="3" fill="currentColor" opacity="0.6" />
      <circle cx="20" cy="20" r="4.5" fill="currentColor" />
      <circle cx="32" cy="20" r="3" fill="currentColor" opacity="0.6" />
      <circle cx="8" cy="32" r="3" fill="currentColor" opacity="0.35" />
      <circle cx="20" cy="32" r="3" fill="currentColor" opacity="0.6" />
      <circle cx="32" cy="32" r="3" fill="currentColor" opacity="0.35" />
    </svg>
  )
}

function IconNeuralNet() {
  return (
    <svg viewBox="0 0 40 40" fill="none" xmlns="http://www.w3.org/2000/svg">
      <g stroke="currentColor" strokeWidth="1.2" opacity="0.5">
        <line x1="7" y1="8" x2="20" y2="20" />
        <line x1="7" y1="32" x2="20" y2="20" />
        <line x1="7" y1="20" x2="20" y2="20" />
        <line x1="20" y1="20" x2="33" y2="8" />
        <line x1="20" y1="20" x2="33" y2="20" />
        <line x1="20" y1="20" x2="33" y2="32" />
      </g>
      <circle cx="7" cy="8" r="2.5" fill="currentColor" />
      <circle cx="7" cy="20" r="2.5" fill="currentColor" />
      <circle cx="7" cy="32" r="2.5" fill="currentColor" />
      <circle cx="20" cy="20" r="4" fill="currentColor" />
      <circle cx="33" cy="8" r="2.5" fill="currentColor" />
      <circle cx="33" cy="20" r="2.5" fill="currentColor" />
      <circle cx="33" cy="32" r="2.5" fill="currentColor" />
    </svg>
  )
}

function IconSpark() {
  return (
    <svg viewBox="0 0 40 40" fill="none" xmlns="http://www.w3.org/2000/svg">
      <path d="M20 4 L24 17 L37 20 L24 23 L20 36 L16 23 L3 20 L16 17 Z" fill="currentColor" />
      <circle cx="32" cy="9" r="2" fill="currentColor" opacity="0.6" />
      <circle cx="9" cy="32" r="1.6" fill="currentColor" opacity="0.45" />
    </svg>
  )
}

function IconInfinity() {
  return (
    <svg viewBox="0 0 40 40" fill="none" xmlns="http://www.w3.org/2000/svg">
      <path
        d="M12 14C7 14 4 17 4 20C4 23 7 26 12 26C18 26 22 14 28 14C33 14 36 17 36 20C36 23 33 26 28 26C22 26 18 14 12 14Z"
        stroke="currentColor"
        strokeWidth="2.5"
      />
    </svg>
  )
}

function IconFeatures() {
  return (
    <svg viewBox="0 0 40 40" fill="none" xmlns="http://www.w3.org/2000/svg">
      <g stroke="currentColor" strokeWidth="2.5" strokeLinecap="round">
        <line x1="6" y1="10" x2="34" y2="10" />
        <line x1="6" y1="20" x2="34" y2="20" />
        <line x1="6" y1="30" x2="34" y2="30" />
      </g>
      <circle cx="14" cy="10" r="3.5" fill="currentColor" />
      <circle cx="26" cy="20" r="3.5" fill="currentColor" />
      <circle cx="18" cy="30" r="3.5" fill="currentColor" />
    </svg>
  )
}

function IconTarget() {
  return (
    <svg viewBox="0 0 40 40" fill="none" xmlns="http://www.w3.org/2000/svg">
      <circle cx="20" cy="20" r="16" stroke="currentColor" strokeWidth="2.2" opacity="0.35" />
      <circle cx="20" cy="20" r="10" stroke="currentColor" strokeWidth="2.2" opacity="0.6" />
      <circle cx="20" cy="20" r="4" fill="currentColor" />
    </svg>
  )
}

function IconTimeline() {
  return (
    <svg viewBox="0 0 40 40" fill="none" xmlns="http://www.w3.org/2000/svg">
      <line x1="4" y1="20" x2="36" y2="20" stroke="currentColor" strokeWidth="2" opacity="0.4" />
      <circle cx="9" cy="20" r="3" fill="currentColor" />
      <circle cx="20" cy="20" r="4.5" fill="currentColor" />
      <circle cx="31" cy="20" r="3" fill="currentColor" />
      <path d="M20 20 L20 8" stroke="currentColor" strokeWidth="2" strokeLinecap="round" opacity="0.6" />
      <path d="M16 8 L20 4 L24 8" stroke="currentColor" strokeWidth="2" fill="none" strokeLinecap="round" strokeLinejoin="round" opacity="0.6" />
    </svg>
  )
}

function IconBroadcast() {
  return (
    <svg viewBox="0 0 40 40" fill="none" xmlns="http://www.w3.org/2000/svg">
      <circle cx="20" cy="20" r="4" fill="currentColor" />
      <g stroke="currentColor" strokeWidth="2" fill="none" strokeLinecap="round">
        <path d="M13 13a10 10 0 000 14" opacity="0.7" />
        <path d="M27 13a10 10 0 010 14" opacity="0.7" />
        <path d="M8 8a17 17 0 000 24" opacity="0.4" />
        <path d="M32 8a17 17 0 010 24" opacity="0.4" />
      </g>
    </svg>
  )
}

function IconArrowDown() {
  return (
    <svg viewBox="0 0 24 32" fill="none" xmlns="http://www.w3.org/2000/svg">
      <line x1="12" y1="0" x2="12" y2="22" stroke="currentColor" strokeWidth="2" opacity="0.4" />
      <path d="M5 17 L12 26 L19 17" stroke="currentColor" strokeWidth="2" fill="none" strokeLinecap="round" strokeLinejoin="round" opacity="0.4" />
    </svg>
  )
}

function HeroVisual() {
  return (
    <svg className="hero-visual" viewBox="0 0 800 360" fill="none" xmlns="http://www.w3.org/2000/svg" preserveAspectRatio="xMidYMid slice">
      <defs>
        <radialGradient id="heroGlow" cx="50%" cy="50%" r="50%">
          <stop offset="0%" stopColor="#d4af37" stopOpacity="0.12" />
          <stop offset="100%" stopColor="#d4af37" stopOpacity="0" />
        </radialGradient>
      </defs>
      <circle cx="400" cy="60" r="260" fill="url(#heroGlow)" />
      <g stroke="#d4af37" strokeWidth="1" opacity="0.15">
        <line x1="60" y1="40" x2="200" y2="20" />
        <line x1="600" y1="30" x2="740" y2="60" />
        <line x1="600" y1="30" x2="690" y2="100" />
        <line x1="60" y1="40" x2="40" y2="120" />
        <line x1="740" y1="60" x2="760" y2="140" />
      </g>
      <g fill="#f4cf6e">
        <circle cx="60" cy="40" r="3" opacity="0.4" />
        <circle cx="200" cy="20" r="2.5" opacity="0.3" />
        <circle cx="600" cy="30" r="3" opacity="0.4" />
        <circle cx="740" cy="60" r="2.5" opacity="0.35" />
        <circle cx="690" cy="100" r="2.5" opacity="0.3" />
        <circle cx="40" cy="120" r="2.5" opacity="0.3" />
        <circle cx="760" cy="140" r="2.5" opacity="0.3" />
      </g>
    </svg>
  )
}

function ResultDonut({ home, draw, away, homeLabel, awayLabel, score, colors }) {
  const r = 40
  const C = 2 * Math.PI * r
  const segs = [
    { v: home, color: colors?.home || 'var(--gold)' },
    { v: draw, color: colors?.draw || '#6b7280' },
    { v: away, color: colors?.away || 'var(--cyan)' },
  ]
  let offset = 0
  return (
    <div className="result-donut">
      <svg viewBox="0 0 100 100">
        <circle cx="50" cy="50" r={r} fill="none" stroke="rgba(255,255,255,0.07)" strokeWidth="11" />
        {segs.map((s, i) => {
          const len = Math.max(s.v * C - 2, 0)
          const el = (
            <circle
              key={i}
              cx="50" cy="50" r={r} fill="none"
              stroke={s.color} strokeWidth="11" strokeLinecap="round"
              strokeDasharray={`${len} ${C - len}`}
              strokeDashoffset={-offset}
              transform="rotate(-90 50 50)"
              className="result-donut-seg"
            />
          )
          offset += s.v * C
          return el
        })}
      </svg>
      <div className="result-donut-center">
        <span className="result-donut-score">{score}</span>
      </div>
    </div>
  )
}

// How many days one competition's matchday spans: Champions League rounds run
// Tuesday to Thursday, Bundesliga Friday to Sunday (sometimes Monday). A
// Nations League "matchday" on this site is one evening, as in its tabs.
const MATCHDAY_SPAN_DAYS = { cl: 3, bl: 4, nl: 1 }
const berlinDate = (iso) => new Date(iso).toLocaleDateString('sv-SE', { timeZone: 'Europe/Berlin' })

function lastMatchday(results, key) {
  const done = results
    .filter(r => r.completed && r.sport_key === COMPETITIONS[key].sportKey)
    .sort((a, b) => new Date(b.commence_time) - new Date(a.commence_time))
  if (done.length === 0) return []
  const latest = new Date(berlinDate(done[0].commence_time))
  const span = MATCHDAY_SPAN_DAYS[key] || 1
  return done.filter(r => (latest - new Date(berlinDate(r.commence_time))) / 86400000 < span)
}

// Before anyone picks a competition, the ticker mixes the headline results
// of every competition's last matchday; after, it follows the chosen one.
function tickerResults(results, competitionKey) {
  if (competitionKey) {
    return lastMatchday(results, competitionKey)
      .sort((a, b) => new Date(a.commence_time) - new Date(b.commence_time))
  }
  const byValue = (a, b) => (b.headline_value || 0) - (a.headline_value || 0)
  return Object.keys(COMPETITIONS)
    .flatMap(key => lastMatchday(results, key).sort(byValue).slice(0, 5))
    .sort(byValue)
}

function MatchTicker({ results, competitionKey }) {
  const items = tickerResults(results || [], competitionKey)
  if (items.length === 0) return null
  // The track scrolls by half its width, so the list is repeated; a short
  // matchday is repeated until it fills the bar.
  let loop = [...items]
  while (loop.length < 12) loop = [...loop, ...items]
  loop = [...loop, ...loop]
  return (
    <div className="match-ticker">
      <div className="match-ticker-track">
        {loop.map((r, i) => (
          <span className="match-ticker-item" key={`${r.result_event_id}-${i}`}>
            <span className="match-ticker-team"><TeamLabel name={r.home_team} /></span>
            <span className="match-ticker-score">{r.home_score}:{r.away_score}</span>
            <span className="match-ticker-team"><TeamLabel name={r.away_team} /></span>
            <span className="match-ticker-date">{berlinDate(r.commence_time).slice(5).split('-').reverse().join('.')}</span>
          </span>
        ))}
      </div>
    </div>
  )
}

// The landing card's sample match, with form numbers for the tug of war.
const HERO_SAMPLE = {
  home_team: 'Real Madrid', away_team: 'Bayern Munich',
  explanation: {
    form_last_10_avg_pts: { 'Real Madrid': 2.2, 'Bayern Munich': 2.5 },
    win_rate_last_10: { 'Real Madrid': '70%', 'Bayern Munich': '80%' },
    avg_goals_scored: { 'Real Madrid': 2.1, 'Bayern Munich': 2.8 },
    avg_goals_conceded: { 'Real Madrid': 1.0, 'Bayern Munich': 0.9 },
    clean_sheet_rate: { 'Real Madrid': '30%', 'Bayern Munich': '40%' },
  },
}

// The landing card doubles as a call to action: a click opens the next
// Bundesliga matchday.
function HeroPreviewCard({ onOpen }) {
  const colors = getMatchColors('Real Madrid', 'Bayern Munich')
  return (
    <div className="hero-preview card is-clickable" role="button" tabIndex={0} onClick={onOpen}
         onKeyDown={e => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); onOpen?.() } }}
         aria-label={tr('Zu den Bundesliga-Prognosen', 'Go to the Bundesliga predictions')}>
      <div className="hero-preview-badge">
        <span className="hero-preview-badge-dot" />
        {tr('KI-Prognose', 'AI prediction')}
      </div>
      <div className="hero-preview-teams">
        <span className="hero-preview-team"><TeamLabel name="Real Madrid" /></span>
        <span className="hero-preview-vs">vs</span>
        <span className="hero-preview-team"><TeamLabel name="Bayern Munich" /></span>
      </div>
      {/* The same blocks as a match page: win chances, then the form. */}
      <div className="probabilities-donut hero-preview-probs">
        <ResultDonut home={0.36} draw={0.24} away={0.40} score="1–2" colors={colors} />
        <div className="probabilities-legend">
          <span className="legend-title">{tr('Siegwahrscheinlichkeit', 'Win probability')}</span>
          <div className="legend-row">
            <span className="legend-dot" style={{ background: colors.home }} />
            <span className="legend-name"><TeamLabel name="Real Madrid" /></span>
            <span className="legend-value"><AnimatedNumber value={36} decimals={1} suffix="%" /></span>
          </div>
          <div className="legend-row">
            <span className="legend-dot gray" />
            <span className="legend-name">{tr('Remis', 'Draw')}</span>
            <span className="legend-value"><AnimatedNumber value={24} decimals={1} suffix="%" /></span>
          </div>
          <div className="legend-row">
            <span className="legend-dot" style={{ background: colors.away }} />
            <span className="legend-name"><TeamLabel name="Bayern Munich" /></span>
            <span className="legend-value"><AnimatedNumber value={40} decimals={1} suffix="%" /></span>
          </div>
        </div>
      </div>
      <FormRating data={HERO_SAMPLE} compact />
      {/* An example of the Wett-Tipp as the match page shows it, in the
          card's own gold rather than the tip's green. */}
      <div className="hero-preview-tip">
        <span className="hero-preview-tip-label">{tr('Wett-Tipp', 'Bet tip')}</span>
        <div className="hero-preview-tip-row">
          <span className="hero-preview-tip-pick">{tr('Über 2,5 Tore', 'Over 2.5 goals')}</span>
          <span className="hero-preview-tip-odds">{deNum('1.55')}</span>
          <span className="hero-preview-tip-chance">62% {tr('Chance', 'chance')}</span>
        </div>
        <div className="hero-preview-tip-chips">
          <span>◆ {tr('Modell stimmt zu', 'Model agrees')} ✓</span>
          <span>✨ {tr('KI stimmt zu', 'AI agrees')} ✓</span>
        </div>
      </div>
    </div>
  )
}

// The seven stages of "So funktioniert's", in the page's language.
const flowSteps = () => [
  {
    icon: <IconDataPoints />,
    title: tr('Daten sammeln', 'Data ingestion'),
    description: tr(
      'Jede Analyse beginnt mit echter Fußballhistorie – mehrere Spielzeiten an Ergebnissen, Liga- und Pokaldaten sowie laufende Form- und Torstatistiken für jedes Team, das wir abdecken.',
      'Every analysis starts with real football history – several seasons of results, league and cup data, and rolling form and goal statistics for every team we cover.'),
    tags: [tr('Historische Ergebnisse', 'Historical results'), tr('Direkte Duelle', 'Head-to-head'), tr('Torstatistik', 'Goal stats'), tr('Aktuelle Form', 'Current form')],
  },
  {
    icon: <IconFeatures />,
    title: tr('Merkmale berechnen', 'Feature engineering'),
    description: tr(
      'Aus den Rohdaten werden Signale, aus denen die Modelle lernen können: Elo-Stärkewerte, Angriffs- und Abwehrwerte pro Team, die Bilanz der direkten Duelle, der Heimvorteil und die Formkurve aus den letzten Spielen.',
      'The raw data becomes signals the models can learn from: Elo strength ratings, attack and defence ratings per team, the head-to-head record, home advantage and the form of the last games.'),
    tags: [tr('Elo-Werte', 'Elo ratings'), tr('Angriff & Abwehr', 'Attack & defence'), tr('Direkte Duelle', 'Head-to-head'), tr('Heimvorteil', 'Home advantage')],
  },
  {
    icon: <IconNeuralNet />,
    title: tr('Modell-Ensemble', 'Model ensemble'),
    description: tr(
      'Drei unabhängige Modelle rechnen jedes Spiel parallel durch – ein Dixon-Coles-Poisson-Modell für realistische Ergebnisse, ein XGBoost-Modell für nichtlineare Muster und ein Random Forest für Stabilität. Ihre Ergebnisse werden zu einem gemeinsamen Urteil kombiniert.',
      'Three independent models work through every match in parallel – a Dixon-Coles Poisson model for realistic scores, an XGBoost model for non-linear patterns and a random forest for stability. Their results are combined into one verdict.'),
    tags: ['Dixon-Coles-Poisson', 'XGBoost', 'Random Forest', 'Ensemble'],
  },
  {
    icon: <IconTarget />,
    title: tr('Ergebnis & Wahrscheinlichkeiten', 'Score & probabilities'),
    description: tr(
      'Das Ensemble liefert eine Wahrscheinlichkeit für jedes realistische Ergebnis und leitet daraus die Chancen auf Sieg, Remis und Niederlage, das wahrscheinlichste Endergebnis und die erwarteten Tore (xG) beider Teams ab.',
      'The ensemble gives a probability for every realistic score and derives the chances of a win, a draw and a loss, the most likely final score and both teams\' expected goals (xG).'),
    tags: [tr('Sieg/Remis/Niederlage %', 'Win/draw/loss %'), tr('Wahrscheinlichstes Ergebnis', 'Most likely score'), tr('Erwartete Tore (xG)', 'Expected goals (xG)')],
  },
  {
    icon: <IconTimeline />,
    title: tr('Spielverlauf', 'Game flow'),
    description: tr(
      'Eine eigene Spielverlaufs-Berechnung schätzt, wie sich die 90 Minuten entwickeln – wann Tore fallen, der Halbzeitstand, spätes Drama – und ordnet den Charakter des Spiels ein, von „Abwehrschlacht“ bis „Torfestival“.',
      'A dedicated game-flow model estimates how the 90 minutes unfold – when goals fall, the half-time score, late drama – and classifies the match, from "defensive battle" to "goal fest".'),
    tags: [tr('Tor-Zeitpunkte', 'Goal timing'), tr('Halbzeit & Endstand', 'Half time & full time'), tr('Spieltyp', 'Match type'), tr('Spätes Drama', 'Late drama')],
  },
  {
    icon: <IconSpark />,
    title: tr('KI-Einordnung', 'AI summary'),
    description: tr(
      'Eine KI fasst die berechneten Zahlen in einem Satz zusammen, den Fußballfans verstehen. Sie darf nur die Zahlen des Modells verwenden – keine erfundenen Fakten –, damit der Text der Prognose nie widerspricht.',
      'An AI sums up the calculated numbers in a sentence football fans understand. It may only use the model\'s numbers – no invented facts – so the text never contradicts the prediction.'),
    tags: [tr('KI-Zusammenfassung', 'AI summary'), tr('Nur Modell-Zahlen', 'Model numbers only'), tr('Keine erfundenen Fakten', 'No invented facts')],
  },
  {
    icon: <IconBroadcast />,
    title: tr('Veröffentlichung', 'Publishing'),
    description: tr(
      'Die fertige Analyse wird gespeichert und ist sofort auf der Website abrufbar – Wahrscheinlichkeiten, Ergebnis und Spielverlauf. Dieselben Zahlen landen automatisch als Kurzvideo auf TikTok und Instagram.',
      'The finished analysis is stored and available on the site right away – probabilities, score and game flow. The same numbers go out automatically as a short video on TikTok and Instagram.'),
    tags: [tr('Website', 'Website'), 'TikTok & Instagram', tr('Automatisiert', 'Automated'), tr('Sofort verfügbar', 'Instantly available')],
  },
]

function FlowStepGraphic({ icon, cyan }) {
  const particles = [0, 1, 2, 3, 4, 5].map(i => {
    const angle = (i * 60 * Math.PI) / 180
    return { cx: 85 + 62 * Math.cos(angle), cy: 85 + 62 * Math.sin(angle), delay: i * 0.28 }
  })
  return (
    <div className={`flow-graphic${cyan ? ' cyan' : ''}`}>
      <div className="flow-graphic-rings">
        <span className="flow-ring r1" />
        <span className="flow-ring r2" />
        <span className="flow-ring r3" />
      </div>
      <svg className="flow-graphic-particles" viewBox="0 0 170 170">
        {particles.map((p, i) => (
          <circle key={i} className="flow-particle" cx={p.cx} cy={p.cy} r="3" style={{ animationDelay: `${p.delay}s` }} />
        ))}
      </svg>
      <div className="flow-graphic-core">{icon}</div>
    </div>
  )
}

function AnalysisFlowPage({ onBack }) {
  const FLOW_STEPS = flowSteps()
  const [activeIndex, setActiveIndex] = useState(0)
  const sectionRefs = useRef([])

  useEffect(() => {
    const observers = sectionRefs.current.map((el, i) => {
      if (!el) return null
      const obs = new IntersectionObserver(
        (entries) => {
          entries.forEach(entry => {
            if (entry.isIntersecting) {
              el.classList.add('in-view')
              setActiveIndex(i)
            } else {
              el.classList.remove('in-view')
            }
          })
        },
        { threshold: 0.4, rootMargin: '-15% 0px -15% 0px' }
      )
      obs.observe(el)
      return obs
    })
    return () => observers.forEach(o => o && o.disconnect())
  }, [])

  const goTo = (i) => {
    sectionRefs.current[i]?.scrollIntoView({ behavior: 'smooth', block: 'center' })
  }

  return (
    <section className="flow-section-scroll">
      <div className="card flow-scroll-header">
        <span className="how-eyebrow">{tr('Hinter den Prognosen', 'Behind the predictions')}</span>
        <h2 className="section-title">{tr('So funktioniert unsere KI-Analyse', 'How our AI analysis works')}</h2>
        <p className="how-intro">
          {tr('Vom ersten Datenpunkt bis zum fertigen Social-Media-Video – jede Prognose durchläuft dieselben sieben Stufen. Scroll nach unten und folge den Daten durch jede Stufe.',
              'From the first data point to the finished social video – every prediction passes through the same seven stages. Scroll down and follow the data through each one.')}
        </p>
        <button className="flow-back-btn" onClick={onBack}>{tr('← Zurück zu den Prognosen', '← Back to the predictions')}</button>
      </div>

      <div className="flow-scroll-body">
        <div className="flow-scroll-rail">
          <div
            className="flow-scroll-rail-fill"
            style={{ height: `${(activeIndex / (FLOW_STEPS.length - 1)) * 100}%` }}
          />
          {FLOW_STEPS.map((s, i) => (
            <button
              key={s.title}
              className={'flow-rail-dot' + (i === activeIndex ? ' active' : '') + (i < activeIndex ? ' done' : '')}
              onClick={() => goTo(i)}
              aria-label={s.title}
              title={s.title}
            >
              {i < activeIndex ? '✓' : i + 1}
            </button>
          ))}
        </div>

        <div className="flow-scroll-steps">
          {FLOW_STEPS.map((step, i) => (
            <div
              className={`flow-scroll-step${i % 2 === 1 ? ' reverse' : ''}`}
              key={step.title}
              ref={(el) => { sectionRefs.current[i] = el }}
            >
              <FlowStepGraphic icon={step.icon} cyan={i % 2 === 1} />
              <div className="flow-scroll-text">
                <span className="flow-scroll-step-num">{tr('Stufe', 'Stage')} {i + 1} / {FLOW_STEPS.length}</span>
                <h3>{step.title}</h3>
                <p>{step.description}</p>
                <div className="flow-step-tags">
                  {step.tags.map(tag => (
                    <span className="flow-tag" key={tag}>{tag}</span>
                  ))}
                </div>
              </div>
            </div>
          ))}
        </div>
      </div>

      <button className="flow-nav-btn primary flow-scroll-end-btn" onClick={onBack}>
        {tr('Zurück zu den Prognosen', 'Back to the predictions')}
      </button>
    </section>
  )
}

function buildRealResultsMap(results) {
  const map = {}
  for (const r of results) {
    // The date is part of the key: the same pairing can meet twice in a
    // season, and each meeting must show its own result.
    map[`${r.home_team}__${r.away_team}__${berlinDate(r.commence_time)}`] = r
  }
  return map
}

// ESPN minutes read "32'", "45'+2'" or "90'+4'"; stoppage time counts with
// the half it belongs to.
function tickerMinute(minute) {
  const m = String(minute || '').match(/^(\d+)'?(?:\+(\d+))?/)
  return m ? { base: Number(m[1]), extra: Number(m[2] || 0) } : { base: 0, extra: 0 }
}

// The real match, told the way the old predicted ticker told it: kickoff,
// every goal with the running score, cards, half-time and full-time.
function RealTicker({ events, homeTeam, awayTeam, homeScore, awayScore }) {
  if (!events || events.length === 0) return null
  let home = 0, away = 0
  const score = () => `${home}:${away}`
  const home_ = teamName(homeTeam), away_ = teamName(awayTeam)
  const halftime = () => ({ key: 'ht', minute: tr('HZ', 'HT'), type: 'halftime', head: `⏸️ ${tr('Halbzeit', 'Half time')}`,
                            text: tr(`${home_} ${score()} ${away_} zur Pause.`, `${home_} ${score()} ${away_} at the break.`), score: score() })
  const rows = [{ key: 'ko', minute: "1'", type: 'kickoff', head: `🟢 ${tr('Anpfiff', 'Kick-off')}`,
                  text: tr(`${home_} gegen ${away_} läuft.`, `${home_} vs ${away_} is under way.`), score: '0:0' }]
  let halftimeShown = false
  events.forEach((e, i) => {
    const t = tickerMinute(e.minute)
    if (!halftimeShown && t.base > 45) {
      rows.push(halftime())
      halftimeShown = true
    }
    if (e.type === 'goal') {
      if (e.team === homeTeam) home += 1; else away += 1
      const how = e.own_goal ? tr(' (Eigentor)', ' (own goal)') : e.penalty ? tr(' (Elfmeter)', ' (penalty)') : ''
      rows.push({ key: i, minute: e.minute, type: 'goal', head: tr(`⚽ TOR für ${teamName(e.team)}!`, `⚽ GOAL for ${teamName(e.team)}!`),
                  text: tr(`${e.player || 'Unbekannt'}${how} trifft zum ${score()}.`, `${e.player || 'Unknown'}${how} makes it ${score()}.`), score: score() })
    } else if (e.type === 'red_card') {
      rows.push({ key: i, minute: e.minute, type: 'chance', head: `🟥 ${tr('Rote Karte', 'Red card')} – ${teamName(e.team)}`,
                  text: tr(`${e.player || 'Ein Spieler'} fliegt vom Platz. ${teamName(e.team)} spielt zu zehnt weiter.`,
                           `${e.player || 'A player'} is sent off. ${teamName(e.team)} play on with ten men.`), score: score() })
    } else if (e.type === 'yellow_card') {
      rows.push({ key: i, minute: e.minute, type: 'yellow', head: `🟨 ${tr('Gelbe Karte', 'Yellow card')} – ${teamName(e.team)}`,
                  text: tr(`${e.player || 'Ein Spieler'} sieht Gelb.`, `${e.player || 'A player'} is booked.`), score: null })
    }
  })
  if (!halftimeShown) {
    rows.push(halftime())
  }
  const final = homeScore != null ? `${homeScore}:${awayScore}` : score()
  rows.push({ key: 'ft', minute: tr('Ende', 'FT'), type: 'fulltime', head: `🏁 ${tr('Abpfiff', 'Full time')}`, text: `${home_} ${final} ${away_}.`, score: final })

  return (
    <div className="wm-stories real-ticker">
      <h4>{tr('Liveticker', 'Live ticker')}</h4>
      {rows.map(r => (
        <div className={`wm-ticker-event wm-ticker-${r.type}`} key={r.key}>
          <span className="wm-ticker-minute">{r.minute}</span>
          <div className="wm-ticker-body">
            <div className="wm-ticker-head">
              <span>{r.head}</span>
              {r.score && <span className="wm-ticker-score">{r.score}</span>}
            </div>
            <p>{r.text}</p>
          </div>
        </div>
      ))}
    </div>
  )
}

function RealStats({ stats, homeTeam, awayTeam }) {
  if (!stats || stats.home.possession == null) return null
  return (
    <div className="h2h-stats wm-reveal">
      <h4>{tr('Spielstatistik', 'Match stats')}</h4>
      <div className="h2h-teams">
        <span><TeamLabel name={homeTeam} /></span>
        <span><TeamLabel name={awayTeam} /></span>
      </div>
      {stats.home.possession != null && (
        <HeadToHeadStat label={tr('Ballbesitz', 'Possession')} home={stats.home.possession} away={stats.away.possession} suffix="%" />
      )}
      {stats.home.shots != null && (
        <HeadToHeadStat label={tr('Schüsse', 'Shots')} home={stats.home.shots} away={stats.away.shots} />
      )}
      {stats.home.shots_on_target != null && (
        <HeadToHeadStat label={tr('Schüsse aufs Tor', 'Shots on target')} home={stats.home.shots_on_target} away={stats.away.shots_on_target} />
      )}
      {stats.home.corners != null && (
        <HeadToHeadStat label={tr('Ecken', 'Corners')} home={stats.home.corners} away={stats.away.corners} />
      )}
    </div>
  )
}

function AiComparisonPanel({ fixture, result, aiData }) {
  const sp = aiData.score_prediction || {}
  const bm = sp.betting_markets || {}
  const ou = bm.over_under || []
  const btts = bm.btts || {}
  const topScores = (sp.top_scorelines || []).slice(0, 3)

  const actualHome = result.home_score
  const actualAway = result.away_score
  const actualBtts = actualHome > 0 && actualAway > 0
  const actualTotal = actualHome + actualAway
  const actualWinner = actualHome > actualAway ? 'H' : actualAway > actualHome ? 'A' : 'D'

  const homeCorrect = actualWinner === 'H'
  const drawCorrect = actualWinner === 'D'
  const awayCorrect = actualWinner === 'A'

  return (
    <div className="ai-prediction-inner">
      <p className="wm-subtle" style={{ marginBottom: '0.9rem', fontSize: '0.75rem' }}>{tr('KI-Prognose vor dem Spiel', 'AI prediction before the match')}</p>

      {/* Winner probabilities */}
      <div className="probabilities-donut">
        <ResultDonut
          home={aiData.probability_home_win}
          draw={aiData.probability_draw}
          away={aiData.probability_away_win}
          score={`${actualHome}-${actualAway}`}
          colors={{
            home: homeCorrect ? '#22c55e' : 'var(--gold)',
            draw: drawCorrect ? '#22c55e' : '#9ca3af',
            away: awayCorrect ? '#22c55e' : '#f97316',
          }}
        />
        <div className="probabilities-legend">
          <span className="legend-title">{tr('Siegwahrscheinlichkeit', 'Win probability')}</span>
          <div className="legend-row">
            <span className={`legend-dot ${homeCorrect ? 'hit' : 'gold'}`} />
            <span className="legend-name"><TeamLabel name={aiData.home_team} />{homeCorrect ? ' ✓' : ''}</span>
            <span className="legend-value"><AnimatedNumber value={aiData.probability_home_win * 100} decimals={1} suffix="%" /></span>
          </div>
          <div className="legend-row">
            <span className={`legend-dot ${drawCorrect ? 'hit' : 'gray'}`} />
            <span className="legend-name">{tr('Remis', 'Draw')}{drawCorrect ? ' ✓' : ''}</span>
            <span className="legend-value"><AnimatedNumber value={aiData.probability_draw * 100} decimals={1} suffix="%" /></span>
          </div>
          <div className="legend-row">
            <span className={`legend-dot ${awayCorrect ? 'hit' : 'orange'}`} />
            <span className="legend-name"><TeamLabel name={aiData.away_team} />{awayCorrect ? ' ✓' : ''}</span>
            <span className="legend-value"><AnimatedNumber value={aiData.probability_away_win * 100} decimals={1} suffix="%" /></span>
          </div>
        </div>
      </div>

      {/* Top scorelines */}
      {topScores.length > 0 && (
        <div className="explanation-grid wm-grid" style={{ marginTop: '1rem' }}>
          <div className="stat-card">
            <h4>{tr('Vorhergesagte Ergebnisse', 'Predicted scores')}</h4>
            {topScores.map((s, i) => {
              const hit = s.score === `${actualHome}:${actualAway}`
              return (
                <div className="stat-row" key={i} style={hit ? { color: '#4ade80' } : {}}>
                  <span className="stat-label" style={hit ? { color: '#4ade80', fontWeight: 700 } : {}}>{s.score}{hit ? ' ✓' : ''}</span>
                  <span className="stat-val" style={hit ? { color: '#4ade80' } : {}}>{(s.probability * 100).toFixed(1)}%</span>
                </div>
              )
            })}
          </div>

          {/* BTTS + Over/Under */}
          {(btts.yes != null || ou.length > 0) && (
            <div className="stat-card">
              <h4>{tr('Märkte', 'Markets')}</h4>
              {btts.yes != null && (() => {
                const hit = actualBtts === (btts.yes >= 0.5)
                return (
                  <div className="stat-row" style={hit ? { color: '#4ade80' } : {}}>
                    <span className="stat-label" style={hit ? { color: '#4ade80', fontWeight: 700 } : {}}>{tr('Beide treffen', 'Both score')}: {actualBtts ? tr('Ja', 'Yes') : tr('Nein', 'No')}{hit ? ' ✓' : ''}</span>
                    <span className="stat-val" style={hit ? { color: '#4ade80' } : {}}>{((actualBtts ? btts.yes : btts.no) * 100).toFixed(0)}%</span>
                  </div>
                )
              })()}
              {ou.filter(o => [1.5, 2.5, 3.5].includes(parseFloat(o.line))).map(o => {
                const line = parseFloat(o.line)
                const over = actualTotal > line
                const hit = over === (o.over >= 0.5)
                return (
                  <div className="stat-row" key={o.line} style={hit ? { color: '#4ade80' } : {}}>
                    <span className="stat-label" style={hit ? { color: '#4ade80', fontWeight: 700 } : {}}>{over ? tr('Über', 'Over') : tr('Unter', 'Under')} {deNum(o.line)} {tr('Tore', 'goals')}{hit ? ' ✓' : ''}</span>
                    <span className="stat-val" style={hit ? { color: '#4ade80' } : {}}>{((over ? o.over : 1 - o.over) * 100).toFixed(0)}%</span>
                  </div>
                )
              })}
            </div>
          )}
        </div>
      )}
    </div>
  )
}

function RealResultCard({ fixture, result, aiData, onGenerate, analysisActive }) {
  const [showAI, setShowAI] = useState(false)
  const [expanded, setExpanded] = useState(false)

  if (!expanded) {
    return (
      <div className="fixture-row fixture-final" onClick={() => setExpanded(true)} role="button" tabIndex={0}>
        <div className="fixture-meta">
          <span className="fixture-date">{fixtureWhen(fixture)}</span>
          <span className="fixture-final-badge">{tr('Beendet', 'Full time')}</span>
        </div>
        <div className="fixture-teams">
          <span><TeamLabel name={fixture.home_team} /></span>
          <span className="fixture-final-score">{result.home_score} – {result.away_score}</span>
          <span><TeamLabel name={fixture.away_team} /></span>
        </div>
        <span className="fixture-expand-hint">{tr('Tippen für Details ▾', 'Tap for details ▾')}</span>
      </div>
    )
  }

  return (
    <div className="card wm-card">
      <div className="wm-card-header">
        <span className="wm-match-id">{fixtureWhen(fixture)}</span>
        <div className="wm-card-header-right">
          <span className="wm-match-type" style={{ background: 'rgba(34,197,94,0.15)', color: '#4ade80' }}>{tr('Beendet', 'Full time')}</span>
          <button className="wm-collapse-btn" onClick={() => setExpanded(false)}>{tr('Einklappen ▲', 'Collapse ▲')}</button>
        </div>
      </div>

      <div className="result-header">
        <span className="team-name"><TeamLabel name={fixture.home_team} /></span>
        <div className="prediction-badge" style={{ fontSize: '1.5rem', letterSpacing: '0.05em', padding: '0.3rem 1rem' }}>
          {result.home_score} – {result.away_score}
        </div>
        <span className="team-name"><TeamLabel name={fixture.away_team} /></span>
      </div>

      <RealStats stats={result.stats} homeTeam={fixture.home_team} awayTeam={fixture.away_team} />
      <RealTicker events={result.events} homeTeam={fixture.home_team} awayTeam={fixture.away_team}
                  homeScore={result.home_score} awayScore={result.away_score} />

      {aiData && (
        <div className="ai-prediction-section">
          <button className="ai-toggle-btn" onClick={() => setShowAI(v => !v)}>
            {showAI ? tr('▲ KI-Prognose ausblenden', '▲ Hide the AI prediction') : tr('▼ Mit der KI-Prognose vergleichen', '▼ Compare with the AI prediction')}
          </button>
          {showAI && <AiComparisonPanel fixture={fixture} result={result} aiData={aiData} />}
        </div>
      )}

      {!aiData && (
        <div style={{ marginTop: '1rem' }}>
          {analysisActive
            ? <p className="wm-subtle">{tr('KI-Analyse wird geladen…', 'Loading the AI analysis…')}</p>
            : <button className="fixture-generate-btn" onClick={onGenerate}>{tr('KI-Analyse vor dem Spiel zeigen', 'Show the AI analysis before the match')}</button>
          }
        </div>
      )}
    </div>
  )
}

export default function App() {
  const [page, setPage] = useState('home')
  // The page's language; LANG (module level) is what tr() reads, this state
  // only makes React redraw everything when it changes.
  const [lang, setLang] = useState(LANG)
  function switchLang(next) {
    LANG = next
    try { localStorage.setItem('goaliq-lang', next) } catch { /* private mode */ }
    document.documentElement.lang = next
    document.title = tr('GoalIQ – KI-Prognosen für jedes Spiel', 'GoalIQ – AI predictions for every match')
    setLang(next)
  }
  useEffect(() => {
    document.documentElement.lang = LANG
    document.title = tr('GoalIQ – KI-Prognosen für jedes Spiel', 'GoalIQ – AI predictions for every match')
  }, [])
  const [predictionsById, setPredictionsById] = useState({})
  // The landing page's counted numbers (GET /site-stats).
  const [siteStats, setSiteStats] = useState(null)
  const [realResultsMap, setRealResultsMap] = useState({})
  const [realResults, setRealResults] = useState([])
  // null until someone picks a competition: the ticker then shows a mix.
  const [tickerCompetition, setTickerCompetition] = useState(null)
  const [wmLoading, setWmLoading] = useState(true)
  const [activeCompetition, setActiveCompetition] = useState('cl')
  const [activeGroup, setActiveGroup] = useState('next')
  const [, setFixturesVersion] = useState(0)
  const [analysisStep, setAnalysisStep] = useState({})
  const [combo, setCombo] = useState(null)
  const [comboLoading, setComboLoading] = useState(false)

  const competition = COMPETITIONS[activeCompetition]
  const currentFixtures = competition.fixtures
  const currentGroups = competition.groups
  const nextGames = nextGamesFor(currentFixtures)

  // Anything already loaded belongs to the competition being left, so it is
  // dropped rather than shown under the new one.
  function switchCompetition(key) {
    setActiveCompetition(key)
    setTickerCompetition(key)
    setActiveGroup('next')
    setCombo(null)
    setComboLoading(false)
  }

  // Opens a competition at its next matchday and scrolls to it (the hero
  // button: Champions League, the landing card: Bundesliga).
  function openNextMatchday(key) {
    switchCompetition(key)
    const now = new Date()
    const fixtures = COMPETITIONS[key].fixtures
    const next = COMPETITIONS[key].groups.find(g =>
      fixtures.some(f => f.group === g && fixtureDateTime(f) >= now))
    setActiveGroup(next || 'next')
    setTimeout(() => document.getElementById('predictions')?.scrollIntoView({ behavior: 'smooth', block: 'start' }), 80)
  }
  const openNextChampionsLeague = () => openNextMatchday('cl')

  async function loadCombo() {
    setComboLoading(true)
    setCombo(null)
    try {
      const r = await axios.get(`${API_BASE}/combo-ticket`,
                                { params: { competition: competition.sportKey } })
      setCombo(r.data)
    } catch {
      setCombo({ error: true })
    } finally {
      setComboLoading(false)
    }
  }

  function startAnalysis(matchId, fixture) {
    setAnalysisStep(prev => ({ ...prev, [matchId]: 0 }))
    let step = 0
    const interval = setInterval(() => {
      step += 1
      if (step >= ANALYZING_STEPS.length) {
        clearInterval(interval)
        setAnalysisStep(prev => ({ ...prev, [matchId]: Infinity }))
        // Quietly fetch the odds/agent data in the background once the reveal
        // animation finishes, so the "External Factors" section (and later
        // the Smart Bet check) has data ready without an extra wait - this is
        // the same call startBetCheck makes, just not tied to that button.
        if (fixture) preloadBetInfo(matchId, fixture)
      } else {
        setAnalysisStep(prev => ({ ...prev, [matchId]: step }))
      }
    }, 800)
  }

  function preloadBetInfo(matchId, fixture) {
    setBetInfoById(prev => {
      if (prev[matchId] !== undefined) return prev
      axios.get(`${API_BASE}/value-bets`, { params: { home_team: fixture.home_team, away_team: fixture.away_team } })
        .then(r => setBetInfoById(p => ({ ...p, [matchId]: r.data })))
        .catch(() => setBetInfoById(p => ({ ...p, [matchId]: { odds_found: false, bets: [] } })))
      return { ...prev, [matchId]: null }  // null = fetch in flight, distinct from "not started"
    })
  }

  function collapseAnalysis(matchId) {
    setAnalysisStep(prev => {
      const next = { ...prev }
      delete next[matchId]
      return next
    })
  }

  const [betStepById, setBetStepById] = useState({})
  const [betInfoById, setBetInfoById] = useState({})

  // A combo leg names the match as the odds feed spells it; the fixture list
  // may spell it differently ("Bosnia & Herzegovina"), so names are compared
  // loosely and the kickoff date settles a doubt.
  function findFixture(leg) {
    const simple = name => String(name || '').normalize('NFD').replace(/[\u0300-\u036f]/g, '')
      .toLowerCase().replace(/\band\b|&/g, ' ').replace(/[^a-z]/g, '')
    const words = name => new Set(String(name || '').toLowerCase().split(/[^a-zà-ž]+/).filter(w => w.length > 2))
    const overlap = (a, b) => [...words(a)].some(w => words(b).has(w))
    const date = leg.commence_time ? berlinDate(leg.commence_time) : null
    const keys = Object.keys(COMPETITIONS)
    const ordered = [...keys.filter(k => COMPETITIONS[k].sportKey === leg.sport_key), ...keys.filter(k => COMPETITIONS[k].sportKey !== leg.sport_key)]
    for (const key of ordered) {
      const fixtures = COMPETITIONS[key].fixtures
      const exact = fixtures.find(f => simple(f.home_team) === simple(leg.home_team) && simple(f.away_team) === simple(leg.away_team)
        && (!date || f.date === date))
      const loose = exact || fixtures.find(f => f.date === date && overlap(f.home_team, leg.home_team) && overlap(f.away_team, leg.away_team))
      if (loose) return [key, loose]
    }
    return [null, null]
  }

  // From a combo leg straight to that match: analysis open and bet tips
  // loaded at once, no reveal animation.
  function openLeg(leg) {
    const [key, fixture] = findFixture(leg)
    if (!fixture) return
    const id = fixture.match_id
    setActiveCompetition(key)
    setActiveGroup(fixture.group)
    setAnalysisStep(prev => ({ ...prev, [id]: Infinity }))
    setBetStepById(prev => ({ ...prev, [id]: Infinity }))
    axios.get(`${API_BASE}/value-bets`, { params: { home_team: fixture.home_team, away_team: fixture.away_team } })
      .then(r => setBetInfoById(prev => ({ ...prev, [id]: r.data })))
      .catch(() => setBetInfoById(prev => ({ ...prev, [id]: { odds_found: false, bets: [] } })))
    setTimeout(() => document.getElementById(`match-${id}`)?.scrollIntoView({ block: 'start', behavior: 'smooth' }), 150)
  }

  // Straight to the bet tips from the fixture list: the analysis opens
  // without its step-by-step reveal and the page jumps to the tips.
  function openBets(fixture) {
    const id = fixture.match_id
    setAnalysisStep(prev => ({ ...prev, [id]: Infinity }))
    setBetStepById(prev => ({ ...prev, [id]: Infinity }))
    axios.get(`${API_BASE}/value-bets`, { params: { home_team: fixture.home_team, away_team: fixture.away_team } })
      .then(r => setBetInfoById(prev => ({ ...prev, [id]: r.data })))
      .catch(() => setBetInfoById(prev => ({ ...prev, [id]: { odds_found: false, bets: [] } })))
    setTimeout(() => (document.getElementById(`bets-${id}`) || document.getElementById(`match-${id}`))
      ?.scrollIntoView({ block: 'start', behavior: 'smooth' }), 150)
  }

  function startBetCheck(matchId, fixture) {
    setBetStepById(prev => ({ ...prev, [matchId]: 0 }))
    axios.get(`${API_BASE}/value-bets`, { params: { home_team: fixture.home_team, away_team: fixture.away_team } })
      .then(r => setBetInfoById(prev => ({ ...prev, [matchId]: r.data })))
      .catch(() => setBetInfoById(prev => ({ ...prev, [matchId]: { odds_found: false, bets: [] } })))

    let step = 0
    const interval = setInterval(() => {
      step += 1
      if (step >= BET_STEPS.length) {
        clearInterval(interval)
        setBetStepById(prev => ({ ...prev, [matchId]: Infinity }))
      } else {
        setBetStepById(prev => ({ ...prev, [matchId]: step }))
      }
    }, 700)
  }

  // From the Best Bets tab: jump straight to a match's Smart Bet view.
  useEffect(() => {
    async function loadAll() {
      try {
        try {
          const served = await axios.get(`${API_BASE}/fixtures`)
          applyServerFixtures(served.data)
          setFixturesVersion(v => v + 1)
        } catch (e) {
          // keep the bundled fixtures
        }
        axios.get(`${API_BASE}/site-stats`).then(r => setSiteStats(r.data)).catch(() => {})
        axios.get(`${API_BASE}/model-track-record`)
          .then(r => { MODEL_TRACK_RECORD = r.data; setFixturesVersion(v => v + 1) })
          .catch(() => {})
        const [listResp, resultsResp] = await Promise.allSettled([
          axios.get(`${API_BASE}/predictions`),
          axios.get(`${API_BASE}/real-results`),
        ])
        if (listResp.status === 'fulfilled') {
          const ids = (listResp.value.data.match_ids || []).filter(id =>
            Object.values(COMPETITIONS).some(c => c.fixtures.some(f => f.match_id === id))
          )
          const all = await Promise.all(
            ids.map(id => axios.get(`${API_BASE}/predictions/${id}`).then(r => ({ matchId: id, data: r.data })))
          )
          const byId = {}
          all.forEach(({ matchId, data }) => { byId[matchId] = data })
          setPredictionsById(byId)
        }
        if (resultsResp.status === 'fulfilled') {
          const results = resultsResp.value.data.results || []
          setRealResultsMap(buildRealResultsMap(results))
          setRealResults(results)
        }
      } catch (e) {
        // non-fatal
      } finally {
        setWmLoading(false)
      }
    }
    loadAll()
  }, [])

  return (
    <div className="app">
      <nav className="navbar">
        <a className="nav-brand" href="/" aria-label={tr('GoalIQ Startseite', 'GoalIQ home')}>
          <img className="nav-logo" src="/favicon.svg" alt="" />
          <span className="nav-title">Goal<span>IQ</span></span>
        </a>
        <div className="nav-links">
          <a href="#predictions" onClick={() => setPage('home')}>{tr('Prognosen', 'Predictions')}</a>
          <a href="#how-it-works" onClick={(e) => { e.preventDefault(); setPage('how-it-works') }}>{tr("So funktioniert's", 'How it works')}</a>
        </div>
        <div className="lang-switch" role="group" aria-label={tr('Sprache', 'Language')}>
          <button className={lang === 'de' ? 'active' : ''} onClick={() => switchLang('de')} aria-pressed={lang === 'de'}>DE</button>
          <button className={lang === 'en' ? 'active' : ''} onClick={() => switchLang('en')} aria-pressed={lang === 'en'}>EN</button>
        </div>
      </nav>

      {page === 'home' && <MatchTicker results={realResults} competitionKey={tickerCompetition} />}

      {page === 'home' && (
        <>
          <header className="hero">
            <HeroVisual />
            <div className="hero-grid">
              <div className="hero-content">
                <h1>{tr('KI-Prognosen für jedes Spiel', 'AI predictions for every match')}</h1>
                <p>
                  {tr('Ein KI-Modell, trainiert auf tausenden Spielen, rechnet jede Partie durch: Siegchancen, wahrscheinlichstes Ergebnis und Spielverlauf. Nach dem Abpfiff zeigen wir ehrlich, ob die KI richtig lag.',
                      'An AI model trained on thousands of matches works through every game: win chances, most likely score and game flow. After the final whistle we show honestly whether the AI got it right.')}
                </p>
                <button className="competition-badge hero-cta" onClick={openNextChampionsLeague}>
                  <img src="https://a.espncdn.com/i/leaguelogos/soccer/500-dark/2.png" alt="" className="competition-badge-logo" />
                  <span><span className="hero-cta-new">{tr('Neu', 'New')}</span> <strong>Champions League</strong> – {tr('jetzt Prognosen ansehen', 'see the predictions')}</span>
                  <span className="hero-cta-arrow">→</span>
                </button>
                <div className="hero-stats">
                  <div className="hero-stat">
                    <span className="hero-stat-value">
                      {`${Math.floor((siteStats?.training_matches || 44000) / 1000)}${tr('.000+', ',000+')}`}
                    </span>
                    <span className="hero-stat-label">{tr('Spiele im Training', 'Matches in training')}</span>
                  </div>
                  <div className="hero-stat">
                    <span className="hero-stat-value">3</span>
                    <span className="hero-stat-label">{tr('Wettbewerbe', 'Competitions')}</span>
                  </div>
                  <div className="hero-stat">
                    <span className="hero-stat-value">30+</span>
                    <span className="hero-stat-label">{tr('Wetten pro Spiel geprüft', 'Bets checked per match')}</span>
                  </div>
                  <div className="hero-stat">
                    <span className="hero-stat-value">{siteStats?.settled_matches ?? '–'}</span>
                    <span className="hero-stat-label">{tr('Spiele getrackt', 'Matches tracked')}</span>
                  </div>
                </div>
              </div>
              <HeroPreviewCard onOpen={() => openNextMatchday('bl')} />
            </div>
          </header>

          <main className="main">
            <section id="predictions" className="wm-section">
              <h2 className="section-title">{tr('Prognosen', 'Predictions')}</h2>

              <div className="competition-select">
                {Object.entries(COMPETITIONS).map(([key, c]) => (
                  <button
                    key={key}
                    className={`competition-pill ${activeCompetition === key ? 'active' : ''}`}
                    onClick={() => switchCompetition(key)}
                  >
                    {c.logo
                      ? <img src={c.logo} alt="" />
                      : <span className="competition-pill-emoji">{c.emoji}</span>}
                    {c.label}
                  </button>
                ))}
                <button className="competition-pill soon" disabled title={tr('Bald verfügbar', 'Coming soon')}>
                  <span className="competition-pill-emoji">🏴󠁧󠁢󠁥󠁮󠁧󠁿</span>
                  Premier League
                  <span className="competition-pill-soon">{tr('Bald', 'Soon')}</span>
                </button>
                <button className="competition-pill soon" disabled title={tr('Bald verfügbar', 'Coming soon')}>
                  <span className="competition-pill-emoji">🇪🇸</span>
                  La Liga
                  <span className="competition-pill-soon">{tr('Bald', 'Soon')}</span>
                </button>
              </div>

              <div className="group-nav">
                <div className="group-segments" role="tablist">
                  <button role="tab" aria-selected={activeGroup === 'next'}
                          className={`group-segment ${activeGroup === 'next' ? 'active' : ''}`}
                          onClick={() => setActiveGroup('next')}>📅 {tr('Nächste Spiele', 'Next games')}</button>
                  <button role="tab" aria-selected={activeGroup === 'hot'}
                          className={`group-segment ${activeGroup === 'hot' ? 'active' : ''}`}
                          onClick={() => setActiveGroup('hot')}>🔥 {tr('Topspiele', 'Top games')}</button>
                  <button role="tab" aria-selected={activeGroup === 'combo'}
                          className={`group-segment ${activeGroup === 'combo' ? 'active' : ''}`}
                          onClick={() => { setActiveGroup('combo'); if (combo === null && !comboLoading) loadCombo() }}>
                    🎟️ {tr('Kombi-Schein', 'Combo ticket')}</button>
                </div>
                {currentGroups.length > 0 && (
                  <label className={`group-select ${currentGroups.includes(activeGroup) ? 'active' : ''}`}>
                    <span className="group-select-icon">📆</span>
                    <select value={currentGroups.includes(activeGroup) ? activeGroup : ''}
                            onChange={e => e.target.value && setActiveGroup(e.target.value)}
                            aria-label={tr('Spieltag wählen', 'Choose matchday')}>
                      <option value="" disabled>{tr('Spieltag wählen', 'Choose matchday')}</option>
                      {currentGroups.map(g => <option key={g} value={g}>{groupLabel(g)}</option>)}
                    </select>
                    <span className="group-select-caret">▾</span>
                  </label>
                )}
              </div>

              {wmLoading && (
                <div className="analyzing-status loading-inline">
                  <span className="analyzing-spinner" />
                  <span>{tr('Analysen werden geladen…', 'Loading analyses…')}</span>
                </div>
              )}

              {activeGroup === 'combo' && (
                <ComboTicketView combo={combo} loading={comboLoading} onOpenLeg={openLeg} />
              )}

              {activeGroup === 'next' && nextGames.length === 0 && (
                <p className="wm-subtle">{tr('Heute stehen keine Spiele an.', 'No games today.')}</p>
              )}

              {activeGroup === 'hot' && nextGames.length === 0 && (
                <p className="wm-subtle">{tr('Heute stehen keine Spiele an.', 'No games today.')}</p>
              )}


              <div className="fixtures-list">
                {(() => {
                  let fixtures
                  if (activeGroup === 'next') {
                    fixtures = nextGames
                  } else if (activeGroup === 'hot') {
                    fixtures = getHotFixtures(predictionsById, nextGames)
                  } else {
                    fixtures = currentFixtures.filter(f => f.group === activeGroup)
                  }
                  return fixtures.map(fixture => {
                    const realKey = `${fixture.home_team}__${fixture.away_team}__${fixture.date}`
                    const realResult = realResultsMap[realKey]
                    // Too far ahead: an older cached forecast would not know
                    // the matches still to come, so none is shown yet.
                    const aiData = new Date() >= predictionOpensAt(fixture)
                      ? predictionsById[fixture.match_id] : undefined

                    if (realResult?.completed) {
                      return (
                        <RealResultCard
                          key={fixture.match_id}
                          fixture={fixture}
                          result={realResult}
                          aiData={aiData}
                          onGenerate={() => startAnalysis(fixture.match_id)}
                          analysisActive={analysisStep[fixture.match_id] !== undefined}
                        />
                      )
                    }

                    if (!aiData) {
                      return <FixtureRow key={fixture.match_id} fixture={fixture} />
                    }
                    const step = analysisStep[fixture.match_id]
                    if (step === undefined) {
                      return (
                        <FixtureReadyRow
                          key={fixture.match_id}
                          fixture={fixture}
                          onGenerate={() => startAnalysis(fixture.match_id, fixture)}
                          onBets={() => openBets(fixture)}
                        />
                      )
                    }
                    return (
                      <WmPredictionCard
                        key={fixture.match_id}
                        matchId={fixture.match_id}
                        data={aiData}
                        fixture={fixture}
                        revealStep={step}
                        onCollapse={step === Infinity ? () => collapseAnalysis(fixture.match_id) : undefined}
                        betStep={betStepById[fixture.match_id]}
                        betInfo={betInfoById[fixture.match_id]}
                        onStartBetCheck={() => startBetCheck(fixture.match_id, fixture)}
                      />
                    )
                  })
                })()}
              </div>
            </section>
          </main>
        </>
      )}

      {page === 'how-it-works' && (
        <main className="main flow-main">
          <AnalysisFlowPage onBack={() => setPage('home')} />
        </main>
      )}

      <footer className="footer">
        <p>GoalIQ – {tr('KI-Prognosen, nur zur Unterhaltung. Keine Wettberatung.', 'AI predictions, for entertainment only. Not betting advice.')} · <a href="mailto:kontakt@goaliq.de">kontakt@goaliq.de</a></p>
      </footer>
    </div>
  )
}
