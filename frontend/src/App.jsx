import { Fragment, useState, useEffect, useRef, useSyncExternalStore } from 'react'
import axios from 'axios'
import './App.css'
import CL_FIXTURES from './cl_fixtures.json'
import BL_FIXTURES from './bl_fixtures.json'
import NL_FIXTURES from './nl_fixtures.json'
import CLUB_CRESTS from './club_crests.json'
import TEAM_COLORS from './team_colors.json'
import TEAM_NAMES_DE from './team_names_de.json'
import TEAM_NAMES_BS from './team_names_bs.json'
import STRINGS_BS from './strings_bs.json'
import { fixtureDateTime, nextGamesFor } from './fixtureSchedule.js'
import { matchPath, sectionPath } from './navigation.js'
import { useSiteRoute } from './useSiteRoute.js'
import { createComboCacheEntry, comboCacheIsCurrent } from './comboCache.js'

const API_BASE = import.meta.env.VITE_API_BASE ?? (import.meta.env.DEV ? 'http://127.0.0.1:8000' : '')

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


// The page's language: German by default, English or Bosnian on request (the
// switch at the top right), remembered in the browser. Every text a visitor
// reads goes through tr(german, english[, bosnian]); changing LANG re-renders
// the whole app. The Bosnian text is looked up by its German text in
// strings_bs.json; a third argument gives it directly (texts with numbers or
// names in them). A text without a Bosnian version shows in English.
const LANGS = ['de', 'en', 'bs']
let LANG = (() => {
  try {
    const saved = localStorage.getItem('goaliq-lang')
    return LANGS.includes(saved) ? saved : 'de'
  } catch { return 'de' }
})()
const missingBs = new Set()
function bosnian(de, en, bs) {
  if (bs !== undefined) return bs
  if (STRINGS_BS[de] !== undefined) return STRINGS_BS[de]
  if (import.meta.env.DEV && !missingBs.has(de)) { missingBs.add(de); console.warn('[bs] missing:', de) }
  return en
}
const tr = (de, en, bs) => (LANG === 'en' ? en : LANG === 'bs' ? bosnian(de, en, bs) : de)
const LOCALE = () => ({ en: 'en-GB', bs: 'bs-BA' }[LANG] || 'de-DE')
// A date for the reader. Browsers often lack Bosnian date data (and answer in
// English), so Bosnian dates are written here.
const BS_DAYS = ['nedjelja', 'ponedjeljak', 'utorak', 'srijeda', 'četvrtak', 'petak', 'subota']
const BS_DAYS_SHORT = ['ned', 'pon', 'uto', 'sri', 'čet', 'pet', 'sub']
const BS_MONTHS = ['jan', 'feb', 'mar', 'apr', 'maj', 'jun', 'jul', 'aug', 'sep', 'okt', 'nov', 'dec']
function localeDate(date, options) {
  if (LANG !== 'bs') return date.toLocaleDateString(LOCALE(), options)
  const weekday = options.weekday === 'long' ? BS_DAYS[date.getDay()] : options.weekday ? BS_DAYS_SHORT[date.getDay()] : ''
  const day = options.day ? `${date.getDate()}. ${BS_MONTHS[date.getMonth()]}` : ''
  return [weekday, day].filter(Boolean).join(', ')
}
const DEC = () => (LANG === 'en' ? '.' : ',')

// Teams keep their English key everywhere (fixtures, odds, colours); only
// the name a visitor reads is German or Bosnian - in English the key itself.
const teamName = name => (LANG === 'en' ? name
  : LANG === 'bs' ? (TEAM_NAMES_BS[name] || name)
  : (TEAM_NAMES_DE[name] || name))
// 1.79 -> "1,79" in German, unchanged in English
const deNum = v => String(v ?? '').replace('.', DEC())

// "Do 01.10. · 20:45" / "Thu 01/10 · 20:45"
function fixtureWhen(f) {
  const d = new Date(`${f.date}T12:00:00`)
  const weekday = localeDate(d, { weekday: 'short' }).replace('.', '')
  return LANG === 'en'
    ? `${weekday} ${f.date.slice(8, 10)}/${f.date.slice(5, 7)} · ${f.time}`
    : `${weekday} ${f.date.slice(8, 10)}.${f.date.slice(5, 7)}. · ${f.time}`
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
// the fallback. The whole season is listed, but a match's analysis opens at
// 00:00 (Berlin) PREDICTION_LEAD_DAYS before its matchday - the daily job
// (src/jobs.REPREDICT_DAYS) has predicted it by then. Tabs cover the
// matchdays around today.
const PREDICTION_LEAD_DAYS = 2
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
  const day = new Date(Date.parse(`${fixture.date}T12:00:00Z`) - PREDICTION_LEAD_DAYS * 86400000).toISOString().slice(0, 10)
  return fixtureDateTime({ date: day, time: '00:00' })
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

// Windows draws a flag emoji as two letters ("DE"), Apple as a flag. A flag
// image looks the same everywhere, so flags are shown as images.
function flagUrl(emoji) {
  const cps = [...emoji].map(c => c.codePointAt(0))
  const isRegional = c => c >= 0x1F1E6 && c <= 0x1F1FF
  if (cps.length === 2 && cps.every(isRegional)) {
    return `https://flagcdn.com/w40/${String.fromCharCode(...cps.map(c => c - 0x1F1E6 + 97))}.png`
  }
  if (cps[0] === 0x1F3F4 && cps.length > 2) {   // England, Scotland, Wales: tag letters "gbeng"
    const code = String.fromCharCode(...cps.slice(1, -1).map(c => c - 0xE0000))
    return `https://flagcdn.com/w40/${code.slice(0, 2)}-${code.slice(2)}.png`
  }
  return null
}
const FLAG_ENGLAND = String.fromCodePoint(0x1F3F4, 0xE0067, 0xE0062, 0xE0065, 0xE006E, 0xE0067, 0xE007F)
const FLAG_SPAIN = String.fromCodePoint(0x1F1EA, 0x1F1F8)
// The language switch: a flag and the code for each language.
const LANG_CHOICES = [
  { code: 'de', flag: String.fromCodePoint(0x1F1E9, 0x1F1EA), name: 'Deutsch' },
  { code: 'en', flag: String.fromCodePoint(0x1F1EC, 0x1F1E7), name: 'English' },
  { code: 'bs', flag: String.fromCodePoint(0x1F1E7, 0x1F1E6), name: 'Bosanski' },
]

// An emoji, or an image when it is a flag.
function Emoji({ char, className = '' }) {
  const url = flagUrl(char)
  return url
    ? <img src={url} alt="" className={`team-crest team-flag ${className}`} />
    : <span className={className}>{char}</span>
}

// The switch at the top right: a flag and the code for each language.
function LanguageSwitch({ lang, onChange }) {
  return (
    <div className="lang-switch" role="group" aria-label={tr('Sprache', 'Language')}>
      {LANG_CHOICES.map(({ code, flag, name }) => (
        <button key={code} className={lang === code ? 'active' : ''} onClick={() => onChange(code)}
                aria-pressed={lang === code} aria-label={name} title={name}>
          <Emoji char={flag} className="lang-flag" />{code.toUpperCase()}
        </button>
      ))}
    </div>
  )
}

function TeamLabel({ name, placeholder = false }) {
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
  // A team without a crest or flag gets a neutral badge when asked, so every name keeps its place.
  const badge = flag ? <Emoji char={flag} className="team-flag-emoji" /> : (placeholder && <span className="team-crest team-crest-placeholder" aria-hidden="true">{String(name).trim().charAt(0)}</span>)
  return <>{badge}{teamName(name)}</>
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
  // Scores as "2:1" (German) or "2-1" / "2–1" (English).
  const numberPattern = String.raw`\d+(?:[.,]\d+)?\s?%|\d+[:\-–]\d+`
  const parts = text.split(new RegExp(`(${escaped.join('|')}|${numberPattern})`, 'g'))
  return parts.map((part, i) =>
    terms.includes(part)
      ? <span className="scenario-highlight" key={i}>{part}</span>
      : /^(\d+(?:[.,]\d+)?\s?%|\d+[:\-–]\d+)$/.test(part)
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

// In English or Bosnian, the AI's German texts (scenario, AI tip, KI-Scout)
// come from GET /ai-texts-en?lang=..., translated once on the server and kept.
// The server answers with a map German text -> translation for the whole
// match; a page looks up exactly the text it shows. Whatever is still missing
// (the AI has not written it yet, the translation failed) is asked for again
// every 15 seconds, four times at most; until it arrives the German text shows.
const AI_TEXTS = {}
const AI_TEXTS_RETRY_MS = 15000
const AI_TEXTS_TRIES = 4
function useAiTexts(home, away, shown) {
  const lang = LANG
  const key = `${lang}__${home}__${away}`
  const [, redraw] = useState(0)
  const kept = AI_TEXTS[key]
  const missing = lang !== 'de' && shown.some(t => t && !kept?.map[t])
  useEffect(() => {
    if (!home || !away) return
    if (!missing) { if (AI_TEXTS[key]) AI_TEXTS[key].tries = 0; return }
    const entry = AI_TEXTS[key] || (AI_TEXTS[key] = { map: {}, busy: false, at: 0, tries: 0 })
    if (entry.busy || entry.tries >= AI_TEXTS_TRIES) return
    const wait = entry.at + AI_TEXTS_RETRY_MS - Date.now()
    if (wait > 0) {
      const timer = setTimeout(() => redraw(x => x + 1), wait)
      return () => clearTimeout(timer)
    }
    entry.busy = true
    entry.tries += 1
    entry.at = Date.now()
    axios.get(`${API_BASE}/ai-texts-en`, { params: { home_team: home, away_team: away, lang } })
      .then(r => { entry.map = { ...entry.map, ...(r.data?.texts || {}) } })
      .catch(() => {})
      .finally(() => { entry.busy = false; redraw(x => x + 1) })
  })
  return text => (lang === 'de' || !text ? text : kept?.map[text] ?? text)
}

function MatchScenario({ data }) {
  const bm = (data.score_prediction || {}).betting_markets
  const home = data.home_team
  const away = data.away_team
  const aiText = useAiTexts(home, away, [bm?.scenario])
  if (!bm) return null
  return (
    <div className="betting-markets">
      <div className="scenario-box">
        <h4>{tr('Wahrscheinlichstes Szenario', 'Most likely scenario')}</h4>
        <p>{renderScenario(aiText(bm.scenario), home, away)}</p>
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

// One bet of a combo as a casino chip: the front shows the odds, the back the
// market probability; the bet itself stands under it, with the signs and a
// button that opens the match.
// The signs are always all there: the ones that apply glow gold, the rest are grey.
function ComboChipFlags({ leg }) {
  const flags = [
    { icon: '◆', on: leg.model_probability != null && leg.model_probability >= leg.market_probability,
      label: tr('Modell stimmt zu', 'Model agrees', 'Model se slaže'), off: tr('Modell weicht ab', 'Model disagrees', 'Model se ne slaže') },
    { icon: '✨', on: Boolean(leg.ki_agrees), label: tr('KI-Tipp', 'AI pick', 'AI tip'), off: tr('Kein KI-Tipp', 'Not the AI pick', 'Nije AI tip') },
    { icon: '🎯', on: Boolean(leg.is_likely), label: tr('Wahrscheinlichster Tipp', 'Most likely bet', 'Najvjerovatniji tip'),
      off: tr('Nicht der wahrscheinlichste Tipp dieses Spiels', 'Not the most likely bet of this match', 'Nije najvjerovatniji tip ove utakmice') },
  ]
  return (
    <span className="combo-chip-flags">
      {flags.map(f => <span key={f.icon} className={`combo-flag ${f.on ? 'is-on' : ''}`} title={f.on ? f.label : f.off}>{f.icon}</span>)}
    </span>
  )
}

// One bet of a combo as a casino chip: the front shows the odds, the back the
// market probability; it turns when the pointer is on it (or on a tap). Above
// it stands the match, below it the bet in two fixed lines, the signs and a
// button that opens the match.
function ComboChip({ leg, onOpenLeg, flipped = false, onFlip }) {
  return (
    <div className="combo-chip-wrap">
      <div className="combo-chip-game" title={`${teamName(leg.home_team)} – ${teamName(leg.away_team)}`}>
        <span><TeamLabel name={leg.home_team} /></span>
        <span><TeamLabel name={leg.away_team} /></span>
      </div>
      <button type="button" className={`combo-chip ${flipped ? 'is-flipped' : ''}`} onClick={onFlip}
              aria-label={`${tr('Quote', 'Odds', 'Kvota')} ${leg.best_odds.toFixed(2)}, ${tr('Wahrscheinlichkeit', 'Probability', 'Vjerovatnoća')} ${betPercent(leg.market_probability)}`}>
        <span className="combo-chip-face combo-chip-front">
          <span className="combo-chip-odds">{leg.best_odds.toFixed(2)}</span>
          <span className="combo-chip-sub">{tr('Quote', 'Odds', 'Kvota')}</span>
        </span>
        <span className="combo-chip-face combo-chip-back">
          <span className="combo-chip-odds">{betPercent(leg.market_probability)}</span>
          <span className="combo-chip-sub">{tr('Wahrscheinlichkeit', 'Probability', 'Vjerovatnoća')}</span>
        </span>
      </button>
      <div className="combo-chip-bet">{plainBetPhrase(leg, false)}</div>
      <ComboChipFlags leg={leg} />
      {onOpenLeg && <button type="button" className="combo-chip-open" onClick={() => onOpenLeg(leg)}>{tr('Spiel öffnen', 'Open match', 'Otvori utakmicu')}</button>}
    </div>
  )
}

const PHONE_QUERY = '(max-width: 899px)'
const subscribePhone = cb => {
  const mq = window.matchMedia(PHONE_QUERY)
  mq.addEventListener('change', cb)
  return () => mq.removeEventListener('change', cb)
}

// The chips of a ticket. On a laptop they stand side by side; on a phone one
// chip at a time slides in, on its own every 5 seconds, until the reader touches it.
function ComboChips({ legs, onOpenLeg }) {
  const phone = useSyncExternalStore(subscribePhone, () => window.matchMedia(PHONE_QUERY).matches, () => false)
  return phone ? <ComboCarousel legs={legs} onOpenLeg={onOpenLeg} /> : <ComboRow legs={legs} onOpenLeg={onOpenLeg} />
}

// On a laptop the chips stand side by side and turn when the pointer is on
// them (see the CSS); a click still turns one for touch screens.
function ComboRow({ legs, onOpenLeg }) {
  const [flipped, setFlipped] = useState({})
  return (
    <div className="combo-chips">
      {legs.map((leg, i) => <ComboChip key={i} leg={leg} onOpenLeg={onOpenLeg} flipped={Boolean(flipped[i])} onFlip={() => setFlipped(f => ({ ...f, [i]: !f[i] }))} />)}
    </div>
  )
}

// The first chip is repeated at the end: after the last one the track slides on
// to that copy and then jumps back to the real first, so it never runs back
// across the others.
function ComboCarousel({ legs, onOpenLeg }) {
  const n = legs.length
  const [idx, setIdx] = useState(0)
  const [animate, setAnimate] = useState(true)
  const [stopped, setStopped] = useState(false)
  const [flipped, setFlipped] = useState(false)
  const touchX = useRef(null)
  const active = idx % n

  // Every 5 seconds the next chip slides in, until the reader touches the carousel.
  useEffect(() => {
    if (stopped || n < 2 || window.matchMedia?.('(prefers-reduced-motion: reduce)').matches) return undefined
    const timer = setTimeout(() => { setFlipped(false); setAnimate(true); setIdx(i => (i >= n ? i : i + 1)) }, 5000)
    return () => clearTimeout(timer)
  }, [stopped, n, idx])

  const go = target => { setStopped(true); setFlipped(false); setAnimate(true); setIdx(target) }
  const prev = () => {
    setStopped(true); setFlipped(false)
    if (idx === 0) { setAnimate(false); setIdx(n - 1) } else { setAnimate(true); setIdx(idx - 1) }
  }
  const settle = () => {
    // On the copy of the first chip: jump (without sliding) to the real first.
    if (idx >= n) { setAnimate(false); setIdx(0) }
  }

  return (
    <div className="combo-carousel" onPointerDown={() => setStopped(true)}
         onTouchStart={e => { touchX.current = e.touches[0].clientX }}
         onTouchEnd={e => {
           if (touchX.current == null) return
           const dx = e.changedTouches[0].clientX - touchX.current
           touchX.current = null
           if (dx < -40) { if (idx < n) go(idx + 1) } else if (dx > 40) prev()
         }}>
      <div className="combo-carousel-window">
        <div className="combo-carousel-track"
             style={{ transform: `translateX(-${idx * 100}%)`, transition: animate ? undefined : 'none' }}
             onTransitionEnd={settle}>
          {[...legs, legs[0]].map((leg, i) => (
            <div className="combo-carousel-slide" key={i} inert={i % n !== active ? true : undefined}>
              <ComboChip leg={leg} onOpenLeg={onOpenLeg} flipped={flipped && i % n === active} onFlip={() => { setStopped(true); setFlipped(f => !f) }} />
            </div>
          ))}
        </div>
      </div>
      {n > 1 && (
        <>
          <button type="button" className="combo-carousel-arrow is-prev" aria-label={tr('Vorheriger Tipp', 'Previous bet', 'Prethodni tip')} onClick={prev}>‹</button>
          <button type="button" className="combo-carousel-arrow is-next" aria-label={tr('Nächster Tipp', 'Next bet', 'Sljedeći tip')} onClick={() => { if (idx < n) go(idx + 1) }}>›</button>
          <div className="combo-carousel-dots" role="tablist">
            {legs.map((_, i) => (
              <button key={i} type="button" role="tab" aria-selected={i === active}
                      aria-label={`${i + 1} / ${n}`} className={i === active ? 'is-active' : ''} onClick={() => go(i)} />
            ))}
          </div>
        </>
      )}
    </div>
  )
}

function ComboTicketCard({ ticket, primary, onOpenLeg }) {
  // Folded, a ticket is one line: its size and the combined odds. A click opens it.
  const [open, setOpen] = useState(false)
  return (
    <div className={`combo-ticket ${primary ? 'is-primary' : ''} ${open ? 'is-open' : ''}`}>
      <button type="button" className="combo-ticket-head" aria-expanded={open} onClick={() => setOpen(o => !o)}>
        <span className="combo-ticket-legs">{tr(`${ticket.leg_count}er-Kombi`, `${ticket.leg_count}-fold`, `Kombinacija od ${ticket.leg_count}`)}</span>
        <span className="combo-quote">
          <span className="combo-quote-label">{tr('Gesamtquote', 'Combined odds', 'Ukupna kvota')}</span>
          <span className="combo-ticket-odds">{ticket.combined_odds.toFixed(2)}</span>
        </span>
        <span className="combo-ticket-chevron" aria-hidden="true">▾</span>
      </button>
      {open && (
        <>
          <div className="combo-legs">
            <ComboChips legs={ticket.legs} onOpenLeg={onOpenLeg} />
          </div>
          <dl className="bet-metrics probability-metrics">
            <BetMetric label={tr('Chance, dass alle treffen', 'Chance all of them land')} value={betPercent(ticket.conservative_probability)}
                       detail={tr('Nach Marktpreisen, ohne Marge', "By the market's prices, margin removed")} emphasis />
            <BetMetric label={tr('Unser Modell allein', 'Our model on its own')} value={betPercent(ticket.probability)} detail={tr('Vor dem Abgleich mit dem Preis', 'Before checking against the price')} />
          </dl>
          {primary && (
            <p className="combo-ticket-note">
              {tr(`Die Wahrscheinlichkeiten nehmen an, dass die Ergebnisse unabhängig voneinander sind. Die Quoten
              stammen aus den Einzelmärkten; das Kombi-Angebot selbst wurde nicht
              geprüft. Wir erwarten mit dieser Wette keinen Gewinn – es ist nur der wahrscheinlichste Schein
              über der Zielquote.`, `Probabilities assume the results are independent of one another. Prices come from
              the individual markets; the combined offer itself has not been checked. This is not
              a bet we expect to profit from - it is the likeliest ticket above the target odds.`,
              `Vjerovatnoće pretpostavljaju da su ishodi međusobno nezavisni. Kvote potiču iz pojedinačnih tržišta;
              sama ponuda kombinacije nije provjerena. Ne očekujemo dobitak od ove oklade – to je samo
              najvjerovatniji tiket iznad ciljane kvote.`)}
            </p>
          )}
        </>
      )}
    </div>
  )
}

// A ticket belongs to a league only when every one of its legs does. The
// server already filters by league; this keeps a mixed ticket off the screen
// even if it ever sends one.
function ticketInLeague(ticket, sportKey) {
  return !sportKey || !ticket || (ticket.legs || []).every(leg => !leg.sport_key || leg.sport_key === sportKey)
}

function ComboTicketView({ combo, loading, onOpenLeg, sportKey }) {
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
      {!combo.recommended && (
        <p className="smart-bet-notip">
          <strong>{tr('Heute kein Kombi-Schein.', 'No combo ticket today.')}</strong><br />
          {tr(combo.reason, 'No same-day ticket passes all checks.', 'Nijedan tiket za isti dan ne prolazi sve provjere.')}
        </p>
      )}

      {combo.days?.map(day => (
        <div className="combo-day" key={day.date}>
          <span className="combo-section-label">
            {localeDate(new Date(day.date + 'T12:00:00'), { weekday: 'long', day: 'numeric', month: 'short' })}
            {' · '}{day.eligible_legs} {day.eligible_legs === 1 ? tr('passendes Spiel', 'eligible match') : tr('passende Spiele', 'eligible matches')}
          </span>

          <div className="combo-size-grid">
            {(day.by_size || []).map(raw => {
              const option = {
                ...raw,
                ticket: ticketInLeague(raw.ticket, sportKey) ? raw.ticket : null,
                near_miss: ticketInLeague(raw.near_miss, sportKey) ? raw.near_miss : null,
              }
              return (
              <section className="combo-size-option" key={option.leg_count}
                       aria-label={tr(`${option.leg_count}er-Kombi`, `${option.leg_count}-fold combo`, `Kombinacija od ${option.leg_count}`)}>
                {/* A ticket's own header names its size; only an empty slot needs a title. */}
                {!option.ticket && <h3 className="combo-size-title">{tr(`${option.leg_count}er-Kombi`, `${option.leg_count}-fold combo`, `Kombinacija od ${option.leg_count}`)}</h3>}
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
                    <p>{tr(option.reason || `Keine ${option.leg_count}er-Kombi verfügbar: Dafür braucht es ${option.leg_count} passende Spiele und die Zielquote.`,
                      `No ${option.leg_count}-fold available: it needs ${option.leg_count} qualifying matches and the target combined odds.`,
                      `Kombinacija od ${option.leg_count} nije dostupna: potrebne su ${option.leg_count} odgovarajuće utakmice i ciljana ukupna kvota.`)}</p>
                  </div>
                )}
              </section>
              )
            })}
          </div>
        </div>
      ))}

      <ComboLegend />
    </div>
  )
}

// What the signs next to the combo legs mean.
function ComboLegend() {
  return (
    <div className="combo-legend">
      <span className="combo-legend-title">{tr('Signale', 'Signals')}</span>
      <span><b className="combo-flag is-on">◆</b> {tr('Die Modelleinschätzung zum KI-Tipp', 'The model estimate for the AI pick')}</span>
      <span><b className="combo-flag is-on">✨</b> {tr('Der KI-Tipp für dieses Spiel', 'The AI pick for this match')}</span>
      <span><b className="combo-flag is-on">🎯</b> {tr('Der wahrscheinlichste Tipp dieses Spiels', "This match's most likely selection")}</span>
      <span className="combo-legend-note">{tr('Golden leuchtet ein Zeichen, wenn es zutrifft, grau, wenn nicht.', 'A sign glows gold when it applies, grey when it does not.')}</span>
    </div>
  )
}

function FixtureRow({ fixture }) {
  const opens = predictionOpensAt(fixture)
  const label = opens > new Date()
    ? `${tr('Analyse ab', 'Analysis from')} ${localeDate(opens, { weekday: 'short', day: 'numeric', month: 'short' })}`
    : tr('Analyse folgt', 'Analysis coming')
  return (
    <div className="fixture-row fixture-pending" id={`match-${fixture.match_id}`}>
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
    <div className="fixture-row fixture-ready" id={`match-${fixture.match_id}`}>
      <div className="fixture-meta">
        <span className="fixture-date">{fixtureWhen(fixture)}</span>
        <span className="fixture-ready-badge">{tr('Analyse bereit', 'Analysis ready')}</span>
      </div>
      <div className="fixture-teams">
        <span><TeamLabel name={fixture.home_team} /></span>
        <span className="fixture-vs">vs</span>
        <span><TeamLabel name={fixture.away_team} /></span>
      </div>
      <div className="fixture-actions">
        <button className="fixture-generate-btn" onClick={onGenerate}>
          {tr('KI-Analyse starten', 'Start AI analysis')}
        </button>
        {onBets && (
          <button className="fixture-generate-btn fixture-bets-btn" onClick={onBets}>
            {tr('Wett-Tipps zeigen', 'Show bet tips')}
          </button>
        )}
      </div>
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
                                     `Both teams score: ${String(b.outcome).toLowerCase() === 'yes' ? 'Yes' : 'No'}`,
                                     `Oba tima pogađaju: ${String(b.outcome).toLowerCase() === 'yes' ? 'Da' : 'Ne'}`)
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
// crests=false names the team in plain text (inside a chip there is no room for a crest).
function plainBetPhrase(b, crests = true) {
  const who = crests ? <TeamLabel name={b.team} /> : teamName(b.team)
  if (b.outcome === 'home_win' || b.outcome === 'away_win') return <>{who} {tr('gewinnt', 'to win')}</>
  if (b.outcome === 'draw') return tr('Remis', 'Draw')
  if (b.outcome === 'Over') return tr(`Über ${lineOf(b.market)} Tore`, `Over ${lineOf(b.market)} goals`, `Preko ${lineOf(b.market)} gola`)
  if (b.outcome === 'Under') return tr(`Unter ${lineOf(b.market)} Tore`, `Under ${lineOf(b.market)} goals`, `Ispod ${lineOf(b.market)} gola`)
  if (b.market === 'Handicap +0.5') return <>{who} {tr('oder Remis (Doppelte Chance)', 'or draw (double chance)')}</>
  if (b.market === 'Handicap 0.0') return <>{who} {tr('gewinnt (Remis = Einsatz zurück)', 'to win (draw no bet)')}</>
  if (b.outcome === 'handicap') return <>{who} {lineOf(b.market)} Handicap</>
  if (b.market === 'BTTS') return tr(`Beide treffen: ${String(b.outcome).toLowerCase() === 'yes' ? 'Ja' : 'Nein'}`,
                                     `Both teams score: ${String(b.outcome).toLowerCase() === 'yes' ? 'Yes' : 'No'}`,
                                     `Oba tima pogađaju: ${String(b.outcome).toLowerCase() === 'yes' ? 'Da' : 'Ne'}`)
  return b.market
}

// Must match src/price_tip.py MODEL_TOLERANCE.
const MODEL_TOLERANCE = 0.05
const pct = (x, digits = 0) => `${(x * 100).toFixed(digits)}%`

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

function AgentFactors({ research: researchDe, home, away }) {
  const [open, setOpen] = useState(false)
  const aiText = useAiTexts(home, away, Object.values(researchDe))
  const research = Object.fromEntries(Object.entries(researchDe).map(([k, v]) => [k, aiText(v)]))
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

// Shown until /site-stats answers (it counts, so it takes a moment): the hit rate
// of the Wett-Tipp when this was last updated (14 November 2026, 25 of 51).
const DEFAULT_HIT_RATE = 0.49

// The headline tip accepts changes at the pre-kickoff review.
// The server decides it (bet_tip); this is the fallback.
function computeBetTip(betInfo, agentEval) {
  if (betInfo.bet_tip && betInfo.bet_tip.rule) return betInfo.bet_tip
  if (agentEval?.pick_unavailable) return { tip: null, status: 'pick_unavailable' }
  const pick = agentEval?.pick
  if (!pick) return { tip: null, status: 'waiting_for_ai' }
  if (pick.quote_fresh === false && !pick.quote_carried_forward) return { tip: null, status: 'odds_expired' }
  if (pick.market_probability == null || pick.best_odds < 1.30)
    return { tip: null, status: 'no_agreement' }
  const model = pick.model_probability_raw ?? pick.probability
  return {
    tip: pick,
    status: 'ok',
    confirmed: typeof agentEval.revised_from_previous === 'boolean',
    model_agrees: model == null ? null : model >= pick.market_probability,
  }
}

function BetTipBox({ betTip, hideStatus = false }) {
  const tip = betTip?.tip
  if (!tip) {
    const why = {
      waiting_for_ai: tr('Folgt, sobald die KI das Spiel geprüft hat (in den 12 Stunden vor Anpfiff).', 'Coming once the AI has checked the match (in the 12 hours before kickoff).'),
      pick_unavailable: tr('Die KI hat das Spiel geprüft. Für ihre ausgewählte Wette gibt es aktuell keine Quote im Angebot.', 'The AI has checked the match. Its selected bet currently has no available quote.'),
      no_selection: tr('Kein Wett-Tipp – die KI findet aktuell keine ausreichend begründete Wette.', 'No bet tip – the AI currently finds no sufficiently supported bet.'),
      incomplete_markets: tr('Noch kein Wett-Tipp – aktuelle Quoten für Sieg, Handicap oder Über/Unter fehlen.', 'No bet tip yet – current win, handicap or totals odds are missing.'),
      ai_unsure: tr('Kein Wett-Tipp – der gespeicherte Tipp wurde nach der früheren Wechselregel zurückgehalten.', 'No bet tip – the saved selection was withheld under the previous change rule.'),
      no_agreement: tr('Kein Wett-Tipp – die Bedingungen für einen Tipp sind nicht erfüllt.', 'No bet tip – the conditions for a tip are not met.'),
      odds_expired: tr('Kein Wett-Tipp – die Quoten sind nicht mehr gültig. Bitte erneut laden.', 'No bet tip – the odds are no longer valid. Please reload.'),
    }[betTip?.status] || tr('Kein Wett-Tipp für dieses Spiel.', 'No bet tip for this match.')
    return (
      <div className="bet-tip is-empty">
        <span className="smart-bet-label bet-tip-label">{tr('Wett-Tipp', 'Bet tip')}</span>
        <div className="bet-tip-none">{why}</div>
      </div>
    )
  }
  const model = tip.model_probability_raw ?? tip.probability
  return (
    <div className="bet-tip">
      <span className="smart-bet-label bet-tip-label">{tr('Wett-Tipp', 'Bet tip')}</span>
      <div className="likely-tip-row">
        <span className="bet-tip-pick">{betOutcomeLabel(tip)}</span>
        <span className="likely-tip-odds">{tip.best_odds.toFixed(2)}</span>
        <span className="likely-tip-chance">{pct(tip.market_probability)} {tr('Chance', 'chance')}</span>
      </div>
      <div className="smart-bet-agree-row">
        {model != null && <span className={`smart-bet-agree-chip ${betTip.model_agrees === false ? 'muted' : 'yes'}`}>◆ {betTip.model_agrees === false ? tr('Modell weicht ab', 'Model disagrees') : tr('Modell stimmt zu', 'Model agrees')} {pct(model)}{betTip.model_agrees === false ? ' ✕' : ' ✓'}</span>}
      </div>
      {!hideStatus && (
        <div className={`bet-tip-status ${betTip.confirmed ? 'is-confirmed' : ''}`}>
          {betTip.confirmed
            ? tr('bestätigt – die KI-Prüfung vor Anpfiff ist abgeschlossen', 'confirmed – the AI review before kickoff is complete')
            : tr('vorläufig – die KI prüft das Spiel etwa eine Stunde vor Anpfiff noch einmal', 'provisional – the AI reviews the match again about an hour before kickoff')}
        </div>
      )}
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
      </> : LANG === 'bs' ? <>
        Prema tržištu najvjerovatnija oklada s kvotom između 1,30 i 2,00:
        {' '}<strong>{pct(pick.market_probability)}</strong> šanse uz kvotu <strong>{deOdds(pick.best_odds)}</strong>.
        {' '}Vjerovatno ne znači isplativo – marža kladionice je ugrađena.
      </> : <>
        Laut Markt die wahrscheinlichste Wette mit Quote zwischen 1,30 und 2,00:
        {' '}<strong>{pct(pick.market_probability)}</strong> Chance zur Quote <strong>{deOdds(pick.best_odds)}</strong>.
        {' '}Wahrscheinlich heißt nicht lohnend – die Marge des Buchmachers steckt drin.
      </>}
    </TipCard>
  )
}

function SmartBetCard({ betStep, betInfo, data, onRefresh, currentTime }) {
  const [showAllMarkets, setShowAllMarkets] = useState(false)
  const shownEval = betInfo?.agent_eval
  const aiText = useAiTexts(data?.home_team, data?.away_team,
    [shownEval?.bet_headline, shownEval?.bet_reasoning, shownEval?.revised_from_previous ? shownEval?.change_reason : ''])

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

  const snapshotExpired = betInfo.snapshot_valid === false
    || (betInfo.snapshot_valid_until && currentTime >= Date.parse(betInfo.snapshot_valid_until))
  if (snapshotExpired) {
    return (
      <div className="wm-reveal">
        <p className="smart-bet-notip">
          {tr('Der Quotenstand ist abgelaufen. Bitte lade die Wett-Tipps erneut, um aktuelle Daten abzurufen.',
              'This odds snapshot has expired. Reload the bet tips to fetch updated data.')}
        </p>
        {onRefresh && <button className="fixture-generate-btn" onClick={onRefresh}>
          {tr('Quoten erneut laden', 'Reload odds')}
        </button>}
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
  // The price tip is no longer shown (3 tips in 77 matches, none landed).
  const priceTipPick = null
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
    .filter(b => b.market !== 'Handicap 0.0' || (agentPick && sameBet(b, agentPick)))
  // Table order: the price tip, the market's likeliest bet, the model's
  // biggest gap to the market (★, explained in its box below), the AI's pick.
  // The model's favourite is no longer marked.
  const betTip = computeBetTip(betInfo, agentEval)
  const changedBeforeKickoff = agentEval?.revised_from_previous && agentEval?.change_reason
  const agentReason = changedBeforeKickoff
    ? `${tr('Vor Anpfiff geändert: ', 'Changed before kickoff: ')}${aiText(agentEval.change_reason)}`
    : aiText(agentEval?.bet_reasoning)
  const signals = [betTip.tip, priceTipPick, likelyPick, agentPick].filter(Boolean)
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
        <span className="smart-bet-col-odds">
          {b.best_odds.toFixed(2)}
        </span>
        <span className="smart-bet-col-chance">
          {b.market_probability != null ? `${Math.round(b.market_probability * 100)}%` : '–'}
        </span>
      </div>
    )
  }

  return (
    <div className="wm-reveal smart-bet-card">
      <BetTipBox betTip={betTip} />

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
              {showAllMarkets ? tr('Weniger Märkte ▲', 'Fewer markets ▲') : tr(`Alle Märkte zeigen (${hiddenCount} weitere) ▼`, `Show all markets (${hiddenCount} more) ▼`, `Prikaži sva tržišta (još ${hiddenCount}) ▼`)}
            </button>
          )}
          <p className="smart-bet-table-note">
            {tr('Quoten können je nach Anbieter leicht abweichen.', 'Odds may differ slightly between bookmakers.')}
          </p>
        </div>
      )}

      {agentEval && (
        <div className="smart-bet-agent">
          <div className="smart-bet-agent-headtitle">
            <span className="smart-bet-agent-headline">✨ {tr('KI-Tipp', 'AI tip')}: {aiText(agentEval.bet_headline)}</span>
          </div>
          <p className="smart-bet-agent-text">
            {renderBoldMarkdown(agentReason, 'smart-bet-highlight-purple')}
            {agentEval.pick_unavailable && (
              <> {tr('Diese Auswahl stammt aus dem früheren Quotenstand und ist aktuell nicht verfügbar.', 'This selection comes from the earlier odds snapshot and is currently unavailable.')}</>
            )}
            {agentPick && (
              <> {tr('Unser Modell sieht das bei', 'Our model puts this at')} <strong className="smart-bet-highlight-purple">{((agentPick.model_probability_raw ?? agentPick.probability) * 100).toFixed(0)}%</strong>.</>
            )}
          </p>
        </div>
      )}

      <LikelyTipBox pick={likelyPick} />

      <LineupStrength data={data} />

      <div className="smart-bet-finePrint">
        {LANG === 'en' ? (
          <p>
            <strong>Bet tip</strong> = the AI's pick when our model rates it at least as likely as the market (odds from 1.30);
            {' '}none if the AI changed its pick shortly before kickoff · <strong>🎯</strong> the market's
            likeliest bet (odds 1.30–2.00; no edge, the margin is built in) · <strong>✨</strong> the AI's pick after research ·
            {' '}<strong>⚠</strong> more likely a model error · <strong>✨</strong> after a pick: the AI agrees; grey = the model
            does not agree, odds under 1.30 or chance under 50%. <strong>+0.5</strong> = double chance, <strong>0.0</strong> = draw no bet,
            other numbers = Asian handicap.
          </p>
        ) : LANG === 'bs' ? (
          <p>
            <strong>Tip za okladu</strong> = tip AI-ja kada ga naš model ocjenjuje barem toliko vjerovatnim kao tržište (kvota od 1,30);
            {' '}nema ga ako je AI promijenio tip neposredno prije početka · <strong>🎯</strong> prema tržištu najvjerovatnija
            oklada (kvota 1,30–2,00; bez prednosti, marža je ugrađena) · <strong>✨</strong> tip AI-ja nakon istraživanja ·
            {' '}<strong>⚠</strong> prije greška modela · <strong>✨</strong> iza tipa: AI se slaže; sivo = model se ne slaže,
            kvota ispod 1,30 ili šansa ispod 50 %. <strong>+0,5</strong> = dvostruka šansa, <strong>0,0</strong> = povrat uloga kod neriješenog,
            ostali brojevi = azijski hendikep.
          </p>
        ) : (
          <p>
            <strong>Wett-Tipp</strong> = der Tipp der KI, wenn unser Modell ihn mindestens so hoch einschätzt wie der Markt (Quote ab 1,30);
            {' '}keiner, wenn die KI ihren Tipp kurz vor Anpfiff geändert hat · <strong>🎯</strong> laut Markt
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

function WmPredictionCard({ matchId, data, fixture, onCollapse, revealStep = Infinity, betStep, onStartBetCheck, betInfo, currentTime }) {
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
          {data.prediction === 'H' ? tr(`${teamName(data.home_team)} gewinnt`, `${teamName(data.home_team)} to win`, `${teamName(data.home_team)} pobjeđuje`) :
           data.prediction === 'A' ? tr(`${teamName(data.away_team)} gewinnt`, `${teamName(data.away_team)} to win`, `${teamName(data.away_team)} pobjeđuje`) : tr('Remis', 'Draw')}
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
                <SmartBetCard betStep={betStep} betInfo={betInfo} data={data} onRefresh={onStartBetCheck} currentTime={currentTime} />
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

// The network of lines and points runs from the top of the landing page down
// to the footer, in three bands (top, middle, bottom) that each keep their place
// whatever the window's shape. Gold glow at the top and at the bottom.
const HERO_BANDS = {
  top: {
    glow: [400, 60, 260],
    lines: [[60, 40, 200, 20], [600, 30, 740, 60], [600, 30, 690, 100], [60, 40, 40, 120], [740, 60, 760, 140]],
    dots: [[60, 40, 3], [200, 20, 2.5], [600, 30, 3], [740, 60, 2.5], [690, 100, 2.5], [40, 120, 2.5], [760, 140, 2.5]],
  },
  mid: {
    lines: [[40, 40, 110, 130], [110, 130, 50, 230], [50, 230, 130, 320], [760, 30, 690, 120], [690, 120, 770, 220], [770, 220, 700, 330]],
    dots: [[40, 40, 2.5], [110, 130, 3], [50, 230, 2.5], [130, 320, 3], [760, 30, 2.5], [690, 120, 3], [770, 220, 2.5], [700, 330, 3]],
  },
  bottom: {
    glow: [420, 330, 300],
    lines: [[60, 320, 200, 340], [200, 340, 330, 300], [600, 330, 740, 300], [600, 330, 690, 260], [60, 320, 40, 240], [740, 300, 760, 220]],
    dots: [[60, 320, 3], [200, 340, 2.5], [330, 300, 3], [600, 330, 3], [740, 300, 2.5], [690, 260, 2.5], [40, 240, 2.5], [760, 220, 2.5]],
  },
}

function HeroVisual() {
  return Object.entries(HERO_BANDS).map(([band, { glow, lines, dots }], bi) => (
    <svg key={band} className={`hero-visual hero-visual-${band}`} viewBox="0 0 800 360" fill="none"
         xmlns="http://www.w3.org/2000/svg" preserveAspectRatio="xMidYMid slice" aria-hidden="true">
      <defs>
        <radialGradient id={`heroGlow-${band}`} cx="50%" cy="50%" r="50%">
          <stop offset="0%" stopColor="#d4af37" stopOpacity="0.12" />
          <stop offset="100%" stopColor="#d4af37" stopOpacity="0" />
        </radialGradient>
      </defs>
      {glow && <circle cx={glow[0]} cy={glow[1]} r={glow[2]} fill={`url(#heroGlow-${band})`} />}
      <g stroke="#d4af37" strokeWidth="1" opacity="0.15">
        {lines.map(([x1, y1, x2, y2], i) => <line key={i} x1={x1} y1={y1} x2={x2} y2={y2} />)}
      </g>
      <g fill="#f4cf6e">
        {dots.map(([cx, cy, r], i) => (
          <circle key={i} className="hero-visual-dot" cx={cx} cy={cy} r={r} opacity="0.35"
                  style={{ animationDelay: `${((bi * 5 + i) * 0.7) % 6}s` }} />
        ))}
      </g>
    </svg>
  ))
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

const berlinDate = (iso) => new Date(iso).toLocaleDateString('sv-SE', { timeZone: 'Europe/Berlin' })

// The ticker looks back at most a week: only results of the last 7 days.
const TICKER_DAYS = 7

function lastWeek(results, key, now = new Date()) {
  const today = new Date(berlinDate(now))
  return results.filter(r => r.completed && r.sport_key === COMPETITIONS[key].sportKey
    && (today - new Date(berlinDate(r.commence_time))) / 86400000 < TICKER_DAYS)
}

// Before anyone picks a competition, the ticker mixes the headline results
// of every competition's last week; after, it follows the chosen one.
function tickerResults(results, competitionKey) {
  if (competitionKey) {
    return lastWeek(results, competitionKey)
      .sort((a, b) => new Date(a.commence_time) - new Date(b.commence_time))
  }
  const byValue = (a, b) => (b.headline_value || 0) - (a.headline_value || 0)
  return Object.keys(COMPETITIONS)
    .flatMap(key => lastWeek(results, key).sort(byValue).slice(0, 5))
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

// The sample Wett-Tipp of the landing card, in the shape the match page gets
// from the API, so it renders through the same BetTipBox.
const HERO_BET_TIP = {
  tip: { market: 'Over/Under 2.5', outcome: 'Over', best_odds: 1.55, market_probability: 0.62, model_probability_raw: 0.64 },
  model_agrees: true,
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
    title: tr('KI-Recherche mit Live-Daten', 'AI research with live data'),
    description: tr(
      'Die Zahlen kennen nur die Vergangenheit. Deshalb checkt unsere KI vor jedem Spiel die aktuellen Fakten: Aufstellung, Verletzungen, Form und Quoten. Daraus macht sie eine klare Empfehlung – oder sagt ehrlich: kein Tipp. Kurz vor Anpfiff prüft sie noch einmal.',
      'The numbers only know the past. So before every match our AI checks the latest facts: line-ups, injuries, form and odds. It turns them into one clear recommendation – or honestly says: no tip. Shortly before kickoff it checks again.'),
    tags: [tr('Live-Daten', 'Live data'), tr('Klare Empfehlung', 'Clear recommendation'), tr('Last-Minute-Check', 'Last-minute check')],
  },
  {
    icon: <IconBroadcast />,
    title: tr('Veröffentlicht – und nachgeprüft', 'Published – and verified'),
    description: tr(
      'Vor jedem Anpfiff steht die komplette Analyse samt Wett-Tipp auf der Website. Nach dem Spiel stehen die Ergebnisse bereit – und du siehst, ob der Tipp richtig lag.',
      'Before every kickoff the full analysis, including the bet tip, is on the website. After the match the results are ready – and you see whether the tip was right.'),
    tags: [tr('Wett-Tipp', 'Bet tip'), tr('Ergebnisse nach dem Spiel', 'Results after the match'), tr('Treffer-Check', 'Hit check')],
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

// A looping mini-demo of the app on the "So funktioniert's" page: pick a
// league, open a match, read the analysis, see the Wett-Tipp, check it after
// the match. Sample data only, same look as the real pages.
const DEMO_SCENES = () => [
  { key: 'league', caption: tr('Liga wählen', 'Pick a league') },
  { key: 'match', caption: tr('Spiel öffnen', 'Open a match') },
  { key: 'analysis', caption: tr('KI-Analyse lesen', 'Read the AI analysis') },
  { key: 'bets', caption: tr('Wett-Tipps zeigen', 'Show the bet tips') },
  { key: 'tip', caption: tr('Wett-Tipp sehen', 'See the bet tip') },
  { key: 'result', caption: tr('Nach dem Spiel prüfen', 'Check it after the match') },
]

function AppDemo({ onStart }) {
  const scenes = DEMO_SCENES()
  const [scene, setScene] = useState(0)
  // Every scene (picked by hand or not) runs 3.2 s, then the next one follows.
  useEffect(() => {
    const reduce = typeof window !== 'undefined' && window.matchMedia?.('(prefers-reduced-motion: reduce)').matches
    if (reduce) return undefined
    const id = setTimeout(() => setScene(s => (s + 1) % scenes.length), 3200)
    return () => clearTimeout(id)
  }, [scene, scenes.length])
  const colors = { home: '#d4af37', draw: '#6b7280', away: '#dc052d' }
  const current = scenes[scene].key
  return (
    <div className="app-demo">
      <div className="app-demo-phone">
        <div className="app-demo-screen" key={current}>
          {current === 'league' && (
            <div className="demo-pane">
              <div className="demo-pills">
                {['Alle', 'Champions League', 'Bundesliga', 'Nations League'].map((n, i) => (
                  <span key={n} className={'demo-pill' + (i === 2 ? ' is-picked' : '')}>
                    {n}{i === 2 && <span className="demo-tap" />}
                  </span>
                ))}
              </div>
            </div>
          )}
          {current === 'match' && (
            <div className="demo-pane">
              {[['Bayer Leverkusen', 'SC Paderborn'], ['Real Madrid', 'Bayern Munich'], ['RB Leipzig', 'Union Berlin']].map(([h, a], i) => (
                <div key={h} className={'demo-row' + (i === 1 ? ' is-picked' : '')}>
                  <span><TeamLabel name={h} /></span><span className="demo-vs">vs</span><span><TeamLabel name={a} /></span>
                  {i === 1 && <span className="demo-tap" />}
                </div>
              ))}
            </div>
          )}
          {current === 'analysis' && (
            <div className="demo-pane demo-center">
              <div className="probabilities-donut demo-probs">
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
            </div>
          )}
          {current === 'bets' && (
            <div className="demo-pane demo-center">
              <div className="demo-match-head">
                <span><TeamLabel name="Real Madrid" /></span><span className="demo-vs">vs</span><span><TeamLabel name="Bayern Munich" /></span>
              </div>
              <div className="demo-btns">
                <span className="fixture-generate-btn demo-btn">{tr('KI-Analyse starten', 'Start AI analysis')}</span>
                <span className="fixture-generate-btn fixture-bets-btn demo-btn demo-btn-picked">
                  {tr('Wett-Tipps zeigen', 'Show bet tips')}<span className="demo-tap" />
                </span>
              </div>
            </div>
          )}
          {current === 'tip' && (
            <div className="demo-pane demo-center demo-pop"><BetTipBox betTip={HERO_BET_TIP} hideStatus /></div>
          )}
          {current === 'result' && (
            <div className="demo-pane demo-center">
              <div className="demo-final"><TeamLabel name="Real Madrid" /> <b>1 – 2</b> <TeamLabel name="Bayern Munich" /></div>
              <div className="demo-hit">{tr('Wett-Tipp eingetroffen', 'Bet tip won')} ✓</div>
              <div className="demo-hit-sub">{tr('Über 2,5 Tore – 3 Tore gefallen', 'Over 2.5 goals – 3 goals scored')}</div>
            </div>
          )}
        </div>
      </div>
      <div className="app-demo-caption" aria-live="polite">
        <span className="app-demo-step">{scene + 1}</span> {scenes[scene].caption}
      </div>
      <div className="app-demo-dots">
        {scenes.map((sc, i) => (
          <button key={sc.key} className={i === scene ? 'is-on' : ''} aria-label={sc.caption}
                  onClick={() => setScene(i)} />
        ))}
      </div>
      {onStart && (
        <button className="app-demo-cta" onClick={onStart}>
          {tr('Analyse jetzt starten', 'Start your analysis now')} <span aria-hidden="true">→</span>
        </button>
      )}
    </div>
  )
}

// The background of "So funktioniert's": rising data points and a gold glow that moves down with the stage you are reading.
function FlowBackdrop({ stage, total }) {
  const p = total > 1 ? stage / (total - 1) : 0
  const dots = Array.from({ length: 26 }, (_, i) => ({
    left: (i * 37 + 11) % 100,
    size: 2 + (i % 3),
    dur: 16 + (i % 7) * 3,
    delay: -((i * 17) % 40),
    drift: ((i % 5) - 2) * 14,
  }))
  return (
    <div className="flow-backdrop" aria-hidden="true" style={{ '--p': p }}>
      <div className="flow-backdrop-glow" />
      {dots.map((d, i) => (
        <span key={i} className="flow-backdrop-dot"
              style={{ left: `${d.left}%`, width: d.size, height: d.size, animationDuration: `${d.dur}s`, animationDelay: `${d.delay}s`, '--drift': `${d.drift}px` }} />
      ))}
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
      <FlowBackdrop stage={activeIndex} total={FLOW_STEPS.length} />
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
              {i + 1}
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
                <span className="flow-scroll-step-num">{tr('Stufe', 'Stage')} {i + 1}</span>
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
function RealTicker({ events, homeTeam, awayTeam }) {
  if (!events || events.length === 0) return null
  let home = 0, away = 0
  const score = () => `${home}:${away}`
  const home_ = teamName(homeTeam), away_ = teamName(awayTeam)
  const halftime = () => ({ key: 'ht', minute: tr('HZ', 'HT'), type: 'halftime', head: `⏸️ ${tr('Halbzeit', 'Half time')}`,
                            text: tr(`${home_} ${score()} ${away_} zur Pause.`, `${home_} ${score()} ${away_} at the break.`, `${home_} ${score()} ${away_} na poluvremenu.`), score: score() })
  // Goals, cards and half time only: no kick-off or full-time rows.
  const rows = []
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
      rows.push({ key: i, minute: e.minute, type: 'goal', head: tr(`⚽ TOR für ${teamName(e.team)}!`, `⚽ GOAL for ${teamName(e.team)}!`, `⚽ GOL za ${teamName(e.team)}!`),
                  text: tr(`${e.player || 'Unbekannt'}${how} trifft zum ${score()}.`, `${e.player || 'Unknown'}${how} makes it ${score()}.`, `${e.player || 'Nepoznat igrač'}${how} postiže gol: ${score()}.`), score: score() })
    } else if (e.type === 'red_card') {
      rows.push({ key: i, minute: e.minute, type: 'chance', head: `🟥 ${tr('Rote Karte', 'Red card')} – ${teamName(e.team)}`,
                  text: tr(`${e.player || 'Ein Spieler'} fliegt vom Platz. ${teamName(e.team)} spielt zu zehnt weiter.`,
                           `${e.player || 'A player'} is sent off. ${teamName(e.team)} play on with ten men.`,
                           `${e.player || 'Igrač'} je isključen. ${teamName(e.team)} nastavlja s deset igrača.`), score: score() })
    } else if (e.type === 'yellow_card') {
      rows.push({ key: i, minute: e.minute, type: 'yellow', head: `🟨 ${tr('Gelbe Karte', 'Yellow card')} – ${teamName(e.team)}`,
                  text: tr(`${e.player || 'Ein Spieler'} sieht Gelb.`, `${e.player || 'A player'} is booked.`, `${e.player || 'Igrač'} dobija žuti karton.`), score: null })
    }
  })
  if (!halftimeShown) {
    rows.push(halftime())
  }

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
  const topScores = (sp.top_scorelines || []).slice(0, 3)

  const actualHome = result.home_score
  const actualAway = result.away_score
  const actualWinner = actualHome > actualAway ? 'H' : actualAway > actualHome ? 'A' : 'D'

  const homeCorrect = actualWinner === 'H'
  const drawCorrect = actualWinner === 'D'
  const awayCorrect = actualWinner === 'A'
  // The same team colours as the analysis before the match; the outcome that
  // happened is marked with a check, not recoloured.
  const matchColors = getMatchColors(aiData.home_team, aiData.away_team)

  return (
    <div className="ai-prediction-inner">

      {/* Winner probabilities */}
      <div className="probabilities-donut">
        <ResultDonut
          home={aiData.probability_home_win}
          draw={aiData.probability_draw}
          away={aiData.probability_away_win}
          score={`${actualHome}-${actualAway}`}
          colors={matchColors}
        />
        <div className="probabilities-legend">
          <span className="legend-title">{tr('Siegwahrscheinlichkeit', 'Win probability')}</span>
          <div className={`legend-row ${homeCorrect ? 'is-correct' : ''}`}>
            <span className="legend-dot" style={{ background: matchColors.home }} />
            <span className="legend-name"><TeamLabel name={aiData.home_team} />{homeCorrect && <span className="legend-check"> ✓</span>}</span>
            <span className="legend-value"><AnimatedNumber value={aiData.probability_home_win * 100} decimals={1} suffix="%" /></span>
          </div>
          <div className={`legend-row ${drawCorrect ? 'is-correct' : ''}`}>
            <span className="legend-dot gray" />
            <span className="legend-name">{tr('Remis', 'Draw')}{drawCorrect && <span className="legend-check"> ✓</span>}</span>
            <span className="legend-value"><AnimatedNumber value={aiData.probability_draw * 100} decimals={1} suffix="%" /></span>
          </div>
          <div className={`legend-row ${awayCorrect ? 'is-correct' : ''}`}>
            <span className="legend-dot" style={{ background: matchColors.away }} />
            <span className="legend-name"><TeamLabel name={aiData.away_team} />{awayCorrect && <span className="legend-check"> ✓</span>}</span>
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

        </div>
      )}

      <AiTipResult fixture={fixture} />
    </div>
  )
}

// How the AI tip of a finished match turned out (GET /ai-tip-result): the
// Wett-Tipp box, gold when it came in and dark grey when not, and below it
// every priced bet with whether it came in.
const RESULT_ROWS = 6

function AiTipResult({ fixture }) {
  const [data, setData] = useState(null)
  const [showAll, setShowAll] = useState(false)
  useEffect(() => {
    let alive = true
    axios.get(`${API_BASE}/ai-tip-result`, {
      params: { home_team: fixture.home_team, away_team: fixture.away_team, date: fixture.date },
    }).then(r => { if (alive) setData(r.data) }).catch(() => { if (alive) setData({ found: false }) })
    return () => { alive = false }
  }, [fixture.home_team, fixture.away_team, fixture.date])

  if (!data?.found || !data.tip) return null
  const tip = data.tip
  const hit = tip.result === 'win'
  const isTip = b => b.market === tip.market && b.outcome === tip.outcome && (b.team || null) === (tip.team || null)
  const rows = showAll ? data.bets : data.bets.slice(0, RESULT_ROWS)
  if (!showAll && !rows.some(isTip)) {
    const own = data.bets.find(isTip)
    if (own) rows.push(own)
  }

  const push = tip.result === 'push'
  return (
    // The Smart Bet card of the analysis in grey, its Wett-Tipp box gold when
    // the tip came in and dark grey when not.
    <div className="smart-bet-card ai-tip-result is-grey">
      <div className={`bet-tip ai-tip-result-head ${hit ? '' : 'is-empty is-miss'}`}>
        <span className="smart-bet-label bet-tip-label">{tr('Wett-Tipp', 'Bet tip')}</span>
        <div className="likely-tip-row">
          <span className="bet-tip-pick">{betOutcomeLabel(tip)}</span>
          {tip.best_odds && <span className="likely-tip-odds">{tip.best_odds.toFixed(2)}</span>}
          {tip.market_probability != null && <span className="likely-tip-chance">{pct(tip.market_probability)} {tr('Chance', 'chance')}</span>}
        </div>
        <div className="smart-bet-agree-row">
          <span className={`smart-bet-agree-chip ${hit ? 'yes' : 'muted'}`}>
            {hit ? tr('Wett-Tipp eingetroffen ✓', 'Bet tip won ✓')
              : push ? tr('Einsatz zurück', 'Stake returned')
              : tr('Wett-Tipp nicht eingetroffen ✕', 'Bet tip lost ✕')}
          </span>
        </div>
      </div>

      {data.bets.length > 0 && (
        <div className="smart-bet-table ai-tip-result-table">
          <div className="smart-bet-table-head">
            <span>{tr('Markt', 'Market')}</span>
            <span>{tr('Tipp', 'Pick')}</span>
            <span>{tr('Quote', 'Odds')}</span>
            <span>{tr('Ergebnis', 'Result')}</span>
          </div>
          {rows.map((b, i) => (
            <div key={i} className={`smart-bet-table-row ${b.result === 'win' ? 'is-won' : b.result === 'push' ? 'is-push' : 'is-lost'} ${isTip(b) ? 'is-ai-tip' : ''}`}>
              <span className="smart-bet-col-market">{marketGroupLabel(b.market)}</span>
              <span className="smart-bet-col-pick">{b.likely ? '🎯 ' : ''}{isTip(b) ? '✨ ' : ''}{betOutcomeLabel(b)}</span>
              <span className="smart-bet-col-odds">{b.best_odds.toFixed(2)}</span>
              <span className="smart-bet-col-chance">{b.result === 'win' ? '✓' : b.result === 'push' ? '↺' : '✕'}</span>
            </div>
          ))}
          {data.bets.length > RESULT_ROWS && (
            <button className="smart-bet-more" onClick={() => setShowAll(v => !v)}>
              {showAll ? tr('Weniger Märkte ▲', 'Fewer markets ▲') : tr(`Alle Märkte zeigen (${data.bets.length - RESULT_ROWS} weitere) ▼`, `Show all markets (${data.bets.length - RESULT_ROWS} more) ▼`, `Prikaži sva tržišta (još ${data.bets.length - RESULT_ROWS}) ▼`)}
            </button>
          )}
        </div>
      )}

    </div>
  )
}

function RealResultCard({ fixture, result, aiData, onGenerate, analysisActive, isLinked, onOpen, onCollapse }) {
  const [showAI, setShowAI] = useState(false)

  if (!isLinked) {
    return (
      <div className="fixture-row fixture-final" id={`match-${fixture.match_id}`}
           onClick={onOpen} role="button" tabIndex={0}>
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
    <div className="card wm-card" id={`match-${fixture.match_id}`}>
      <div className="wm-card-header">
        <span className="wm-match-id">{fixtureWhen(fixture)}</span>
        <div className="wm-card-header-right">
          <span className="wm-match-type" style={{ background: 'rgba(34,197,94,0.15)', color: '#4ade80' }}>{tr('Beendet', 'Full time')}</span>
          <button className="wm-collapse-btn" onClick={onCollapse}>{tr('Einklappen ▲', 'Collapse ▲')}</button>
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
      <RealTicker events={result.events} homeTeam={fixture.home_team} awayTeam={fixture.away_team} />

      {aiData && (
        <div className="ai-prediction-section">
          {/* Like the analysis: one centred button that opens the comparison and
              then goes away; the card collapses from its header. */}
          {showAI
            ? <AiComparisonPanel fixture={fixture} result={result} aiData={aiData} />
            : (
              <div className="ai-compare-cta">
                <button className="fixture-generate-btn" onClick={() => setShowAI(true)}>
                  {tr('Mit der KI-Prognose vergleichen', 'Compare with the AI prediction')}
                </button>
              </div>
            )}
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

// A single match day by its exact date ("Di 24.11.").
const WEEKDAYS_SHORT = {
  de: ['So', 'Mo', 'Di', 'Mi', 'Do', 'Fr', 'Sa'],
  en: ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat'],
  bs: ['Ned', 'Pon', 'Uto', 'Sri', 'Čet', 'Pet', 'Sub'],
}
function formatFixtureDay(date) {
  const [y, m, d] = date.split('-').map(Number)
  const weekday = WEEKDAYS_SHORT[LANG][new Date(Date.UTC(y, m - 1, d)).getUTCDay()]
  return LANG === 'en'
    ? `${weekday} ${d} ${['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'][m - 1]}`
    : `${weekday} ${String(d).padStart(2, '0')}.${String(m).padStart(2, '0')}.`
}

// The days with matches from today on (three weeks ahead), what the "Next
// games" dropdown lists after "Past games".
const berlinDay = new Intl.DateTimeFormat('sv-SE', { timeZone: 'Europe/Berlin' })
function upcomingFixtureDays(fixtures, now = new Date()) {
  const today = berlinDay.format(now)
  const last = berlinDay.format(new Date(now.getTime() + TAB_AHEAD_DAYS * 86400000))
  return [...new Set(fixtures.map(f => f.date).filter(d => d >= today && d <= last))].sort()
}

// The "Next games" tab as a dropdown: next games first, then every match day.
// The list is fixed-positioned so the tab bar's horizontal scroll cannot clip it.
function MatchdayPicker({ activeGroup, days, onSelect }) {
  const [open, setOpen] = useState(false)
  const [pos, setPos] = useState({ top: 0, left: 0, width: 260 })
  const wrap = useRef(null)
  const menu = useRef(null)
  useEffect(() => {
    if (!open) return
    const close = () => setOpen(false)
    // Scrolling the page closes the list; scrolling inside it must not.
    const onScroll = e => { if (!menu.current?.contains(e.target)) close() }
    const onDown = e => { if (!wrap.current?.contains(e.target)) close() }
    const onKey = e => { if (e.key === 'Escape') close() }
    document.addEventListener('mousedown', onDown)
    document.addEventListener('keydown', onKey)
    window.addEventListener('scroll', onScroll, true)
    window.addEventListener('resize', close)
    return () => {
      document.removeEventListener('mousedown', onDown)
      document.removeEventListener('keydown', onKey)
      window.removeEventListener('scroll', onScroll, true)
      window.removeEventListener('resize', close)
    }
  }, [open])
  function toggle() {
    if (!open && wrap.current) {
      const r = wrap.current.getBoundingClientRect()
      const width = Math.min(280, window.innerWidth - 32)
      setPos({ top: r.bottom + 8, left: Math.max(16, Math.min(r.left, window.innerWidth - width - 16)), width })
    }
    setOpen(o => !o)
  }
  function pick(group) { setOpen(false); onSelect(group) }
  const activeDay = activeGroup.startsWith('day:') ? activeGroup.slice(4) : null
  const active = activeGroup === 'next' || activeGroup === 'past' || activeDay !== null
  return (
    <div className="group-picker" ref={wrap}>
      <button role="tab" aria-selected={active} aria-haspopup="listbox" aria-expanded={open}
              className={`group-segment group-picker-btn ${active ? 'active' : ''}`} onClick={toggle}>
        <span>📅 {activeDay ? formatFixtureDay(activeDay) : activeGroup === 'past' ? tr('Vergangene Spiele', 'Past games') : tr('Nächste Spiele', 'Next games')}</span>
        <span className={`group-picker-caret ${open ? 'open' : ''}`}>▾</span>
      </button>
      {open && (
        <ul className="group-picker-menu" role="listbox" ref={menu} style={{ top: pos.top, left: pos.left, width: pos.width }}>
          <li>
            <button role="option" aria-selected={activeGroup === 'next'}
                    className={`group-picker-item ${activeGroup === 'next' ? 'selected' : ''}`}
                    onClick={() => pick('next')}>{tr('Nächste Spiele', 'Next games')}</button>
          </li>
          <li>
            <button role="option" aria-selected={activeGroup === 'past'}
                    className={`group-picker-item ${activeGroup === 'past' ? 'selected' : ''}`}
                    onClick={() => pick('past')}>{tr('Vergangene Spiele', 'Past games')}</button>
          </li>
          {days.length > 0 && <li className="group-picker-divider" role="separator" />}
          {days.map(day => (
            <li key={day}>
              <button role="option" aria-selected={activeDay === day}
                      className={`group-picker-item ${activeDay === day ? 'selected' : ''}`}
                      onClick={() => pick(`day:${day}`)}>{formatFixtureDay(day)}</button>
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}

// Tab title and canonical link follow the page that is shown.
function useDocumentTitle(title, route) {
  useEffect(() => {
    document.title = title
    const canonical = document.querySelector('link[rel="canonical"]')
    if (canonical) canonical.href = `https://goaliq.de${window.location.pathname}`
  }, [title, route])
}

export default function App() {
  const [route, navigate] = useSiteRoute()
  const page = route.page
  // The page's language; LANG (module level) is what tr() reads, this state
  // only makes React redraw everything when it changes.
  const [lang, setLang] = useState(LANG)
  function switchLang(next) {
    LANG = next
    try { localStorage.setItem('goaliq-lang', next) } catch { /* private mode */ }
    document.documentElement.lang = next
    setLang(next)
  }
  useEffect(() => {
    document.documentElement.lang = LANG
  }, [])
  const [predictionsById, setPredictionsById] = useState({})
  // The landing page's counted numbers (GET /site-stats).
  const [siteStats, setSiteStats] = useState(null)
  const [realResultsMap, setRealResultsMap] = useState({})
  const [realResults, setRealResults] = useState([])
  // null until someone picks a competition: the ticker then shows a mix.
  const tickerCompetition = route.competition && route.competition !== 'all' ? route.competition : null
  const [wmLoading, setWmLoading] = useState(true)
  const activeCompetition = route.competition || 'cl'
  const isAll = activeCompetition === 'all'
  const competitionKeys = isAll ? Object.keys(COMPETITIONS) : [activeCompetition]
  const [, setFixturesVersion] = useState(0)
  const [fixtureNow, setFixtureNow] = useState(() => new Date())
  useEffect(() => {
    const refreshClock = () => setFixtureNow(new Date())
    const timer = setInterval(refreshClock, 60000)
    window.addEventListener('focus', refreshClock)
    return () => { clearInterval(timer); window.removeEventListener('focus', refreshClock) }
  }, [])
  const [analysisStep, setAnalysisStep] = useState({})
  const [combos, setCombos] = useState({})
  const comboCache = useRef({})
  const comboRequests = useRef(new Set())

  const [pastMore, setPastMore] = useState({ key: '', n: 20 })
  const competition = isAll ? null : COMPETITIONS[activeCompetition]
  const currentFixtures = isAll ? competitionKeys.flatMap(k => COMPETITIONS[k].fixtures) : competition.fixtures
  const linkedFixture = route.matchId ? currentFixtures.find(f => f.match_id === route.matchId && f.date === route.matchDate) : null
  // A view is next games, top games, the combo ticket or one day; an opened
  // match in a single league shows its own day.
  const isView = g => ['next', 'hot', 'combo', 'past'].includes(g) || (typeof g === 'string' && g.startsWith('day:'))
  const activeGroup = isAll
    ? (isView(route.group) ? route.group : 'next')
    : (linkedFixture ? `day:${linkedFixture.date}` : route.group || 'next')
  const activeDay = activeGroup.startsWith('day:') ? activeGroup.slice(4) : null
  const comboFor = key => comboCacheIsCurrent(combos[key], fixtureNow.getTime()) ? combos[key].data : null
  const comboExpiry = activeGroup === 'combo' ? Math.min(...competitionKeys.map(k => combos[k]?.expiresAt ?? Infinity)) : Infinity
  const currentDays = upcomingFixtureDays(currentFixtures, fixtureNow)
  // Past games, newest first, shown 20 at a time.
  const pastFixtures = activeGroup === 'past'
    ? currentFixtures.filter(f => fixtureDateTime(f) < fixtureNow).sort((a, b) => fixtureDateTime(b) - fixtureDateTime(a))
    : []
  const pastShown = pastMore.key === activeCompetition ? pastMore.n : 20
  const nextGames = isAll
    ? competitionKeys.flatMap(k => nextGamesFor(COMPETITIONS[k].fixtures, fixtureNow))
        .sort((a, b) => fixtureDateTime(a) - fixtureDateTime(b))
    : nextGamesFor(currentFixtures, fixtureNow)
  const leagueOf = fixture => Object.keys(COMPETITIONS).find(k => COMPETITIONS[k].fixtures.includes(fixture))

  const pageLabel = isAll ? tr('Prognosen', 'Predictions') : competition.label
  const titleSuffix = linkedFixture ? `${teamName(linkedFixture.home_team)} – ${teamName(linkedFixture.away_team)}`
    : page === 'how-it-works' ? tr('So funktioniert’s', 'How it works')
    : page === 'home' ? pageLabel : ''
  useDocumentTitle(titleSuffix
    ? `${titleSuffix} | GoalIQ`
    : tr('GoalIQ – KI-Prognosen für jedes Spiel', 'GoalIQ – AI predictions for every match'), route)

  useEffect(() => {
    if (wmLoading) return
    if (route.matchId) document.getElementById(`match-${route.matchId}`)?.scrollIntoView({ block: 'start' })
    else if (window.location.hash === '#predictions') document.getElementById('predictions')?.scrollIntoView()
  }, [route, wmLoading, linkedFixture])

  useEffect(() => {
    if (activeGroup !== 'combo') return
    const keys = activeCompetition === 'all' ? Object.keys(COMPETITIONS) : [activeCompetition]
    keys.forEach(key => {
      if (comboRequests.current.has(key) || comboCacheIsCurrent(comboCache.current[key], Date.now())) return
      comboRequests.current.add(key)
      axios.get(`${API_BASE}/combo-ticket`, { params: { competition: COMPETITIONS[key].sportKey } })
        .then(r => {
          const entry = createComboCacheEntry(r.data, Date.now())
          comboCache.current[key] = entry
          setCombos(prev => ({ ...prev, [key]: entry }))
        })
        .catch(() => {
          const entry = createComboCacheEntry({ error: true }, Date.now())
          comboCache.current[key] = entry
          setCombos(prev => ({ ...prev, [key]: entry }))
        })
        .finally(() => comboRequests.current.delete(key))
    })
  }, [activeCompetition, activeGroup, fixtureNow])

  useEffect(() => {
    const delay = comboExpiry - Date.now()
    if (!Number.isFinite(delay) || delay <= 0) return
    const timer = setTimeout(() => setFixtureNow(new Date()), delay + 1)
    return () => clearTimeout(timer)
  }, [comboExpiry])

  // Changing the league keeps the chosen view (next / top games / combo).
  const keepGroup = ['hot', 'combo', 'past'].includes(activeGroup) ? activeGroup : 'next'

  function switchCompetition(key, group = 'next') {
    navigate(sectionPath(key, group))
  }

  // Opens a competition at its next matchday and scrolls to it (the hero
  // button: Champions League, the landing card: Bundesliga).
  function openNextMatchday(key) {
    const now = new Date()
    const fixtures = COMPETITIONS[key].fixtures
    const next = COMPETITIONS[key].groups.find(g =>
      fixtures.some(f => f.group === g && fixtureDateTime(f) >= now))
    switchCompetition(key, next || 'next')
    setTimeout(() => document.getElementById('predictions')?.scrollIntoView({ behavior: 'smooth', block: 'start' }), 80)
  }
  const openNextChampionsLeague = () => openNextMatchday('cl')

  function startAnalysis(matchId, fixture) {
    const selected = fixture || currentFixtures.find(f => f.match_id === matchId)
    if (selected) navigate(matchPath(activeCompetition, selected))
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
    if (route.matchId === matchId) navigate(sectionPath(activeCompetition, activeGroup))
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
    navigate(matchPath(key, fixture))
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
    navigate(matchPath(activeCompetition, fixture))
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
    navigate(matchPath(activeCompetition, fixture))
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
        const [listResp, resultsResp] = await Promise.allSettled([
          axios.get(`${API_BASE}/predictions`),
          axios.get(`${API_BASE}/real-results`),
        ])
        // The results come first: the ticker should not wait for every prediction.
        if (resultsResp.status === 'fulfilled') {
          const results = resultsResp.value.data.results || []
          setRealResultsMap(buildRealResultsMap(results))
          setRealResults(results)
        }
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
          <a href={`${sectionPath('all')}#predictions`} onClick={(e) => { e.preventDefault(); navigate(`${sectionPath('all')}#predictions`) }}>{tr('Prognosen', 'Predictions')}</a>
          <a href="/so-funktionierts" onClick={(e) => { e.preventDefault(); navigate('/so-funktionierts'); window.scrollTo(0, 0) }}>{tr("So funktioniert's", 'How it works')}</a>
        </div>
        <LanguageSwitch lang={lang} onChange={switchLang} />
      </nav>

      {(page === 'home' || page === 'landing') && <MatchTicker results={realResults} competitionKey={tickerCompetition} />}

      {page === 'landing' && (
        <>
          <header className="hero">
            <HeroVisual />
            <div className="hero-grid">
              <div className="hero-content">
                <h1>{tr('KI-Prognosen für jedes Spiel', 'AI predictions for every match')}</h1>
                <p>
                  {/* The full text on a desktop, a short version on phones and small tablets. */}
                  <span className="hero-text-full">
                    {tr('Ein KI-Modell, trainiert auf tausenden Spielen, rechnet jede Partie durch: Siegchancen, wahrscheinlichstes Ergebnis und Spielverlauf. Nach dem Abpfiff zeigen wir ehrlich, ob die KI richtig lag.',
                        'An AI model trained on thousands of matches works through every game: win chances, most likely score and game flow. After the final whistle we show honestly whether the AI got it right.')}
                  </span>
                  <span className="hero-text-short">
                    {tr('Die KI rechnet jedes Spiel durch. Nach dem Abpfiff zeigen wir ehrlich, ob sie richtig lag.',
                        'Our AI works through every match. After the final whistle we show honestly whether it was right.')}
                  </span>
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
                    <span className="hero-stat-value">
                      {`${Math.round((siteStats?.hit_rate?.rate ?? DEFAULT_HIT_RATE) * 100)} %`}
                    </span>
                    <span className="hero-stat-label">{tr('Trefferquote Wett-Tipp', 'Hit rate of the main tip')}</span>
                  </div>
                </div>
              </div>
              <AppDemo onStart={() => navigate(sectionPath('all'))} />
            </div>
          </header>
        </>
      )}

      {page === 'home' && (
        <>
          <main className="main">
            <section id="predictions" className="wm-section">
              <h2 className="section-title">{tr('Prognosen', 'Predictions')}</h2>

              <div className="competition-select" role="group" aria-label={tr("Nach Liga filtern", "Filter by league")}>
                <button
                  className={`competition-pill ${isAll ? 'active' : ''}`}
                  onClick={() => switchCompetition('all', keepGroup)}
                >
                  {tr('Alle', 'All')}
                </button>
                {Object.entries(COMPETITIONS).map(([key, c]) => (
                  <button
                    key={key}
                    className={`competition-pill ${activeCompetition === key ? 'active' : ''}`}
                    onClick={() => switchCompetition(key, keepGroup)}
                  >
                    {c.logo
                      ? <img src={c.logo} alt="" />
                      : <Emoji char={c.emoji} className="competition-pill-emoji" />}
                    {c.label}
                  </button>
                ))}
                <button className="competition-pill soon" disabled title={tr('Bald verfügbar', 'Coming soon')}>
                  <Emoji char={FLAG_ENGLAND} className="competition-pill-emoji" />
                  Premier League
                  <span className="competition-pill-soon">{tr('Bald', 'Soon')}</span>
                </button>
                <button className="competition-pill soon" disabled title={tr('Bald verfügbar', 'Coming soon')}>
                  <Emoji char={FLAG_SPAIN} className="competition-pill-emoji" />
                  La Liga
                  <span className="competition-pill-soon">{tr('Bald', 'Soon')}</span>
                </button>
              </div>

              <div className="group-nav">
                <div className="group-segments" role="tablist">
                  {/* "Next games" opens a list: next games, past games, then the match days
                      around today. Between matchdays (Nations League) there are no upcoming
                      days, but the past games must stay reachable. */}
                  <MatchdayPicker
                    activeGroup={activeGroup}
                    days={currentDays}
                    onSelect={group => navigate(sectionPath(activeCompetition, group))}
                  />
                  <button role="tab" aria-selected={activeGroup === 'hot'}
                          className={`group-segment ${activeGroup === 'hot' ? 'active' : ''}`}
                          onClick={() => navigate(sectionPath(activeCompetition, 'hot'))}>🔥 {tr('Topspiele', 'Top games')}</button>
                  <button role="tab" aria-selected={activeGroup === 'combo'}
                          className={`group-segment ${activeGroup === 'combo' ? 'active' : ''}`}
                          onClick={() => navigate(sectionPath(activeCompetition, 'combo'))}>
                    🎟️ {tr('Kombi-Schein', 'Combo ticket')}</button>
                </div>
              </div>

              {wmLoading && (
                <div className="analyzing-status loading-inline">
                  <span className="analyzing-spinner" />
                  <span>{tr('Analysen werden geladen…', 'Loading analyses…')}</span>
                </div>
              )}

              {activeGroup === 'combo' && (() => {
                // On "All" only the leagues that have a ticket (or are still loading)
                // are listed; the empty and failed ones stay out. A single league always shows its own view.
                const hasTicket = c => !!c?.days?.some(d => (d.by_size || []).some(o => o.ticket))
                const listed = isAll
                  ? competitionKeys.filter(k => { const c = comboFor(k); return c === null || hasTicket(c) })
                  : competitionKeys
                if (isAll && listed.length === 0) {
                  const reason = competitionKeys.map(comboFor).find(c => c?.reason)?.reason
                  return (
                    <div className="combo-view">
                      <p className="smart-bet-notip">
                        <strong>{tr('Heute kein Kombi-Schein.', 'No combo ticket today.')}</strong>
                        {reason && <><br />{tr(reason, 'No same-day ticket passes all checks.', 'Nijedan tiket za isti dan ne prolazi sve provjere.')}</>}
                      </p>
                      <ComboLegend />
                    </div>
                  )
                }
                return <>
                  {listed.map(key => (
                  <div key={key}>
                    {isAll && <h3 className="fixture-league-tag combo-league-title">{COMPETITIONS[key].label}</h3>}
                    <ComboTicketView combo={comboFor(key)} loading={comboFor(key) === null} onOpenLeg={openLeg} sportKey={COMPETITIONS[key].sportKey} />
                  </div>
                  ))}
                </>
              })()}

              {activeGroup === 'next' && nextGames.length === 0 && (
                <p className="wm-subtle">{tr('Noch keine weiteren Spieltermine verfügbar.', 'No further fixtures available yet.')}</p>
              )}

              {activeGroup === 'past' && pastFixtures.length === 0 && (
                <p className="wm-subtle">{tr('Noch keine vergangenen Spiele.', 'No past games yet.')}</p>
              )}

              {activeGroup === 'hot' && nextGames.length === 0 && (
                <p className="wm-subtle">{tr('Noch keine weiteren Spieltermine verfügbar.', 'No further fixtures available yet.')}</p>
              )}


              <div className="fixtures-list">
                {route.matchId && !linkedFixture && !wmLoading && (
                  <p className="wm-subtle">{tr('Dieses Spiel ist nicht mehr im aktuellen Spielplan verfügbar.', 'This match is no longer available in the current schedule.')}</p>
                )}
                {(() => {
                  let fixtures
                  if (activeGroup === 'next') {
                    fixtures = nextGames
                  } else if (activeGroup === 'hot') {
                    fixtures = getHotFixtures(predictionsById, nextGames)
                  } else if (activeGroup === 'past') {
                    fixtures = pastFixtures.slice(0, pastShown)
                  } else if (activeDay) {
                    fixtures = currentFixtures.filter(f => f.date === activeDay)
                      .sort((a, b) => fixtureDateTime(a) - fixtureDateTime(b))
                  } else {
                    fixtures = currentFixtures.filter(f => f.group === activeGroup)
                  }
                  if (isAll && linkedFixture && !fixtures.includes(linkedFixture)) fixtures = [linkedFixture, ...fixtures]
                  const renderFixture = fixture => {
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
                          analysisActive={linkedFixture === fixture}
                          isLinked={linkedFixture === fixture}
                          onOpen={() => navigate(matchPath(activeCompetition, fixture))}
                          onCollapse={() => navigate(sectionPath(activeCompetition, activeGroup))}
                        />
                      )
                    }

                    if (!aiData) {
                      return <FixtureRow key={fixture.match_id} fixture={fixture} />
                    }
                    const step = linkedFixture === fixture ? (analysisStep[fixture.match_id] ?? Infinity) : undefined
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
                        currentTime={fixtureNow.getTime()}
                        onStartBetCheck={() => startBetCheck(fixture.match_id, fixture)}
                      />
                    )
                  }
                  // Which league (all leagues) and, for past games, which day.
                  const tagFor = fixture => [
                    activeGroup === 'past' ? formatFixtureDay(fixture.date) : null,
                    isAll ? COMPETITIONS[leagueOf(fixture)]?.label : null,
                  ].filter(Boolean).join(' · ')
                  return fixtures.map(fixture => tagFor(fixture) ? (
                    <Fragment key={fixture.match_id}>
                      <span className="fixture-league-tag">{tagFor(fixture)}</span>
                      {renderFixture(fixture)}
                    </Fragment>
                  ) : renderFixture(fixture))
                })()}
              </div>
              {activeGroup === 'past' && pastFixtures.length > pastShown && (
                <button className="past-more" onClick={() => setPastMore({ key: activeCompetition, n: pastShown + 20 })}>
                  {tr('Mehr anzeigen', 'Show more')}
                </button>
              )}
            </section>
          </main>
        </>
      )}

      {page === 'how-it-works' && (
        <main className="main flow-main">
          <AnalysisFlowPage onBack={() => navigate(sectionPath(activeCompetition))} />
        </main>
      )}

      {page === 'not-found' && <main className="main flow-main"><p>{tr('Diese Seite wurde nicht gefunden.', 'This page was not found.')}</p><a href="/">{tr('Zur Startseite', 'Back to home')}</a></main>}

      <footer className="footer">
        <p>GoalIQ – {tr('KI-Prognosen, nur zur Unterhaltung. Keine Wettberatung.', 'AI predictions, for entertainment only. Not betting advice.')} · <a href="mailto:kontakt@goaliq.de">kontakt@goaliq.de</a></p>
      </footer>
    </div>
  )
}
