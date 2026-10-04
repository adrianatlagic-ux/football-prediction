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

// Teams keep their English key everywhere (fixtures, odds, colours); only
// the name a visitor reads is German.
const teamName = name => TEAM_NAMES_DE[name] || name
// 1.79 -> "1,79"
const deNum = v => String(v ?? '').replace('.', ',')

// "Do, 01.10. · 20:45"
function fixtureWhen(f) {
  const d = new Date(`${f.date}T12:00:00`)
  const weekday = d.toLocaleDateString('de-DE', { weekday: 'short' }).replace('.', '')
  return `${weekday} ${f.date.slice(8, 10)}.${f.date.slice(5, 7)}. · ${f.time}`
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
        sportKey: 'soccer_uefa_nations_league', emoji: '\u{1F3C6}' },
}

// Fixtures come from the server (GET /fixtures, rebuilt daily from ESPN), so
// a new matchday appears without a redeploy; the bundled files above are only
// the fallback. The whole season is listed, but a prediction is shown from
// PREDICTION_LEAD_HOURS before kickoff - the window the daily job predicts in
// with every result up to then. Tabs cover the matchdays around today.
const PREDICTION_LEAD_HOURS = 48
const TAB_PAST_DAYS = 14
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
  // The last matchday already played always stays, for its results - in the
  // Champions League that can be four weeks back.
  const lastPlayed = [...ordered].reverse().find(([, g]) => g.last < now)
  if (lastPlayed) kept.add(lastPlayed[0])
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
function getHotFixture(predictionsById, fixtures) {
  let best = null
  let bestScore = -Infinity
  for (const fixture of fixtures) {
    const data = predictionsById[fixture.match_id]
    const score = data ? excitementScore(data) : -1
    if (score > bestScore) {
      bestScore = score
      best = fixture
    }
  }
  return best
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

  return <>{display.toFixed(decimals).replace('.', ',')}{suffix}</>
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
        {animate ? <AnimatedNumber value={value * 100} decimals={1} suffix="%" /> : `${(value * 100).toFixed(1).replace('.', ',')}%`}
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
  const terms = [teamName(home), teamName(away), '2+ Toren', '3+ Toren', 'torreichen Spiel', 'torarmen Spiel']
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
    ? <><TeamLabel name={team} />: <strong>{Math.round(info.share * 100)}%</strong> der stärkstmöglichen Aufstellung (Bank nach Spielzeit gewichtet)</>
    : <><TeamLabel name={team} />: Aufstellung nicht bewertet</>
  const moved = k => `${Math.round(before[k] * 100)}% → ${Math.round(data[k] * 100)}%`
  return (
    <div className="lineup-box">
      <h4>Aufstellungen</h4>
      <p>{side(l.home, data.home_team)}</p>
      <p>{side(l.away, data.away_team)}</p>
      <p className="lineup-effect">
        Siegchancen angepasst: {teamName(data.home_team)} {moved('probability_home_win')}, Remis {moved('probability_draw')},
        {' '}{teamName(data.away_team)} {moved('probability_away_win')}.
      </p>
    </div>
  )
}

function FormRating({ data }) {
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
  const tug = (end) => ({ '--tug-meet': `${meet}%`, '--tug-end': `${end}%`, width: `${end}%` })

  return (
    <div className="form-rating-box form-rating-top">
      <h4>Formkurve <span className="wm-subtle">· letzte 10 Spiele</span></h4>

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
          <div className="form-tug-fill-home tug-animate" style={tug(homePct)} />
          <div className="form-tug-fill-away tug-animate" style={tug(awayPct)} />
        </div>
        <div className="form-tug-values">
          <span className="form-tug-value home">{homeRating}</span>
          <span className="form-tug-value away">{awayRating}</span>
        </div>
      </div>

      <p className="form-rating-detail">
        <strong><TeamLabel name={home} /></strong> — {deNum(explanation.form_last_10_avg_pts[home])} Pkt./Spiel &middot; {deNum(explanation.avg_goals_scored[home])} Tore &middot; {deNum(explanation.avg_goals_conceded[home])} Gegentore &middot; {explanation.clean_sheet_rate[home]} zu null
      </p>
      <p className="form-rating-detail">
        <strong><TeamLabel name={away} /></strong> — {deNum(explanation.form_last_10_avg_pts[away])} Pkt./Spiel &middot; {deNum(explanation.avg_goals_scored[away])} Tore &middot; {deNum(explanation.avg_goals_conceded[away])} Gegentore &middot; {explanation.clean_sheet_rate[away]} zu null
      </p>
    </div>
  )
}

function MatchScenario({ data }) {
  const bm = (data.score_prediction || {}).betting_markets
  if (!bm) return null
  const home = data.home_team
  const away = data.away_team
  return (
    <div className="betting-markets">
      <div className="scenario-box">
        <h4>Wahrscheinlichstes Szenario</h4>
        <p>{renderScenario(bm.scenario, home, away)}</p>
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
            <h4>Doppelte Chance</h4>
            <div className="market-grid">
              <div className={`market-card market-card-fillable${dc.home_or_draw === dcMax ? ' is-leader' : ''}`}>
                <AnimatedBarFill className="market-card-fill" targetPct={dc.home_or_draw * 100} />
                <div className="market-card-content">
                  <div className="market-card-label"><TeamLabel name={home} /> oder Remis</div>
                  <div className="market-card-value"><AnimatedNumber value={dc.home_or_draw * 100} decimals={1} suffix="%" /></div>
                </div>
              </div>
              <div className={`market-card market-card-fillable${dc.home_or_away === dcMax ? ' is-leader' : ''}`}>
                <AnimatedBarFill className="market-card-fill" targetPct={dc.home_or_away * 100} />
                <div className="market-card-content">
                  <div className="market-card-label"><TeamLabel name={home} /> oder <TeamLabel name={away} /></div>
                  <div className="market-card-value"><AnimatedNumber value={dc.home_or_away * 100} decimals={1} suffix="%" /></div>
                </div>
              </div>
              <div className={`market-card market-card-fillable${dc.draw_or_away === dcMax ? ' is-leader' : ''}`}>
                <AnimatedBarFill className="market-card-fill" targetPct={dc.draw_or_away * 100} />
                <div className="market-card-content">
                  <div className="market-card-label">Remis oder <TeamLabel name={away} /></div>
                  <div className="market-card-value"><AnimatedNumber value={dc.draw_or_away * 100} decimals={1} suffix="%" /></div>
                </div>
              </div>
            </div>
          </div>
        )
      })()}

      <div>
        <h4>Tore gesamt (Über / Unter)</h4>
        {ou.map(o => (
          <div className="over-under-row" key={o.line}>
            <span className="over-under-line">{deNum(o.line)}</span>
            <div className="over-under-track">
              <AnimatedBarFill className="over-under-fill" targetPct={o.over * 100} />
            </div>
            <span className="over-under-value">über <AnimatedNumber value={o.over * 100} decimals={1} suffix="%" /></span>
          </div>
        ))}
      </div>

      <div className="market-card btts-card">
        <div className="market-card-label">Beide Teams treffen</div>
        <div className="btts-split">
          <div className="btts-half">
            <div className="market-card-value"><AnimatedNumber value={btts.yes * 100} decimals={1} suffix="%" /></div>
            <div className="market-card-sub">Ja</div>
          </div>
          <div className="btts-half">
            <div className="market-card-value"><AnimatedNumber value={btts.no * 100} decimals={1} suffix="%" /></div>
            <div className="market-card-sub">Nein</div>
          </div>
        </div>
      </div>

      <div>
        <h4>Wenn <TeamLabel name={favorite} /> gewinnt (<AnimatedNumber value={margin1 * 100} decimals={1} suffix="%" />) – wie hoch?</h4>
        <div className="market-grid">
          <div className="market-card">
            <div className="market-card-label">1+ Tor</div>
            <div className="market-card-value"><AnimatedNumber value={margin1 * 100} decimals={1} suffix="%" /></div>
          </div>
          <div className="market-card">
            <div className="market-card-label">2+ Tore</div>
            <div className="market-card-value"><AnimatedNumber value={margin2 * 100} decimals={1} suffix="%" /></div>
          </div>
          <div className="market-card">
            <div className="market-card-label">3+ Tore</div>
            <div className="market-card-value"><AnimatedNumber value={margin3 * 100} decimals={1} suffix="%" /></div>
          </div>
        </div>
      </div>
    </div>
  )
}

function betPercent(value, signed = false) {
  return Number.isFinite(value) ? `${signed && value > 0 ? '+' : ''}${(value * 100).toFixed(1).replace('.', ',')}%` : '—'
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
         title={onOpenLeg ? 'Dieses Spiel mit der Wette öffnen' : undefined}>
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
          {leg.policy === 'agree' && <span className="smart-bet-agree-chip yes">◆ Modell stimmt zu ✓</span>}
          {leg.ki_agrees && <span className="smart-bet-agree-chip yes">✨ KI stimmt zu ✓</span>}
          {leg.is_likely && <span className="smart-bet-agree-chip yes">🎯 Wahrscheinlichster Tipp</span>}
          {leg.likely_pick && (
            <span className="smart-bet-agree-chip muted"
                  title={`🎯 dieses Spiels: ${plainBetPhrase(leg.likely_pick)} zu ${leg.likely_pick.best_odds?.toFixed(2)}`}>
              🎯 Nicht der wahrscheinlichste
            </span>
          )}
        </div>
      </div>
      <div className="combo-leg-numbers">
        <span className="combo-leg-odds">{leg.best_odds.toFixed(2)}</span>
        <span className="combo-leg-prob">{betPercent(leg.probability)} Modell</span>
      </div>
    </div>
  )
}

function ComboTicketCard({ ticket, primary, onOpenLeg }) {
  return (
    <div className={`combo-ticket ${primary ? 'is-primary' : ''}`}>
      <div className="combo-ticket-head">
        <span className="combo-ticket-legs">{ticket.leg_count}er-Kombi · {ticket.bookmaker}</span>
        <div className="combo-quote">
          <span className="combo-quote-label">Geschätzte Gesamtquote</span>
          <span className="combo-ticket-odds">{ticket.combined_odds.toFixed(2)}</span>
        </div>
      </div>
      <div className="combo-legs">
        {ticket.legs.map((leg, i) => <ComboLegRow key={i} leg={leg} index={i} onOpenLeg={onOpenLeg} />)}
      </div>
      <dl className="bet-metrics probability-metrics">
        <BetMetric label="Chance, dass alle treffen" value={betPercent(ticket.conservative_probability)}
                   detail="Nach Marktpreisen, ohne Marge" emphasis />
        <BetMetric label="Unser Modell allein" value={betPercent(ticket.probability)} detail="Vor dem Abgleich mit dem Preis" />
      </dl>
      <dl className="bet-metrics decision-metrics">
        <BetMetric label="Gewinn pro 1 € Einsatz" value={ticket.returns_per_unit.toFixed(2)} detail="Wenn jeder Tipp trifft" />
      </dl>
      {primary && (
        <p className="combo-ticket-note">
          Die Wahrscheinlichkeiten nehmen an, dass die Ergebnisse unabhängig voneinander sind. Die Quoten
          stammen aus den Einzelmärkten von {ticket.bookmaker}; das Kombi-Angebot selbst wurde nicht
          geprüft. Wir erwarten mit dieser Wette keinen Gewinn – es ist nur der wahrscheinlichste Schein,
          der den Einsatz mindestens verdoppelt.
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
        <span className="combo-ticket-legs">💰 {ticket.leg_count}er-Kombi · bet-at-home</span>
        <div className="combo-quote">
          <span className="combo-quote-label">Gesamtquote</span>
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
              <div className="combo-leg-meta">{marketGroupLabel(leg.market)} · fair {leg.fair_odds.toFixed(2)} · Vorteil {(leg.edge * 100).toFixed(1)}%</div>
            </div>
            <div className="combo-leg-numbers">
              <span className="combo-leg-odds">{leg.book_odds.toFixed(2)}</span>
              <span className="combo-leg-prob">{betPercent(leg.probability)} Pinnacle</span>
            </div>
          </div>
        ))}
      </div>
      <dl className="bet-metrics probability-metrics">
        <BetMetric label="Chance, dass alle treffen" value={betPercent(ticket.probability)} detail="Nach Pinnacles fairen Preisen" emphasis />
        <BetMetric label="Vorteil" value={`${ticket.edge >= 0 ? '+' : ''}${(ticket.edge * 100).toFixed(1)}%`} detail="Pro 1 € Einsatz, im Schnitt über viele Scheine" />
      </dl>
      <p className="combo-ticket-note">
        Nur Preis-Tipps, alle in der Stunde vor Anpfiff gelesen. Ergebnisse gelten als unabhängig;
        das Kombi-Angebot bei bet-at-home wurde nicht geprüft. Ein Vorteil ist ein Durchschnitt, kein Versprechen für diesen Schein.
      </p>
    </div>
  )
}

function ComboTicketView({ combo, loading, onOpenLeg }) {
  if (loading) {
    return (
      <div className="analyzing-status loading-inline">
        <span className="analyzing-spinner" />
        <span>Kombinationen werden gebaut…</span>
      </div>
    )
  }
  if (!combo) return null
  if (combo.error) {
    return <p className="wm-subtle">Kombi-Vorschlag gerade nicht verfügbar (keine aktuellen Quoten).</p>
  }

  return (
    <div className="combo-view">
      {combo.price_tip_combos?.length > 0 && (
        <div className="combo-day">
          <span className="combo-section-label">💰 Preis-Tipp-Kombi</span>
          {combo.price_tip_combos.map(t => <PriceTipComboCard key={t.date} ticket={t} onOpenLeg={onOpenLeg} />)}
        </div>
      )}

      <p className="best-bets-intro">
        Jeder Tipp muss treffen. Alle Quoten sind von <strong>bet-at-home</strong>; jeder Schein nutzt <strong>einen Spieltag</strong>
        {' '}und höchstens einen Tipp pro Spiel. Genommen werden nur Tipps, denen <strong>unser Modell zustimmt</strong>;
        {' '}Tipps, die auch die <strong>KI</strong> nach ihrer Recherche stützt, kommen zuerst. Ein Schein zahlt mindestens
        {' '}<strong>{(combo.min_combined_odds || 3).toFixed(2).replace('.', ',')}</strong>. Vergleiche die besten 2er-, 3er- und 4er-Kombis pro Tag.
      </p>

      {!combo.recommended && (
        <p className="smart-bet-notip">
          <strong>Heute kein Kombi-Schein.</strong><br />
          {combo.reason}
        </p>
      )}

      {combo.days?.map(day => (
        <div className="combo-day" key={day.date}>
          <span className="combo-section-label">
            {new Date(day.date + 'T12:00:00').toLocaleDateString('de-DE', { weekday: 'long', day: 'numeric', month: 'short' })}
            {' · '}{day.eligible_legs} {day.eligible_legs === 1 ? 'passendes Spiel' : 'passende Spiele'}
          </span>

          <div className="combo-size-grid">
            {(day.by_size || []).map(option => (
              <section className="combo-size-option" key={option.leg_count}
                       aria-label={`${option.leg_count}er-Kombi`}>
                <h3 className="combo-size-title">{option.leg_count}er-Kombi</h3>
                {option.ticket ? (
                  <>
                    <ComboTicketCard ticket={option.ticket} onOpenLeg={onOpenLeg} />
                    {option.near_miss && (
                      <details className="combo-near-miss">
                        <summary>
                          Wahrscheinlicher, knapp unter {(combo.min_combined_odds || 2).toFixed(2).replace('.', ',')}: {betPercent(option.near_miss.conservative_probability)} zu
                          {' '}{option.near_miss.combined_odds.toFixed(2)}
                          {' '}(statt {betPercent(option.ticket.conservative_probability)} zu {option.ticket.combined_odds.toFixed(2)})
                        </summary>
                        <ComboTicketCard ticket={option.near_miss} onOpenLeg={onOpenLeg} />
                      </details>
                    )}
                  </>
                ) : (
                  <div className="combo-size-empty">
                    <strong>Nicht verfügbar</strong>
                    <p>{option.reason}</p>
                  </div>
                )}
              </section>
            ))}
          </div>
        </div>
      ))}

      <p className="smart-bet-finePrint">
        Unter den Scheinen mit den meisten KI-gestützten Tipps gewinnt der laut Markt wahrscheinlichste.
        Die Wahrscheinlichkeiten nehmen unabhängige Ergebnisse an; die Gesamtquoten sind aus Einzelquoten
        berechnet und nicht als Buchmacher-Schein geprüft. Eine höhere geschätzte Trefferquote
        heißt nicht, dass sich die Wette lohnt.
        Scheine können sich überschneiden und sind keine unabhängigen Wetten.
      </p>
    </div>
  )
}

function FixtureRow({ fixture }) {
  const opens = predictionOpensAt(fixture)
  const label = opens > new Date()
    ? `Analyse ab ${opens.toLocaleDateString('de-DE', { weekday: 'short', day: 'numeric', month: 'short' })}`
    : 'Analyse folgt'
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
        <span className="fixture-ready-badge">Analyse bereit</span>
      </div>
      <div className="fixture-teams">
        <span><TeamLabel name={fixture.home_team} /></span>
        <span className="fixture-vs">vs</span>
        <span><TeamLabel name={fixture.away_team} /></span>
      </div>
      <button className="fixture-generate-btn" onClick={onGenerate}>
        KI-Analyse starten
      </button>
      {onBets && (
        <button className="fixture-generate-btn fixture-bets-btn" onClick={onBets}>
          Wett-Tipps zeigen
        </button>
      )}
    </div>
  )
}

const ANALYZING_STEPS = [
  'Aktuelle Spieldaten werden gelesen…',
  'Stärke, Form & direkte Duelle werden analysiert…',
  'Sieg-, Remis- und Niederlagen-Chancen werden berechnet…',
  'Märkte & Quoten werden berechnet…',
  'Wahrscheinlichste Ergebnisse werden ermittelt…',
  'Spielverlauf wird erstellt…',
]

const BET_STEPS = [
  'Aktuelle Quoten werden geladen…',
  'Abgleich mit den Modell-Wahrscheinlichkeiten…',
  'Erwartungswert wird berechnet…',
  'Beste Wette wird gesucht…',
]

function betOutcomeLabel(b) {
  if (b.market === 'Handicap +0.5') return <><TeamLabel name={b.team} /> oder Remis</>
  if (b.market === 'Handicap 0.0') return <><TeamLabel name={b.team} /> (Remis = Einsatz zurück)</>
  if (b.outcome === 'handicap') return <>{b.market.replace('Handicap ', '')} <TeamLabel name={b.team} /></>
  if (b.outcome === 'home_win' || b.outcome === 'away_win') return <>Sieg <TeamLabel name={b.team} /></>
  if (b.team) return <TeamLabel name={b.team} />
  if (b.outcome === 'draw') return 'Remis'
  if (b.market === 'BTTS') return `Beide treffen: ${String(b.outcome).toLowerCase() === 'yes' ? 'Ja' : 'Nein'}`
  if (b.outcome === 'Over') return `Über ${b.market.replace('Over/Under ', '')}`
  if (b.outcome === 'Under') return `Unter ${b.market.replace('Over/Under ', '')}`
  return b.outcome
}

function marketGroupLabel(market) {
  if (market === '1X2') return 'Ergebnis'
  if (market === 'Handicap +0.5') return 'Doppelte Chance'
  if (market === 'Handicap 0.0') return 'Remis = Einsatz zurück'
  if (market.startsWith('Handicap')) return 'Asian Handicap'
  if (market === 'BTTS') return 'Beide treffen'
  return 'Tore'
}

// Plain-language phrasing of a bet for the Best Bets overview.
function plainBetPhrase(b) {
  if (b.outcome === 'home_win' || b.outcome === 'away_win') return <><TeamLabel name={b.team} /> gewinnt</>
  if (b.outcome === 'draw') return 'Remis'
  if (b.outcome === 'Over') return `Über ${b.market.replace('Over/Under ', '')} Tore`
  if (b.outcome === 'Under') return `Unter ${b.market.replace('Over/Under ', '')} Tore`
  if (b.market === 'Handicap +0.5') return <><TeamLabel name={b.team} /> oder Remis (Doppelte Chance)</>
  if (b.market === 'Handicap 0.0') return <><TeamLabel name={b.team} /> gewinnt (Remis = Einsatz zurück)</>
  if (b.outcome === 'handicap') return <><TeamLabel name={b.team} /> {b.market.replace('Handicap ', '')} Handicap</>
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
const signedPct = (x) => `${x >= 0 ? '+' : ''}${(x * 100).toFixed(1).replace('.', ',')}%`
const bookName = (b) => (b || 'bet-at-home').replace(/\.de$/, '')

// The headline tip: where bet-at-home pays more than Pinnacle's margin-free
// price (src/price_tip.py). Model and AI are shown beside it, not used by it.
function PriceTipBox({ priceTip }) {
  if (!priceTip) {
    return (
      <p className="smart-bet-notip">
        <strong>Kein Preis-Tipp für dieses Spiel.</strong><br />
        Hier gibt es keinen verlässlichen Referenzpreis.
      </p>
    )
  }
  const tip = priceTip.tip
  const book = bookName(priceTip.bookmaker)
  if (!tip) {
    return (
      <div className="price-tip is-empty">
        <div className="price-tip-none">
          💰 Kein Preis-Tipp – {priceTip.waiting
            ? 'entscheidet sich in der Stunde vor Anpfiff.'
            : (priceTip.reason || `${book} zahlt nirgends mehr als Pinnacles fairer Preis.`)}
        </div>
        <details className="price-tip-more">
          <summary>Vergleich ansehen</summary>
        {priceTip.outcomes.length > 0 && (
          <div className="price-tip-table">
            <div className="price-tip-table-head">
              <span>Ausgang</span><span>Pinnacle</span><span>{book}</span><span>Chance</span><span>Vorteil</span>
            </div>
            {priceTipRows(priceTip.outcomes).map((o) => (
              <div className="price-tip-table-row" key={`${o.market}-${o.outcome}-${o.side}`}>
                <span>{betOutcomeLabel(o)}</span>
                <span>{o.pinnacle_odds ? o.pinnacle_odds.toFixed(2) : <em title="faire Quote aus Pinnacles 1X2">{o.fair_odds.toFixed(2)}</em>}</span>
                <span>{o.book_odds.toFixed(2)}</span>
                <span title={o.refund_probability > 0 ? `Sieg ${pct(o.win_probability)} · Remis erstattet ${pct(o.refund_probability)} · Niederlage ${pct(o.loss_probability)}` : undefined}>
                  {pct(o.win_probability ?? o.probability)}{o.refund_probability > 0 ? '*' : ''}
                </span>
                <span className={o.edge >= priceTip.threshold ? 'positive' : 'negative'}>{signedPct(o.edge)}</span>
              </div>
            ))}
          </div>
        )}
        <p className="price-tip-footnote">
          {priceTip.outcomes.some(o => o.refund_probability > 0) && <>* Remis = Einsatz zurück: Chance auf Sieg; bei Remis gibt es den Einsatz zurück. </>}
          Ein Tipp erscheint, wenn {book} mindestens {pct(priceTip.threshold)} über Pinnacles fairem Preis zahlt.
          Das passiert meist in der letzten Stunde vor Anpfiff, wenn Pinnacle zuerst reagiert.
        </p>
        </details>
      </div>
    )
  }
  return (
    <div className="smart-bet-best price-tip">
      <span className="smart-bet-label">Preis-Tipp</span>
      <div className="smart-bet-pick">{betOutcomeLabel(tip)}</div>
      <div className="price-tip-kpis">
        <div className="price-tip-kpi">
          <span className="price-tip-kpi-label">Pinnacle</span>
          <span className="price-tip-kpi-value">{(tip.pinnacle_odds || tip.fair_odds).toFixed(2)}</span>
          <span className="price-tip-kpi-sub">{tip.pinnacle_odds ? `fair ${tip.fair_odds.toFixed(2)}` : 'fair, aus 1X2'}</span>
        </div>
        <div className="price-tip-kpi is-book">
          <span className="price-tip-kpi-label">{book}</span>
          <span className="price-tip-kpi-value">{tip.book_odds.toFixed(2)}</span>
          <span className="price-tip-kpi-sub">deine Quote</span>
        </div>
        <div className="price-tip-kpi">
          <span className="price-tip-kpi-label">Chance</span>
          <span className="price-tip-kpi-value">{pct(tip.win_probability ?? tip.probability)}</span>
          <span className="price-tip-kpi-sub">
            {tip.refund_probability > 0
              ? `Sieg · ${pct(tip.refund_probability)} zurück · ${pct(tip.loss_probability)} Niederlage`
              : 'laut Pinnacle'}
          </span>
        </div>
        <div className="price-tip-kpi is-edge">
          <span className="price-tip-kpi-label">Vorteil</span>
          <span className="price-tip-kpi-value">{signedPct(tip.edge)}</span>
          <span className="price-tip-kpi-sub">pro € Einsatz</span>
        </div>
      </div>
      <div className="smart-bet-agree-row">
        {priceTip.model_agrees != null && (
          <span className={`smart-bet-agree-chip ${priceTip.model_agrees ? 'yes' : 'no'}`}>
            {priceTip.model_agrees ? '◆ Modell stimmt zu ✓' : '◆ Modell sieht es anders ✕'}
            {priceTip.model_probability != null ? ` ${pct(priceTip.model_probability)}` : ''}
          </span>
        )}
        {priceTip.ai_agrees != null && (
          <span className={`smart-bet-agree-chip ${priceTip.ai_agrees ? 'yes' : 'no'}`}>
            {priceTip.ai_agrees ? '✨ KI stimmt zu ✓' : '✨ KI sieht es anders ✕'}
          </span>
        )}
      </div>
      <div className="smart-bet-best-meta">
        Nur nach Preis gewählt. Der Vorteil ist ein Durchschnitt über viele Wetten, kein Versprechen für diese.
      </div>
    </div>
  )
}

// The AI's research, closed until the reader asks for it.
function AgentFactors({ research }) {
  const [open, setOpen] = useState(false)
  const rows = [
    ['⚕', 'Aufstellung & Verletzungen', research.lineups_injuries],
    ['📈', 'Form', research.form],
    ['🏆', 'Tabellensituation', research.table_situation],
    ['💬', 'Sonstiges', research.other],
  ].filter(([, , text]) => text)
  if (rows.length === 0) return null
  return (
    <div className="wm-reveal agent-factors">
      <button className={`scout-btn${open ? ' is-open' : ''}`} onClick={() => setOpen(v => !v)} aria-expanded={open}>
        <span className="scout-btn-icon">🛰️</span>
        <span className="scout-btn-text">
          <span className="scout-btn-title">KI-Scout</span>
          <span className="scout-btn-sub">Was die Zahlen nicht sehen: Verletzungen, Aufstellung, Form, Tabelle – live recherchiert</span>
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
function LikelyTipBox({ pick, agentPick, sameBet, home, away }) {
  if (!pick) return null
  // Within five points of the market counts as agreeing: 69% against 73% is
  // noise, not a contrary view. The model's own number is shown either way.
  const modelP = pick.model_probability_raw
  const modelAgrees = modelP != null && modelP >= pick.market_probability - MODEL_TOLERANCE
  const aiAgrees = agentPick ? impliesBet(agentPick, pick, home, away, sameBet) : null
  return (
    <div className="likely-tip">
      <span className="smart-bet-label likely-tip-label">🎯 Am wahrscheinlichsten</span>
      <div className="likely-tip-row">
        <span className="likely-tip-pick">{betOutcomeLabel(pick)}</span>
        <span className="likely-tip-odds">{pick.best_odds.toFixed(2)}</span>
        <span className="likely-tip-chance">{pct(pick.market_probability)} Chance</span>
      </div>
      <div className="smart-bet-agree-row">
        <span className={`smart-bet-agree-chip ${modelAgrees ? 'yes' : 'no'}`}>
          {modelAgrees ? '◆ Modell stimmt zu ✓' : '◆ Modell sieht es anders ✕'}{modelP != null ? ` ${pct(modelP)}` : ''}
        </span>
        {aiAgrees != null && (
          <span className={`smart-bet-agree-chip ${aiAgrees ? 'yes' : 'no'}`}>
            {aiAgrees ? '✨ KI stimmt zu ✓' : '✨ KI sieht es anders ✕'}
          </span>
        )}
      </div>
    </div>
  )
}

function SmartBetCard({ betStep, betInfo, data }) {
  const [showAllMarkets, setShowAllMarkets] = useState(false)

  const analyzing = betStep < BET_STEPS.length
  if (analyzing) {
    return (
      <div className="analyzing-status">
        <span className="analyzing-spinner" />
        <span>{BET_STEPS[betStep]}</span>
      </div>
    )
  }
  if (!betInfo || !betInfo.odds_found) {
    return (
      <div className="wm-reveal">
        <p className="wm-subtle">Für dieses Spiel gibt es gerade keine Quoten.</p>
      </div>
    )
  }

  if (betInfo.in_play) {
    return (
      <div className="wm-reveal">
        <p className="smart-bet-notip">
          <strong>Dieses Spiel läuft bereits.</strong><br />
          Die Quoten sind jetzt live und bewegen sich mit dem Spielstand – unser Vorab-Modell lässt sich
          nicht mehr sinnvoll damit vergleichen. Kein Tipp für dieses Spiel.
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
  const allBets = (betInfo.bets && betInfo.bets.length) ? betInfo.bets : [...greens, ...reds]
  // Table order: the price tip, the market's likeliest bet, the model's
  // biggest gap to the market (★, explained in its box below), the AI's pick.
  // The model's favourite is no longer marked.
  const signals = [priceTipPick, likelyPick, best, agentPick].filter(Boolean)
  const signalRank = b => { const i = signals.findIndex(x => sameBet(x, b)); return i === -1 ? signals.length : i }
  // After the marked bets: positive edges with a stake of at least 1% -
  // first those without ⚠, then those with it - then the greyed rest
  // (smaller stakes, then no edge). Largest edge first within each group.
  const worthStaking = b => b.expected_value > 0 && (b.kelly_stake_pct || 0) >= 1
  const edgeGroup = b => worthStaking(b) ? (b.suspicious ? 1 : 0) : (b.expected_value > 0 ? 2 : 3)
  const ordered = [...allBets].sort((a, b) =>
    signalRank(a) - signalRank(b)
    || edgeGroup(a) - edgeGroup(b)
    || b.expected_value - a.expected_value)
  const visibleRows = showAllMarkets ? ordered : ordered.slice(0, TABLE_ROWS)
  const hiddenCount = ordered.length - TABLE_ROWS
  const hasUserBook = (betInfo.bets || []).some(b => b.bookmaker_key === USER_BOOK_KEY)

  // Greyed out: no positive edge, a stake under 1% (the sizing itself says
  // the bet is barely worth making), or a ⚠ - a model/market gap that is
  // more likely a model error than a bargain.
  const dimmed = b => b.expected_value <= 0 || (b.kelly_stake_pct || 0) < 1 || b.suspicious

  const renderRow = (b, i, kind) => {
    const isRec = best && sameBet(b, best)
    const isPriceTip = priceTipPick && sameBet(b, priceTipPick)
    const isAgentPick = agentPick && sameBet(b, agentPick)
    const isLikelyPick = likelyPick && sameBet(b, likelyPick)
    // Any marked signal (price tip 💰, value bet ★, AI pick ✨, model
    // favorite ◆, most likely 🎯) is a headline in its own right - dimming its
    // row to 40% opacity just because the model rates its edge negative
    // buries it, even though we deliberately show these regardless of edge.
    // The price tip especially is chosen against Pinnacle, not the model, so
    // the model's edge column may well be negative on it.
    const keepFullOpacity = isPriceTip || isAgentPick || isLikelyPick || isRec
    return (
      <div className={`smart-bet-table-row ${dimmed(b) && !keepFullOpacity ? 'is-red' : ''} ${isPriceTip ? 'is-rec' : ''}`}
           key={`${kind}-${i}`}>
        <span className="smart-bet-col-market">{marketGroupLabel(b.market)}{b.suspicious ? ' ⚠' : ''}</span>
        <span className="smart-bet-col-pick">
          {isPriceTip ? '💰 ' : ''}{isLikelyPick ? '🎯 ' : ''}{isRec ? '★ ' : ''}{isAgentPick ? '✨ ' : ''}{betOutcomeLabel(b)}
        </span>
        <span className="smart-bet-col-odds" title={b.bookmaker}>
          {b.best_odds.toFixed(2)}{b.bookmaker_key !== USER_BOOK_KEY && hasUserBook ? '*' : ''}
        </span>
        <span className={`smart-bet-col-edge ${b.expected_value >= 0 ? 'positive' : 'negative'}`}>
          {b.expected_value >= 0 ? '+' : ''}{(b.expected_value * 100).toFixed(0)}%
        </span>
        <span className="smart-bet-col-stake">{b.kelly_stake_pct}%</span>
      </div>
    )
  }

  return (
    <div className="wm-reveal smart-bet-card">
      <LikelyTipBox pick={likelyPick} agentPick={agentPick} sameBet={sameBet}
                    home={betInfo.home_team} away={betInfo.away_team} />
      <PriceTipBox priceTip={betInfo.price_tip} />

      {(greens.length > 0 || reds.length > 0) && (
        <div className="smart-bet-table">
          <div className="smart-bet-table-head">
            <span>Markt</span>
            <span>Tipp</span>
            <span>Quote</span>
            <span>Vorteil</span>
            <span>Einsatz</span>
          </div>
          {visibleRows.map((b, i) => renderRow(b, i, 'row'))}
          {hiddenCount > 0 && (
            <button className="smart-bet-more" onClick={() => setShowAllMarkets(v => !v)}>
              {showAllMarkets ? 'Weniger Märkte ▲' : `Alle Märkte zeigen (${hiddenCount} weitere) ▼`}
            </button>
          )}
          <p className="smart-bet-table-note">
            {hasUserBook
              ? 'Quoten von bet-at-home. * = bei bet-at-home nicht im Angebot, beste andere Quote gezeigt.'
              : 'Die vollen Märkte von bet-at-home werden in der Stunde vor Anpfiff gelesen; bis dahin zeigen wir die besten verfügbaren Quoten.'}
          </p>
        </div>
      )}

      <LineupStrength data={data} />

      {agentEval && (
        <div className="smart-bet-agent">
          <div className="smart-bet-agent-headtitle">
            <span className="smart-bet-agent-headline">✨ KI-Tipp: {agentEval.bet_headline}</span>
          </div>
          <p className="smart-bet-agent-text">
            {renderBoldMarkdown(agentEval.bet_reasoning, 'smart-bet-highlight-purple')}
            {agentPick && (
              <> Unser Modell sieht das bei <strong className="smart-bet-highlight-purple">{(agentPick.probability * 100).toFixed(0)}%</strong>.</>
            )}
          </p>
        </div>
      )}

      {best ? (
        <div className="smart-bet-signal-box is-green">
          <div className="smart-bet-agent-headtitle">
            <span className="smart-bet-signal-headline">★ Größte Abweichung vom Markt: {betOutcomeLabel(best)}</span>
          </div>
          <p className="smart-bet-agent-text">
            {best.market_probability != null ? (
              <>Wir sehen das bei <strong className="smart-bet-highlight-green">{(best.probability * 100).toFixed(0)}%</strong> (unser Modell ein Stück Richtung Markt gezogen, weil es sonst
              zu selbstsicher ist), während die Quote <strong className="smart-bet-highlight-green">{best.best_odds.toFixed(2)}</strong> von {best.bookmaker} {(best.market_probability * 100).toFixed(0)}% bedeutet –
              eine Abweichung von {Math.round((best.probability - best.market_probability) * 100)} Prozentpunkten.</>
            ) : (
              <>Wir sehen das bei <strong className="smart-bet-highlight-green">{(best.probability * 100).toFixed(0)}%</strong> zur Quote <strong className="smart-bet-highlight-green">{best.best_odds.toFixed(2)}</strong> von {best.bookmaker}; ein
              verlässlicher Marktvergleich fehlt hier.</>
            )}
          </p>
          <ModelTrackRecord bet={best} bets={betInfo.bets || []} competition={betInfo.sport_key} />
        </div>
      ) : (
        <div className="smart-bet-signal-box is-green">
          <div className="smart-bet-agent-headtitle">
            <span className="smart-bet-signal-headline">★ Größte Abweichung vom Markt: keine nennenswerte</span>
          </div>
          <p className="smart-bet-agent-text">
            {recWarning
              ? 'Die größte Abweichung in diesem Spiel ist zu klein, um sie zu nennen.'
              : 'Unser Modell und die Buchmacher liegen bei allen Märkten dieses Spiels nah beieinander.'}
          </p>
        </div>
      )}

      <div className="smart-bet-finePrint">
        <p>
          <strong>💰</strong> bet-at-home zahlt mehr als Pinnacles fairer Preis · <strong>🎯</strong> laut Markt
          wahrscheinlichste Wette (Quote 1,30–2,00; kein Vorteil, die Marge steckt drin) · <strong>✨</strong> Tipp der KI
          nach Recherche · <strong>★</strong> größte Abweichung des Modells vom Markt · <strong>⚠</strong> eher ein
          Modellfehler. <strong>+0,5</strong> = Doppelte Chance, <strong>0,0</strong> = Einsatz zurück bei Remis,
          andere Zahlen = Asian Handicap.
        </p>

      <p className="smart-bet-disclaimer">
        Nur zur Unterhaltung und Information. Das ist ein statistisches Modell, keine Wettberatung – es garantiert
        keinen Gewinn und hat keinen nachgewiesenen Vorteil gegenüber den Quoten der Buchmacher. Wetten kann zu
        finanziellen Verlusten führen; wenn du wettest, dann verantwortungsvoll und nur mit Geld, dessen Verlust du
        verkraften kannst. 18+. Hilfe bei Glücksspielproblemen: check-dein-spiel.de, Tel. 0800 1 37 27 00 (kostenlos).
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
          {gf.match_type && show(6) && <span className="wm-match-type">{MATCH_TYPES_DE[gf.match_type] || gf.match_type}</span>}
          {onCollapse && !analyzing && (
            <button className="wm-collapse-btn" onClick={onCollapse}>
              Einklappen ▲
            </button>
          )}
        </div>
      </div>

      <div className="result-header">
        <span className="team-name"><TeamLabel name={data.home_team} /></span>
        <div className="prediction-badge">
          {data.prediction === 'H' ? `${teamName(data.home_team)} gewinnt` :
           data.prediction === 'A' ? `${teamName(data.away_team)} gewinnt` : 'Remis'}
        </div>
        <span className="team-name"><TeamLabel name={data.away_team} /></span>
      </div>

      <FormRating data={data} />

      {analyzing && (
        <div className="analyzing-status">
          <span className="analyzing-spinner" />
          <span>{ANALYZING_STEPS[revealStep]}</span>
        </div>
      )}

      <div className="wm-cluster">
        <span className="wm-cluster-label">Überblick</span>

        <RevealSection visible={show(1)} className="probabilities-donut">
          <ResultDonut
            home={data.probability_home_win}
            draw={data.probability_draw}
            away={data.probability_away_win}
            score={sp.most_likely_score}
            colors={matchColors}
          />
          <div className="probabilities-legend">
            <span className="legend-title">Siegwahrscheinlichkeit</span>
            <div className="legend-row">
              <span className="legend-dot" style={{ background: matchColors.home }} />
              <span className="legend-name"><TeamLabel name={data.home_team} /></span>
              <span className="legend-value"><AnimatedNumber value={data.probability_home_win * 100} decimals={1} suffix="%" /></span>
            </div>
            <div className="legend-row">
              <span className="legend-dot gray" />
              <span className="legend-name">Remis</span>
              <span className="legend-value"><AnimatedNumber value={data.probability_draw * 100} decimals={1} suffix="%" /></span>
            </div>
            <div className="legend-row">
              <span className="legend-dot" style={{ background: matchColors.away }} />
              <span className="legend-name"><TeamLabel name={data.away_team} /></span>
              <span className="legend-value"><AnimatedNumber value={data.probability_away_win * 100} decimals={1} suffix="%" /></span>
            </div>
            {sp.most_likely_score && (
              <div className="legend-likely">
                Wahrscheinlichstes Ergebnis <strong>{sp.most_likely_score}</strong>
                {sp.top_scorelines?.[0] && <span className="wm-subtle"> ({(sp.top_scorelines[0].probability * 100).toFixed(0)}%)</span>}
              </div>
            )}
          </div>
        </RevealSection>

        <RevealSection visible={show(2)}>
          <MatchScenario data={data} />
        </RevealSection>
      </div>

      {!analyzing && (
        <details className="wm-details">
          <summary>Mehr Details: Märkte, Ergebnisse &amp; Halbzeit</summary>
          <div className="wm-cluster">
            <BettingMarkets data={data} />
            <div className="explanation-grid wm-grid">
              <div className="stat-card">
                <h4>Wahrscheinlichste Ergebnisse</h4>
                <p className="wm-subtle wm-scoreboard-xg">
                  xG: {Number(sp.home_xg).toFixed(2)} : {Number(sp.away_xg).toFixed(2)}
                </p>
                {(sp.top_scorelines || []).slice(0, 3).map((s, i) => (
                  <div className={`score-row${i === 0 ? ' is-leader' : ''}`} key={i}>
                    <span className="score-row-rank">{i === 0 ? '★' : i + 1}</span>
                    <span className="score-row-label">{s.score}</span>
                    <span className="score-row-value">{(s.probability * 100).toFixed(1)}%</span>
                  </div>
                ))}
              </div>
              <div className="stat-card">
                <h4>Halbzeit</h4>
                {(gf.top_halftime_scores || []).slice(0, 3).map((h, i) => (
                  <div className={`score-row${i === 0 ? ' is-leader' : ''}`} key={i}>
                    <span className="score-row-rank">{i === 0 ? '★' : i + 1}</span>
                    <span className="score-row-label">{h.score}</span>
                    <span className="score-row-value">{(h.probability * 100).toFixed(1)}%</span>
                  </div>
                ))}
                <div className="score-row is-drama">
                  <span className="score-row-rank">⚡</span>
                  <span className="score-row-label score-row-label-wide">Spätes Drama (75'+)</span>
                  <span className="score-row-value">{((gf.late_drama_probability || 0) * 100).toFixed(0)}%</span>
                </div>
              </div>
            </div>
            {gf.match_description && gf.match_description !== 'Both teams play attacking football at an even level' && (
              <p className="wm-description">{MATCH_DESCRIPTIONS_DE[gf.match_description] || gf.match_description}</p>
            )}
          </div>
        </details>
      )}

      {!analyzing && betInfo && betInfo.agent_eval && betInfo.agent_eval.research && (
        <div className="wm-cluster wm-cluster-scout">
          <AgentFactors research={betInfo.agent_eval.research} />
        </div>
      )}

      {!analyzing && onStartBetCheck && (
        <div className="wm-cluster wm-cluster-bet">
          <span className="wm-cluster-label">Wett-Analyse</span>

          {onStartBetCheck && (
            <div className="smart-bet-section" id={`bets-${matchId}`}>
              {betStep === undefined ? (
                <div className="smart-bet-cta">
                  <span className="smart-bet-cta-icon">🎯</span>
                  <h4 className="smart-bet-cta-title">Modell gegen Buchmacher-Quoten?</h4>
                  <p className="smart-bet-cta-sub">
                    Wo Modell und Markt übereinstimmen, wo nicht – mit einem Tipp.
                  </p>
                  <button className="smart-bet-btn" onClick={onStartBetCheck}>
                    Quoten-Vergleich zeigen
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

function HeroPreviewCard() {
  const colors = getMatchColors('Real Madrid', 'Barcelona')
  return (
    <div className="hero-preview card">
      <div className="hero-preview-badge">
        <span className="hero-preview-badge-dot" />
        KI-Prognose
      </div>
      <div className="hero-preview-teams">
        <span className="hero-preview-team"><TeamLabel name="Real Madrid" /></span>
        <span className="hero-preview-vs">vs</span>
        <span className="hero-preview-team"><TeamLabel name="Barcelona" /></span>
      </div>
      <div className="hero-preview-body">
        <ResultDonut home={0.48} draw={0.24} away={0.28} score="2–1" colors={colors} />
        <div className="hero-preview-bars">
          <ProbabilityBar label="Real Madrid" value={0.48} color={colors.home} />
          <ProbabilityBar label="Remis" value={0.24} color={colors.draw} />
          <ProbabilityBar label="FC Barcelona" value={0.28} color={colors.away} />
        </div>
      </div>
      <p className="hero-preview-note">
        „Enge erste Hälfte erwartet – Real Madrids Tempo im Konter bricht nach 60 Minuten den Bann.“
      </p>
    </div>
  )
}

const FLOW_STEPS = [
  {
    icon: <IconDataPoints />,
    title: 'Daten sammeln',
    description:
      'Jede Analyse beginnt mit echter Fußballhistorie – mehrere Spielzeiten an Ergebnissen, ' +
      'Liga- und Pokaldaten sowie laufende Form- und Torstatistiken für jedes Team, ' +
      'das wir abdecken.',
    tags: ['Historische Ergebnisse', 'Direkte Duelle', 'Torstatistik', 'Aktuelle Form'],
  },
  {
    icon: <IconFeatures />,
    title: 'Merkmale berechnen',
    description:
      'Aus den Rohdaten werden Signale, aus denen die Modelle lernen können: Elo-Stärkewerte, ' +
      'Angriffs- und Abwehrwerte pro Team, die Bilanz der direkten Duelle, der Heimvorteil ' +
      'und die Formkurve aus den letzten Spielen.',
    tags: ['Elo-Werte', 'Angriff & Abwehr', 'Direkte Duelle', 'Heimvorteil'],
  },
  {
    icon: <IconNeuralNet />,
    title: 'Modell-Ensemble',
    description:
      'Drei unabhängige Modelle rechnen jedes Spiel parallel durch – ein Dixon-Coles-Poisson-Modell ' +
      'für realistische Ergebnisse, ein XGBoost-Modell für nichtlineare Muster und ein Random Forest ' +
      'für Stabilität. Ihre Ergebnisse werden zu einem gemeinsamen Urteil kombiniert.',
    tags: ['Dixon-Coles-Poisson', 'XGBoost', 'Random Forest', 'Ensemble'],
  },
  {
    icon: <IconTarget />,
    title: 'Ergebnis & Wahrscheinlichkeiten',
    description:
      'Das Ensemble liefert eine Wahrscheinlichkeit für jedes realistische Ergebnis und leitet ' +
      'daraus die Chancen auf Sieg, Remis und Niederlage, das wahrscheinlichste Endergebnis und ' +
      'die erwarteten Tore (xG) beider Teams ab.',
    tags: ['Sieg/Remis/Niederlage %', 'Wahrscheinlichstes Ergebnis', 'Erwartete Tore (xG)'],
  },
  {
    icon: <IconTimeline />,
    title: 'Spielverlauf',
    description:
      'Eine eigene Spielverlaufs-Berechnung schätzt, wie sich die 90 Minuten entwickeln – wann Tore ' +
      'fallen, der Halbzeitstand, spätes Drama – und ordnet den Charakter des Spiels ein, ' +
      'von „Abwehrschlacht“ bis „Torfestival“.',
    tags: ['Tor-Zeitpunkte', 'Halbzeit & Endstand', 'Spieltyp', 'Spätes Drama'],
  },
  {
    icon: <IconSpark />,
    title: 'KI-Einordnung',
    description:
      'Eine KI fasst die berechneten Zahlen in einem Satz zusammen, den Fußballfans verstehen. ' +
      'Sie darf nur die Zahlen des Modells verwenden – keine erfundenen Fakten –, damit der Text ' +
      'der Prognose nie widerspricht.',
    tags: ['KI-Zusammenfassung', 'Nur Modell-Zahlen', 'Keine erfundenen Fakten'],
  },
  {
    icon: <IconBroadcast />,
    title: 'Veröffentlichung',
    description:
      'Die fertige Analyse wird gespeichert und ist sofort auf der Website abrufbar – ' +
      'Wahrscheinlichkeiten, Ergebnis und Spielverlauf. Dieselben Zahlen landen automatisch ' +
      'als Kurzvideo auf TikTok und Instagram.',
    tags: ['Website', 'TikTok & Instagram', 'Automatisiert', 'Sofort verfügbar'],
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
        <span className="how-eyebrow">Hinter den Prognosen</span>
        <h2 className="section-title">So funktioniert unsere KI-Analyse</h2>
        <p className="how-intro">
          Vom ersten Datenpunkt bis zum fertigen Social-Media-Video – jede Prognose durchläuft
          dieselben sieben Stufen. Scroll nach unten und folge den Daten durch jede Stufe.
        </p>
        <button className="flow-back-btn" onClick={onBack}>← Zurück zu den Prognosen</button>
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
                <span className="flow-scroll-step-num">Stufe {i + 1} / {FLOW_STEPS.length}</span>
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
        Zurück zu den Prognosen
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
  const rows = [{ key: 'ko', minute: "1'", type: 'kickoff', head: '🟢 Anpfiff', text: `${home_} gegen ${away_} läuft.`, score: '0:0' }]
  let halftimeShown = false
  events.forEach((e, i) => {
    const t = tickerMinute(e.minute)
    if (!halftimeShown && t.base > 45) {
      rows.push({ key: 'ht', minute: 'HZ', type: 'halftime', head: '⏸️ Halbzeit', text: `${home_} ${score()} ${away_} zur Pause.`, score: score() })
      halftimeShown = true
    }
    if (e.type === 'goal') {
      if (e.team === homeTeam) home += 1; else away += 1
      const how = e.own_goal ? ' (Eigentor)' : e.penalty ? ' (Elfmeter)' : ''
      rows.push({ key: i, minute: e.minute, type: 'goal', head: `⚽ TOR für ${teamName(e.team)}!`,
                  text: `${e.player || 'Unbekannt'}${how} trifft zum ${score()}.`, score: score() })
    } else if (e.type === 'red_card') {
      rows.push({ key: i, minute: e.minute, type: 'chance', head: `🟥 Rote Karte – ${teamName(e.team)}`,
                  text: `${e.player || 'Ein Spieler'} fliegt vom Platz. ${teamName(e.team)} spielt zu zehnt weiter.`, score: score() })
    } else if (e.type === 'yellow_card') {
      rows.push({ key: i, minute: e.minute, type: 'yellow', head: `🟨 Gelbe Karte – ${teamName(e.team)}`,
                  text: `${e.player || 'Ein Spieler'} sieht Gelb.`, score: null })
    }
  })
  if (!halftimeShown) {
    rows.push({ key: 'ht', minute: 'HZ', type: 'halftime', head: '⏸️ Halbzeit', text: `${home_} ${score()} ${away_} zur Pause.`, score: score() })
  }
  const final = homeScore != null ? `${homeScore}:${awayScore}` : score()
  rows.push({ key: 'ft', minute: 'Ende', type: 'fulltime', head: '🏁 Abpfiff', text: `${home_} ${final} ${away_}.`, score: final })

  return (
    <div className="wm-stories real-ticker">
      <h4>Liveticker</h4>
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
      <h4>Spielstatistik</h4>
      <div className="h2h-teams">
        <span><TeamLabel name={homeTeam} /></span>
        <span><TeamLabel name={awayTeam} /></span>
      </div>
      {stats.home.possession != null && (
        <HeadToHeadStat label="Ballbesitz" home={stats.home.possession} away={stats.away.possession} suffix="%" />
      )}
      {stats.home.shots != null && (
        <HeadToHeadStat label="Schüsse" home={stats.home.shots} away={stats.away.shots} />
      )}
      {stats.home.shots_on_target != null && (
        <HeadToHeadStat label="Schüsse aufs Tor" home={stats.home.shots_on_target} away={stats.away.shots_on_target} />
      )}
      {stats.home.corners != null && (
        <HeadToHeadStat label="Ecken" home={stats.home.corners} away={stats.away.corners} />
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
      <p className="wm-subtle" style={{ marginBottom: '0.9rem', fontSize: '0.75rem' }}>KI-Prognose vor dem Spiel</p>

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
          <span className="legend-title">Siegwahrscheinlichkeit</span>
          <div className="legend-row">
            <span className={`legend-dot ${homeCorrect ? 'hit' : 'gold'}`} />
            <span className="legend-name"><TeamLabel name={aiData.home_team} />{homeCorrect ? ' ✓' : ''}</span>
            <span className="legend-value"><AnimatedNumber value={aiData.probability_home_win * 100} decimals={1} suffix="%" /></span>
          </div>
          <div className="legend-row">
            <span className={`legend-dot ${drawCorrect ? 'hit' : 'gray'}`} />
            <span className="legend-name">Remis{drawCorrect ? ' ✓' : ''}</span>
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
            <h4>Vorhergesagte Ergebnisse</h4>
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
              <h4>Märkte</h4>
              {btts.yes != null && (() => {
                const hit = actualBtts === (btts.yes >= 0.5)
                return (
                  <div className="stat-row" style={hit ? { color: '#4ade80' } : {}}>
                    <span className="stat-label" style={hit ? { color: '#4ade80', fontWeight: 700 } : {}}>Beide treffen: {actualBtts ? 'Ja' : 'Nein'}{hit ? ' ✓' : ''}</span>
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
                    <span className="stat-label" style={hit ? { color: '#4ade80', fontWeight: 700 } : {}}>{over ? 'Über' : 'Unter'} {deNum(o.line)} Tore{hit ? ' ✓' : ''}</span>
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
          <span className="fixture-final-badge">Beendet</span>
        </div>
        <div className="fixture-teams">
          <span><TeamLabel name={fixture.home_team} /></span>
          <span className="fixture-final-score">{result.home_score} – {result.away_score}</span>
          <span><TeamLabel name={fixture.away_team} /></span>
        </div>
        <span className="fixture-expand-hint">Tippen für Details ▾</span>
      </div>
    )
  }

  return (
    <div className="card wm-card">
      <div className="wm-card-header">
        <span className="wm-match-id">{fixtureWhen(fixture)}</span>
        <div className="wm-card-header-right">
          <span className="wm-match-type" style={{ background: 'rgba(34,197,94,0.15)', color: '#4ade80' }}>Beendet</span>
          <button className="wm-collapse-btn" onClick={() => setExpanded(false)}>Einklappen ▲</button>
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
            {showAI ? '▲ KI-Prognose ausblenden' : '▼ Mit der KI-Prognose vergleichen'}
          </button>
          {showAI && <AiComparisonPanel fixture={fixture} result={result} aiData={aiData} />}
        </div>
      )}

      {!aiData && (
        <div style={{ marginTop: '1rem' }}>
          {analysisActive
            ? <p className="wm-subtle">KI-Analyse wird geladen…</p>
            : <button className="fixture-generate-btn" onClick={onGenerate}>KI-Analyse vor dem Spiel zeigen</button>
          }
        </div>
      )}
    </div>
  )
}

export default function App() {
  const [page, setPage] = useState('home')
  const [predictionsById, setPredictionsById] = useState({})
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
        <a className="nav-brand" href="/" aria-label="GoalIQ Startseite">
          <img className="nav-logo" src="/favicon.svg" alt="" />
          <span className="nav-title">Goal<span>IQ</span></span>
        </a>
        <div className="nav-links">
          <a href="#predictions" onClick={() => setPage('home')}>Prognosen</a>
          <a href="#how-it-works" onClick={(e) => { e.preventDefault(); setPage('how-it-works') }}>So funktioniert's</a>
        </div>
      </nav>

      {page === 'home' && <MatchTicker results={realResults} competitionKey={tickerCompetition} />}

      {page === 'home' && (
        <>
          <header className="hero">
            <HeroVisual />
            <div className="hero-grid">
              <div className="hero-content">
                <div className="hero-top">
                  <span className="hero-eyebrow">Fußball, nachgerechnet</span>
                </div>
                <h1>KI-Prognosen für jedes Spiel</h1>
                <p>
                  Ein KI-Modell, trainiert auf tausenden Spielen, rechnet jede Partie durch: Siegchancen,
                  wahrscheinlichstes Ergebnis und Spielverlauf. Nach dem Abpfiff zeigen wir ehrlich,
                  ob die KI richtig lag.
                </p>
                <div className="competition-badge">
                  <img src="https://a.espncdn.com/i/leaguelogos/soccer/500-dark/2.png" alt="" className="competition-badge-logo" />
                  <span>Jetzt mit <strong>Bundesliga, Champions League &amp; Nations League</strong></span>
                </div>
                <div className="hero-stats">
                  <div className="hero-stat">
                    <span className="hero-stat-value">Tausende</span>
                    <span className="hero-stat-label">Spiele ausgewertet</span>
                  </div>
                  <div className="hero-stat">
                    <span className="hero-stat-value">36</span>
                    <span className="hero-stat-label">Klubs in der Ligaphase</span>
                  </div>
                  <div className="hero-stat">
                    <span className="hero-stat-value">189</span>
                    <span className="hero-stat-label">Spiele in der Ligaphase</span>
                  </div>
                  <div className="hero-stat">
                    <span className="hero-stat-value">1</span>
                    <span className="hero-stat-label">Pokal</span>
                  </div>
                </div>
              </div>
              <HeroPreviewCard />
            </div>
          </header>

          <main className="main">
            <section id="predictions" className="wm-section">
              <h2 className="section-title">Prognosen</h2>

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
                <button className="competition-pill soon" disabled title="Bald verfügbar">
                  <span className="competition-pill-emoji">🏴󠁧󠁢󠁥󠁮󠁧󠁿</span>
                  Premier League
                  <span className="competition-pill-soon">Bald</span>
                </button>
                <button className="competition-pill soon" disabled title="Bald verfügbar">
                  <span className="competition-pill-emoji">🇪🇸</span>
                  La Liga
                  <span className="competition-pill-soon">Bald</span>
                </button>
              </div>

              <div className="group-tabs">
                <button
                  className={`group-tab special-tab ${activeGroup === 'next' ? 'active' : ''}`}
                  onClick={() => setActiveGroup('next')}
                >
                  📅 Nächste Spiele
                </button>
                <button
                  className={`group-tab special-tab ${activeGroup === 'hot' ? 'active' : ''}`}
                  onClick={() => setActiveGroup('hot')}
                >
                  🔥 Topspiel
                </button>
                <button
                  className={`group-tab special-tab ${activeGroup === 'combo' ? 'active' : ''}`}
                  onClick={() => { setActiveGroup('combo'); if (combo === null && !comboLoading) loadCombo() }}
                >
                  🎟️ Kombi-Schein
                </button>
                {currentGroups.map(g => (
                  <button
                    key={g}
                    className={`group-tab ${activeGroup === g ? 'active' : ''}`}
                    onClick={() => setActiveGroup(g)}
                  >
                    {groupLabel(g)}
                  </button>
                ))}
              </div>

              {wmLoading && (
                <div className="analyzing-status loading-inline">
                  <span className="analyzing-spinner" />
                  <span>Analysen werden geladen…</span>
                </div>
              )}

              {activeGroup === 'combo' && (
                <ComboTicketView combo={combo} loading={comboLoading} onOpenLeg={openLeg} />
              )}

              {activeGroup === 'next' && nextGames.length === 0 && (
                <p className="wm-subtle">Heute stehen keine Spiele an.</p>
              )}

              {activeGroup === 'hot' && (
                nextGames.length === 0
                  ? <p className="wm-subtle">Heute stehen keine Spiele an.</p>
                  : <p className="wm-subtle hot-game-subtitle">🔥 Das Topspiel des Tages – das spannendste Duell laut KI.</p>
              )}


              <div className="fixtures-list">
                {(() => {
                  let fixtures
                  if (activeGroup === 'next') {
                    fixtures = nextGames
                  } else if (activeGroup === 'hot') {
                    const hotFixture = getHotFixture(predictionsById, nextGames)
                    fixtures = hotFixture ? [hotFixture] : []
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
        <p>GoalIQ – KI-Prognosen, nur zur Unterhaltung. Keine Wettberatung. · <a href="mailto:kontakt@goaliq.de">kontakt@goaliq.de</a></p>
      </footer>
    </div>
  )
}
