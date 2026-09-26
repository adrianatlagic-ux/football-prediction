import { useState, useEffect, useRef } from 'react'
import axios from 'axios'
import './App.css'
import CL_FIXTURES from './cl_fixtures.json'
import BL_FIXTURES from './bl_fixtures.json'
import NL_FIXTURES from './nl_fixtures.json'
import CLUB_CRESTS from './club_crests.json'
import TEAM_COLORS from './team_colors.json'

const API_BASE = import.meta.env.DEV ? 'http://127.0.0.1:8000' : ''
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
        {name}
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
        {name}
      </>
    )
  }
  const flag = TEAM_FLAGS[name]
  return <>{flag && <span style={{ marginRight: '0.4em' }}>{flag}</span>}{name}</>
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

  return <>{display.toFixed(decimals)}{suffix}</>
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
        {animate ? <AnimatedNumber value={value * 100} decimals={1} suffix="%" /> : `${(value * 100).toFixed(1)}%`}
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
  const terms = [home, away, '2+ goals', '3+ goals', 'high-scoring game', 'low-scoring game']
  const escaped = terms.map(t => t.replace(/[.*+?^${}()|[\]\\]/g, '\\$&'))
  // Also highlight standalone numbers - win rates, probabilities, scorelines
  // (e.g. "94%", "55%", "0:1") - these are the figures a reader actually
  // scans for, same treatment as the highlighted numbers in the other boxes.
  const numberPattern = String.raw`\d+(?:\.\d+)?%|\d+:\d+`
  const parts = text.split(new RegExp(`(${escaped.join('|')}|${numberPattern})`, 'g'))
  return parts.map((part, i) =>
    terms.includes(part)
      ? <span className="scenario-highlight" key={i}>{part}</span>
      : /^(\d+(?:\.\d+)?%|\d+:\d+)$/.test(part)
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

  return (
    <div className="form-rating-box">
      <h4>Form Rating</h4>

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
          <div className="form-tug-fill-home" style={{ width: `${homePct}%` }} />
          <div className="form-tug-fill-away" style={{ width: `${awayPct}%` }} />
        </div>
        <div className="form-tug-values">
          <span className="form-tug-value home">{homeRating}</span>
          <span className="form-tug-value away">{awayRating}</span>
        </div>
      </div>

      <p className="form-rating-detail">
        <strong><TeamLabel name={home} /></strong> — {explanation.form_last_10_avg_pts[home]} pts/game &middot; {explanation.avg_goals_scored[home]} scored &middot; {explanation.avg_goals_conceded[home]} conceded &middot; {explanation.clean_sheet_rate[home]} clean sheets
      </p>
      <p className="form-rating-detail">
        <strong><TeamLabel name={away} /></strong> — {explanation.form_last_10_avg_pts[away]} pts/game &middot; {explanation.avg_goals_scored[away]} scored &middot; {explanation.avg_goals_conceded[away]} conceded &middot; {explanation.clean_sheet_rate[away]} clean sheets
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
        <h4>Most Likely Scenario</h4>
        <p>{renderScenario(bm.scenario, home, away)}</p>
      </div>

      <FormRating data={data} />
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
            <h4>Double Chance</h4>
            <div className="market-grid">
              <div className={`market-card market-card-fillable${dc.home_or_draw === dcMax ? ' is-leader' : ''}`}>
                <AnimatedBarFill className="market-card-fill" targetPct={dc.home_or_draw * 100} />
                <div className="market-card-content">
                  <div className="market-card-label"><TeamLabel name={home} /> or Draw</div>
                  <div className="market-card-value"><AnimatedNumber value={dc.home_or_draw * 100} decimals={1} suffix="%" /></div>
                </div>
              </div>
              <div className={`market-card market-card-fillable${dc.home_or_away === dcMax ? ' is-leader' : ''}`}>
                <AnimatedBarFill className="market-card-fill" targetPct={dc.home_or_away * 100} />
                <div className="market-card-content">
                  <div className="market-card-label"><TeamLabel name={home} /> or <TeamLabel name={away} /></div>
                  <div className="market-card-value"><AnimatedNumber value={dc.home_or_away * 100} decimals={1} suffix="%" /></div>
                </div>
              </div>
              <div className={`market-card market-card-fillable${dc.draw_or_away === dcMax ? ' is-leader' : ''}`}>
                <AnimatedBarFill className="market-card-fill" targetPct={dc.draw_or_away * 100} />
                <div className="market-card-content">
                  <div className="market-card-label">Draw or <TeamLabel name={away} /></div>
                  <div className="market-card-value"><AnimatedNumber value={dc.draw_or_away * 100} decimals={1} suffix="%" /></div>
                </div>
              </div>
            </div>
          </div>
        )
      })()}

      <div>
        <h4>Total Goals (Over / Under)</h4>
        {ou.map(o => (
          <div className="over-under-row" key={o.line}>
            <span className="over-under-line">{o.line}</span>
            <div className="over-under-track">
              <AnimatedBarFill className="over-under-fill" targetPct={o.over * 100} />
            </div>
            <span className="over-under-value">over <AnimatedNumber value={o.over * 100} decimals={1} suffix="%" /></span>
          </div>
        ))}
      </div>

      <div className="market-card btts-card">
        <div className="market-card-label">Both Teams to Score</div>
        <div className="btts-split">
          <div className="btts-half">
            <div className="market-card-value"><AnimatedNumber value={btts.yes * 100} decimals={1} suffix="%" /></div>
            <div className="market-card-sub">Yes</div>
          </div>
          <div className="btts-half">
            <div className="market-card-value"><AnimatedNumber value={btts.no * 100} decimals={1} suffix="%" /></div>
            <div className="market-card-sub">No</div>
          </div>
        </div>
      </div>

      <div>
        <h4>If <TeamLabel name={favorite} /> win (<AnimatedNumber value={margin1 * 100} decimals={1} suffix="%" />) — by how much?</h4>
        <div className="market-grid">
          <div className="market-card">
            <div className="market-card-label">1+ goal</div>
            <div className="market-card-value"><AnimatedNumber value={margin1 * 100} decimals={1} suffix="%" /></div>
          </div>
          <div className="market-card">
            <div className="market-card-label">2+ goals</div>
            <div className="market-card-value"><AnimatedNumber value={margin2 * 100} decimals={1} suffix="%" /></div>
          </div>
          <div className="market-card">
            <div className="market-card-label">3+ goals</div>
            <div className="market-card-value"><AnimatedNumber value={margin3 * 100} decimals={1} suffix="%" /></div>
          </div>
        </div>
      </div>
    </div>
  )
}

function betPercent(value, signed = false) {
  return Number.isFinite(value) ? `${signed && value > 0 ? '+' : ''}${(value * 100).toFixed(1)}%` : '—'
}

function BetMetric({ label, value, detail, emphasis = false }) {
  return (
    <div className={`bet-metric${emphasis ? ' is-emphasized' : ''}`}>
      <dt>{label}</dt>
      <dd>{value}<small>{detail}</small></dd>
    </div>
  )
}

function ComboLegRow({ leg, index }) {
  return (
    <div className="combo-leg">
      <span className="combo-leg-num">{index + 1}</span>
      <div className="combo-leg-body">
        <div className="combo-leg-match">
          <TeamLabel name={leg.home_team} /> <span className="combo-leg-vs">vs</span> <TeamLabel name={leg.away_team} />
        </div>
        <div className="combo-leg-pick">{plainBetPhrase(leg)}</div>
        <div className="combo-leg-meta">
          {marketGroupLabel(leg.market)} · {leg.bookmaker}
        </div>
      </div>
      <div className="combo-leg-numbers">
        <span className="combo-leg-odds">{leg.best_odds.toFixed(2)}</span>
        <span className="combo-leg-prob">{betPercent(leg.probability)} model</span>
      </div>
    </div>
  )
}

function ComboTicketCard({ ticket, primary }) {
  return (
    <div className={`combo-ticket ${primary ? 'is-primary' : ''}`}>
      <div className="combo-ticket-head">
        <span className="combo-ticket-legs">{ticket.leg_count}-fold · {ticket.bookmaker}</span>
        <div className="combo-quote">
          <span className="combo-quote-label">Estimated combined odds</span>
          <span className="combo-ticket-odds">{ticket.combined_odds.toFixed(2)}</span>
        </div>
      </div>
      <div className="combo-legs">
        {ticket.legs.map((leg, i) => <ComboLegRow key={i} leg={leg} index={i} />)}
      </div>
      <dl className="bet-metrics probability-metrics">
        <BetMetric label="Chance all of them land" value={betPercent(ticket.conservative_probability)}
                   detail="By the market's prices, margin removed" emphasis />
        <BetMetric label="Our model on its own" value={betPercent(ticket.probability)} detail="Before checking against the price" />
      </dl>
      <dl className="bet-metrics decision-metrics">
        <BetMetric label="Profit per 1 staked" value={ticket.returns_per_unit.toFixed(2)} detail="If every selection wins" />
      </dl>
      {primary && (
        <p className="combo-ticket-note">
          Probabilities assume the results are independent of one another. Prices come
          from {ticket.bookmaker}'s individual markets; the combined offer itself has
          not been checked. This is not a bet we expect to profit from — it is the
          likeliest ticket that at least doubles a stake.
        </p>
      )}
    </div>
  )
}

// A combo of the day's price tips: every leg is a bet where bet-at-home pays
// more than Pinnacle's fair price, so the edges multiply.
function PriceTipComboCard({ ticket }) {
  return (
    <div className="combo-ticket is-primary price-tip-combo">
      <div className="combo-ticket-head">
        <span className="combo-ticket-legs">💰 {ticket.leg_count}-fold · bet-at-home</span>
        <div className="combo-quote">
          <span className="combo-quote-label">Combined odds</span>
          <span className="combo-ticket-odds">{ticket.combined_odds.toFixed(2)}</span>
        </div>
      </div>
      <div className="combo-legs">
        {ticket.legs.map((leg, i) => (
          <div className="combo-leg" key={i}>
            <span className="combo-leg-num">{i + 1}</span>
            <div className="combo-leg-body">
              <div className="combo-leg-match">
                <TeamLabel name={leg.home_team} /> <span className="combo-leg-vs">vs</span> <TeamLabel name={leg.away_team} />
              </div>
              <div className="combo-leg-pick">{betOutcomeLabel(leg)}</div>
              <div className="combo-leg-meta">{marketGroupLabel(leg.market)} · fair {leg.fair_odds.toFixed(2)} · edge {(leg.edge * 100).toFixed(1)}%</div>
            </div>
            <div className="combo-leg-numbers">
              <span className="combo-leg-odds">{leg.book_odds.toFixed(2)}</span>
              <span className="combo-leg-prob">{betPercent(leg.probability)} Pinnacle</span>
            </div>
          </div>
        ))}
      </div>
      <dl className="bet-metrics probability-metrics">
        <BetMetric label="Chance all of them land" value={betPercent(ticket.probability)} detail="By Pinnacle's fair prices" emphasis />
        <BetMetric label="Edge" value={`${ticket.edge >= 0 ? '+' : ''}${(ticket.edge * 100).toFixed(1)}%`} detail="Per 1 staked, on average over many tickets" />
      </dl>
      <p className="combo-ticket-note">
        Only price tips, all read in the hour before kickoff. Results are assumed independent;
        the combined offer at bet-at-home has not been checked. An edge is an average, not a promise for this ticket.
      </p>
    </div>
  )
}

function ComboTicketView({ combo, loading }) {
  if (loading) {
    return (
      <div className="analyzing-status loading-inline">
        <span className="analyzing-spinner" />
        <span>Building combinations…</span>
      </div>
    )
  }
  if (!combo) return null
  if (combo.error) {
    return <p className="wm-subtle">Combo suggestion unavailable right now (no current odds).</p>
  }

  return (
    <div className="combo-view">
      {combo.price_tip_combos?.length > 0 && (
        <div className="combo-day">
          <span className="combo-section-label">💰 Price tip combo</span>
          {combo.price_tip_combos.map(t => <PriceTipComboCard key={t.date} ticket={t} />)}
        </div>
      )}

      <p className="best-bets-intro">
        Every selection must win. All prices are <strong>bet-at-home's</strong>; each ticket uses <strong>one matchday</strong>
        {' '}and at most one selection per match. Selections favour outcomes rated likely by
        both the model and the market. Only win-or-lose markets are combined;
        quarter lines are excluded. Compare the best available 2-, 3- and 4-fold for each day.
      </p>

      {!combo.recommended && (
        <p className="smart-bet-notip">
          <strong>No combo ticket today.</strong><br />
          {combo.reason}
        </p>
      )}

      {combo.days?.map(day => (
        <div className="combo-day" key={day.date}>
          <span className="combo-section-label">
            {new Date(day.date + 'T12:00:00').toLocaleDateString('en-GB', { weekday: 'long', day: 'numeric', month: 'short' })}
            {' · '}{day.eligible_legs} eligible {day.eligible_legs === 1 ? 'match' : 'matches'}
          </span>

          <div className="combo-size-grid">
            {(day.by_size || []).map(option => (
              <section className="combo-size-option" key={option.leg_count}
                       aria-label={`${option.leg_count}-fold combo`}>
                <h3 className="combo-size-title">{option.leg_count}-fold combo</h3>
                {option.ticket ? (
                  <ComboTicketCard ticket={option.ticket} />
                ) : (
                  <div className="combo-size-empty">
                    <strong>Not available</strong>
                    <p>{option.reason}</p>
                  </div>
                )}
              </section>
            ))}
          </div>
        </div>
      ))}

      <p className="smart-bet-finePrint">
        Ranked by the lower of the model and market estimates for each selection.
        Probabilities assume independent results; combined odds are calculated from individual
        prices and have not been verified as a bookmaker ticket. A higher estimated hit rate
        does not establish profitability.
        Tickets can overlap and should not be treated as independent bets.
      </p>
    </div>
  )
}

function FixtureRow({ fixture }) {
  const opens = predictionOpensAt(fixture)
  const label = opens > new Date()
    ? `Analysis from ${opens.toLocaleDateString('en-GB', { weekday: 'short', day: 'numeric', month: 'short' })}`
    : 'Analysis pending'
  return (
    <div className="fixture-row fixture-pending">
      <div className="fixture-meta">
        <span className="fixture-date">{fixture.date} · {fixture.time}</span>
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

function FixtureReadyRow({ fixture, onGenerate }) {
  return (
    <div className="fixture-row fixture-ready">
      <div className="fixture-meta">
        <span className="fixture-date">{fixture.date} · {fixture.time}</span>
        <span className="fixture-ready-badge">Analysis ready</span>
      </div>
      <div className="fixture-teams">
        <span><TeamLabel name={fixture.home_team} /></span>
        <span className="fixture-vs">vs</span>
        <span><TeamLabel name={fixture.away_team} /></span>
      </div>
      <button className="fixture-generate-btn" onClick={onGenerate}>
        Generate AI Analysis
      </button>
    </div>
  )
}

const ANALYZING_STEPS = [
  'Reading current match data…',
  'Analyzing FIFA ranking, form & head-to-head…',
  'Calculating win/draw/loss probabilities…',
  'Computing betting markets & odds…',
  'Simulating most likely scorelines…',
  'Generating match flow & ticker…',
]

const BET_STEPS = [
  'Loading current odds…',
  'Comparing with model probabilities…',
  'Calculating expected value…',
  'Finding the best bet…',
]

function betOutcomeLabel(b) {
  if (b.market === 'Handicap +0.5') return <><TeamLabel name={b.team} /> or Draw</>
  if (b.market === 'Handicap 0.0') return <><TeamLabel name={b.team} /> (Draw No Bet)</>
  if (b.outcome === 'handicap') return <>{b.market.replace('Handicap ', '')} <TeamLabel name={b.team} /></>
  if (b.outcome === 'home_win' || b.outcome === 'away_win') return <>Win <TeamLabel name={b.team} /></>
  if (b.team) return <TeamLabel name={b.team} />
  if (b.outcome === 'draw') return 'Draw'
  if (b.market === 'BTTS') return `Both score: ${b.outcome}`
  if (b.outcome === 'Over') return `Over ${b.market.replace('Over/Under ', '')}`
  if (b.outcome === 'Under') return `Under ${b.market.replace('Over/Under ', '')}`
  return b.outcome
}

function marketGroupLabel(market) {
  if (market === '1X2') return 'Match Result'
  if (market === 'Handicap +0.5') return 'Double Chance'
  if (market === 'Handicap 0.0') return 'Draw No Bet'
  if (market.startsWith('Handicap')) return 'Asian Handicap'
  if (market === 'BTTS') return 'Both Teams Score'
  return 'Goals'
}

// Plain-language phrasing of a bet for the Best Bets overview.
function plainBetPhrase(b) {
  if (b.outcome === 'home_win' || b.outcome === 'away_win') return <><TeamLabel name={b.team} /> to win</>
  if (b.outcome === 'draw') return 'Draw'
  if (b.outcome === 'Over') return `Over ${b.market.replace('Over/Under ', '')} goals`
  if (b.outcome === 'Under') return `Under ${b.market.replace('Over/Under ', '')} goals`
  if (b.market === 'Handicap +0.5') return <><TeamLabel name={b.team} /> or Draw (double chance)</>
  if (b.market === 'Handicap 0.0') return <><TeamLabel name={b.team} /> to win (draw no bet)</>
  if (b.outcome === 'handicap') return <><TeamLabel name={b.team} /> {b.market.replace('Handicap ', '')} handicap</>
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
const signedPct = (x) => `${x >= 0 ? '+' : ''}${(x * 100).toFixed(1)}%`
const bookName = (b) => (b || 'bet-at-home').replace(/\.de$/, '')

// The headline tip: where bet-at-home pays more than Pinnacle's margin-free
// price (src/price_tip.py). Model and AI are shown beside it, not used by it.
function PriceTipBox({ priceTip }) {
  if (!priceTip) {
    return (
      <p className="smart-bet-notip">
        <strong>No price tip for this match.</strong><br />
        No sharp reference price is available here.
      </p>
    )
  }
  const tip = priceTip.tip
  const book = bookName(priceTip.bookmaker)
  if (!tip) {
    return (
      <div className="price-tip is-empty">
        <span className="smart-bet-label price-tip-label-muted">Price Tip</span>
        <div className="price-tip-none">No tip for this match</div>
        <p className="price-tip-reason">{priceTip.reason}</p>
        {priceTip.outcomes.length > 0 && (
          <div className="price-tip-table">
            <div className="price-tip-table-head">
              <span>Outcome</span><span>Pinnacle</span><span>{book}</span><span>Chance</span><span>Edge</span>
            </div>
            {priceTipRows(priceTip.outcomes).map((o) => (
              <div className="price-tip-table-row" key={`${o.market}-${o.outcome}-${o.side}`}>
                <span>{betOutcomeLabel(o)}</span>
                <span>{o.pinnacle_odds ? o.pinnacle_odds.toFixed(2) : <em title="fair odds from Pinnacle's 1X2">{o.fair_odds.toFixed(2)}</em>}</span>
                <span>{o.book_odds.toFixed(2)}</span>
                <span title={o.refund_probability > 0 ? `win ${pct(o.win_probability)} · draw refunds ${pct(o.refund_probability)} · lose ${pct(o.loss_probability)}` : undefined}>
                  {pct(o.win_probability ?? o.probability)}{o.refund_probability > 0 ? '*' : ''}
                </span>
                <span className={o.edge >= priceTip.threshold ? 'positive' : 'negative'}>{signedPct(o.edge)}</span>
              </div>
            ))}
          </div>
        )}
        <p className="price-tip-footnote">
          {priceTip.outcomes.some(o => o.refund_probability > 0) && <>* Draw No Bet: chance to win; a draw returns the stake. </>}
          A tip appears when {book} pays at least {pct(priceTip.threshold)} above Pinnacle's fair price.
          That usually happens in the last hour before kickoff, when Pinnacle moves first.
        </p>
      </div>
    )
  }
  return (
    <div className="smart-bet-best price-tip">
      <span className="smart-bet-label">Price Tip</span>
      <div className="smart-bet-pick">{betOutcomeLabel(tip)}</div>
      <div className="price-tip-kpis">
        <div className="price-tip-kpi">
          <span className="price-tip-kpi-label">Pinnacle</span>
          <span className="price-tip-kpi-value">{(tip.pinnacle_odds || tip.fair_odds).toFixed(2)}</span>
          <span className="price-tip-kpi-sub">{tip.pinnacle_odds ? `fair ${tip.fair_odds.toFixed(2)}` : 'fair, from 1X2'}</span>
        </div>
        <div className="price-tip-kpi is-book">
          <span className="price-tip-kpi-label">{book}</span>
          <span className="price-tip-kpi-value">{tip.book_odds.toFixed(2)}</span>
          <span className="price-tip-kpi-sub">your odds</span>
        </div>
        <div className="price-tip-kpi">
          <span className="price-tip-kpi-label">Chance</span>
          <span className="price-tip-kpi-value">{pct(tip.win_probability ?? tip.probability)}</span>
          <span className="price-tip-kpi-sub">
            {tip.refund_probability > 0
              ? `win · ${pct(tip.refund_probability)} refund · ${pct(tip.loss_probability)} lose`
              : 'per Pinnacle'}
          </span>
        </div>
        <div className="price-tip-kpi is-edge">
          <span className="price-tip-kpi-label">Edge</span>
          <span className="price-tip-kpi-value">{signedPct(tip.edge)}</span>
          <span className="price-tip-kpi-sub">per € staked</span>
        </div>
      </div>
      <div className="smart-bet-agree-row">
        {priceTip.model_agrees != null && (
          <span className={`smart-bet-agree-chip ${priceTip.model_agrees ? 'yes' : 'no'}`}>
            {priceTip.model_agrees ? '◆ Model agrees ✓' : '◆ Model differs ✕'}
            {priceTip.model_probability != null ? ` ${pct(priceTip.model_probability)}` : ''}
          </span>
        )}
        {priceTip.ai_agrees != null && (
          <span className={`smart-bet-agree-chip ${priceTip.ai_agrees ? 'yes' : 'no'}`}>
            {priceTip.ai_agrees ? '✨ AI agrees ✓' : '✨ AI differs ✕'}
          </span>
        )}
      </div>
      <div className="smart-bet-best-meta">
        Chosen on price alone. Edge is an average over many bets, not a promise for this one.
      </div>
    </div>
  )
}

// The AI's research, closed until the reader asks for it.
function AgentFactors({ research }) {
  const [open, setOpen] = useState(false)
  const rows = [
    ['⚕', 'Lineups & injuries', research.lineups_injuries],
    ['📈', 'Form', research.form],
    ['🏆', 'Table situation', research.table_situation],
    ['💬', 'Other', research.other],
  ].filter(([, , text]) => text)
  if (rows.length === 0) return null
  return (
    <div className="wm-reveal agent-factors">
      <button className="agent-factors-toggle" onClick={() => setOpen(v => !v)} aria-expanded={open}>
        <span>✨ External Factors (AI Agent)</span>
        <span className="agent-factors-chevron">{open ? '▲' : '▼'}</span>
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
      <span className="smart-bet-label likely-tip-label">🎯 Most likely</span>
      <div className="likely-tip-row">
        <span className="likely-tip-pick">{betOutcomeLabel(pick)}</span>
        <span className="likely-tip-odds">{pick.best_odds.toFixed(2)}</span>
        <span className="likely-tip-chance">{pct(pick.market_probability)} chance</span>
      </div>
      <div className="smart-bet-agree-row">
        <span className={`smart-bet-agree-chip ${modelAgrees ? 'yes' : 'no'}`}>
          {modelAgrees ? '◆ Model agrees ✓' : '◆ Model differs ✕'}{modelP != null ? ` ${pct(modelP)}` : ''}
        </span>
        {aiAgrees != null && (
          <span className={`smart-bet-agree-chip ${aiAgrees ? 'yes' : 'no'}`}>
            {aiAgrees ? '✨ AI agrees ✓' : '✨ AI differs ✕'}
          </span>
        )}
      </div>
      <div className="smart-bet-best-meta">
        The market's likeliest bet between odds 1.30 and 2.00. Likely is not the same as good value:
        this pick carries the bookmaker's margin.
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
        <p className="wm-subtle">No current betting odds available for this match.</p>
      </div>
    )
  }

  if (betInfo.in_play) {
    return (
      <div className="wm-reveal">
        <p className="smart-bet-notip">
          <strong>This match has already kicked off.</strong><br />
          Odds are now live/in-play and move with the score — our pre-match model can't be
          meaningfully compared against them anymore. No tip for this one.
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
  const TABLE_ROWS = 10
  const allBets = (betInfo.bets && betInfo.bets.length) ? betInfo.bets : [...greens, ...reds]
  // Table order: the price tip, the market's likeliest bet, the model's
  // biggest gap to the market (★, explained in its box below), the AI's pick.
  // The model's favourite is no longer marked.
  const signals = [priceTipPick, likelyPick, best, agentPick].filter(Boolean)
  const signalRank = b => { const i = signals.findIndex(x => sameBet(x, b)); return i === -1 ? signals.length : i }
  const ordered = [...allBets].sort((a, b) =>
    signalRank(a) - signalRank(b)
    || (b.kelly_stake_pct || 0) - (a.kelly_stake_pct || 0)
    || b.expected_value - a.expected_value)
  const visibleRows = showAllMarkets ? ordered : ordered.slice(0, TABLE_ROWS)
  const hiddenCount = ordered.length - TABLE_ROWS
  const hasUserBook = (betInfo.bets || []).some(b => b.bookmaker_key === USER_BOOK_KEY)

  // Greyed out: no positive edge, or a stake under 1% - the sizing itself
  // says the bet is barely worth making.
  const dimmed = b => b.expected_value <= 0 || (b.kelly_stake_pct || 0) < 1

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
      <div className={`smart-bet-table-row ${dimmed(b) && !keepFullOpacity ? 'is-red' : ''} ${isPriceTip ? 'is-rec' : ''}`} key={`${kind}-${i}`}>
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
      <PriceTipBox priceTip={betInfo.price_tip} />
      <LikelyTipBox pick={likelyPick} agentPick={agentPick} sameBet={sameBet}
                    home={betInfo.home_team} away={betInfo.away_team} />

      {(greens.length > 0 || reds.length > 0) && (
        <div className="smart-bet-table">
          <div className="smart-bet-table-head">
            <span>Market</span>
            <span>Tip</span>
            <span>Odds</span>
            <span>Edge</span>
            <span>Stake</span>
          </div>
          {visibleRows.map((b, i) => renderRow(b, i, 'row'))}
          {hiddenCount > 0 && (
            <button className="smart-bet-more" onClick={() => setShowAllMarkets(v => !v)}>
              {showAllMarkets ? 'Show fewer markets ▲' : `Show all markets (${hiddenCount} more) ▼`}
            </button>
          )}
          <p className="smart-bet-table-note">
            {hasUserBook
              ? 'Odds are bet-at-home\'s. * = not offered at bet-at-home, best other bookmaker shown.'
              : 'bet-at-home\'s full market list is read in the hour before kickoff; until then, best available odds are shown.'}
          </p>
        </div>
      )}

      {agentEval && (
        <div className="smart-bet-agent">
          <div className="smart-bet-agent-headtitle">
            <span className="smart-bet-agent-headline">✨ AI predicts: {agentEval.bet_headline}</span>
          </div>
          <p className="smart-bet-agent-text">
            {renderBoldMarkdown(agentEval.bet_reasoning, 'smart-bet-highlight-purple')}
            {agentPick && (
              <> Our model rates this at <strong className="smart-bet-highlight-purple">{(agentPick.probability * 100).toFixed(0)}%</strong>.</>
            )}
          </p>
        </div>
      )}

      {best ? (
        <div className="smart-bet-signal-box is-green">
          <div className="smart-bet-agent-headtitle">
            <span className="smart-bet-signal-headline">★ Biggest gap to the market: {betOutcomeLabel(best)}</span>
          </div>
          <p className="smart-bet-agent-text">
            {best.market_probability != null ? (
              <>We rate this at <strong className="smart-bet-highlight-green">{(best.probability * 100).toFixed(0)}%</strong> (our model pulled partway toward the market to correct for its
              overconfidence), while {best.bookmaker}'s odds of <strong className="smart-bet-highlight-green">{best.best_odds.toFixed(2)}</strong> imply {(best.market_probability * 100).toFixed(0)}% —
              a gap of {Math.round((best.probability - best.market_probability) * 100)} percentage points. Treat that as a disagreement, not
              a profit: sorted by the size of this gap, our past bets did <em>worse</em> where the
              gap was widest, not better.</>
            ) : (
              <>We rate this at <strong className="smart-bet-highlight-green">{(best.probability * 100).toFixed(0)}%</strong> at odds of <strong className="smart-bet-highlight-green">{best.best_odds.toFixed(2)}</strong> from {best.bookmaker}, with no
              reliable market comparison available for this one.</>
            )}
          </p>
        </div>
      ) : (
        <div className="smart-bet-signal-box is-green">
          <div className="smart-bet-agent-headtitle">
            <span className="smart-bet-signal-headline">★ Biggest gap to the market: none worth showing</span>
          </div>
          <p className="smart-bet-agent-text">
            {recWarning
              ? 'The widest gap in this match is too small to be worth naming.'
              : 'Our model and the bookmakers agree closely on every market in this match.'}
          </p>
        </div>
      )}

      <div className="smart-bet-finePrint">
        <p><strong>💰</strong> price tip: bet-at-home pays more than Pinnacle's fair price. <strong>🎯</strong> the bet
        the market rates most likely to land at odds between 1.30 and 2.00 (no edge claimed). <strong>✨</strong> the AI
        agent's own pick after live research. <strong>★</strong> where our model sees the biggest gap to the
        market. The Edge and Stake columns are the model's view, which has shown no advantage over the market.</p>

      {[...greens, ...reds].some(b => b.market.startsWith('Handicap')) && (
        <p>
          <strong>+0.5</strong> = Double Chance (win/draw). <strong>0.0</strong> = Draw No Bet (stake back on
          a draw; some books call this "Head-to-Head"). Other numbers = Asian Handicap (win/lose margin).
        </p>
      )}

      {[...greens, ...reds].some(b => b.suspicious) && (
        <p>
          <strong>⚠</strong> = large edge or model/market gap — likely a model weakness, not a real tip.
        </p>
      )}

      <p className="smart-bet-disclaimer">
        For entertainment and informational purposes only. This is a statistical model, not betting advice — it
        does not guarantee profit and has no proven edge over bookmaker odds. Betting involves risk of financial
        loss; if you choose to bet, do so responsibly and only with money you can afford to lose. 18+.
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
          {fixture ? `${fixture.date} · ${fixture.time}` : matchId}
        </span>
        <div className="wm-card-header-right">
          {gf.match_type && show(6) && <span className="wm-match-type">{gf.match_type}</span>}
          {onCollapse && !analyzing && (
            <button className="wm-collapse-btn" onClick={onCollapse}>
              Collapse ▲
            </button>
          )}
        </div>
      </div>

      <div className="result-header">
        <span className="team-name"><TeamLabel name={data.home_team} /></span>
        <div className="prediction-badge">
          {data.prediction === 'H' ? `${data.home_team} to win` :
           data.prediction === 'A' ? `${data.away_team} to win` : 'Draw'}
        </div>
        <span className="team-name"><TeamLabel name={data.away_team} /></span>
      </div>

      {analyzing && (
        <div className="analyzing-status">
          <span className="analyzing-spinner" />
          <span>{ANALYZING_STEPS[revealStep]}</span>
        </div>
      )}

      <div className="wm-cluster">
        <span className="wm-cluster-label">Overview</span>

        <RevealSection visible={show(1)} className="probabilities-donut">
          <ResultDonut
            home={data.probability_home_win}
            draw={data.probability_draw}
            away={data.probability_away_win}
            score={sp.most_likely_score}
            colors={matchColors}
          />
          <div className="probabilities-legend">
            <span className="legend-title">Win Probability</span>
            <div className="legend-row">
              <span className="legend-dot" style={{ background: matchColors.home }} />
              <span className="legend-name"><TeamLabel name={data.home_team} /></span>
              <span className="legend-value"><AnimatedNumber value={data.probability_home_win * 100} decimals={1} suffix="%" /></span>
            </div>
            <div className="legend-row">
              <span className="legend-dot gray" />
              <span className="legend-name">Draw</span>
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

      <div className="wm-cluster">
        <span className="wm-cluster-label">Stats &amp; Odds</span>

        <RevealSection visible={show(2)}>
          <BettingMarkets data={data} />
        </RevealSection>

        <RevealSection visible={show(3)} className="explanation-grid wm-grid">
          <div className="stat-card">
            <h4>Most Likely Score</h4>
            <div className="wm-scoreboard">
              <TeamCrest name={data.home_team} className="wm-scoreboard-crest" />
              <div className="wm-score-highlight">{sp.most_likely_score}</div>
              <TeamCrest name={data.away_team} className="wm-scoreboard-crest" />
            </div>
            <p className="wm-subtle wm-scoreboard-xg">
              xG: <AnimatedNumber value={sp.home_xg} decimals={2} /> : <AnimatedNumber value={sp.away_xg} decimals={2} />
            </p>
            {(() => {
              const scorelines = (sp.top_scorelines || []).slice(0, 3)
              const maxP = Math.max(...scorelines.map(s => s.probability), 0)
              return scorelines.map((s, i) => (
                <div className={`score-row${s.probability === maxP ? ' is-leader' : ''}`} key={i}>
                  <span className="score-row-rank">{i === 0 ? '★' : i + 1}</span>
                  <span className="score-row-label">{s.score}</span>
                  <span className="score-row-value"><AnimatedNumber value={s.probability * 100} decimals={1} suffix="%" /></span>
                </div>
              ))
            })()}
          </div>

          <div className="stat-card">
            <h4>Halftime</h4>
            {(() => {
              const htScores = (gf.top_halftime_scores || []).slice(0, 3)
              const maxP = Math.max(...htScores.map(h => h.probability), 0)
              return htScores.map((h, i) => (
                <div className={`score-row${h.probability === maxP ? ' is-leader' : ''}`} key={i}>
                  <span className="score-row-rank">{i === 0 ? '★' : i + 1}</span>
                  <span className="score-row-label">{h.score}</span>
                  <span className="score-row-value"><AnimatedNumber value={h.probability * 100} decimals={1} suffix="%" /></span>
                </div>
              ))
            })()}
            <div className="score-row is-drama">
              <span className="score-row-rank">⚡</span>
              <span className="score-row-label score-row-label-wide">Late drama (75'+)</span>
              <span className="score-row-value"><AnimatedNumber value={(gf.late_drama_probability || 0) * 100} decimals={0} suffix="%" /></span>
            </div>
          </div>
        </RevealSection>

        {ps.possession && (
          <RevealSection visible={show(4)} className="h2h-stats">
            <h4>Predicted Match Stats</h4>
            <div className="h2h-teams">
              <span><TeamLabel name={data.home_team} /></span>
              <span><TeamLabel name={data.away_team} /></span>
            </div>
            <HeadToHeadStat label="Possession" home={ps.possession.home} away={ps.possession.away} suffix="%" />
            <HeadToHeadStat label="Shots" home={ps.shots.home} away={ps.shots.away} />
            <HeadToHeadStat label="Shots on Target" home={ps.shots_on_target.home} away={ps.shots_on_target.away} />
            <HeadToHeadStat label="Corners" home={ps.corners.home} away={ps.corners.away} />
            <HeadToHeadStat label="Passes" home={ps.passes.home} away={ps.passes.away} />
          </RevealSection>
        )}

        {gf.match_description && gf.match_description !== 'Both teams play attacking football at an even level' && (
          <RevealSection visible={show(5)}>
            <p className="wm-description">{gf.match_description}</p>
          </RevealSection>
        )}
      </div>

      {!analyzing && (
        (betInfo && betInfo.agent_eval && betInfo.agent_eval.research) || onStartBetCheck
      ) && (
        <div className="wm-cluster wm-cluster-bet">
          <span className="wm-cluster-label">Smart Bet</span>

          {betInfo && betInfo.agent_eval && betInfo.agent_eval.research && (
            <AgentFactors research={betInfo.agent_eval.research} />
          )}

          {onStartBetCheck && (
            <div className="smart-bet-section">
              {betStep === undefined ? (
                <div className="smart-bet-cta">
                  <span className="smart-bet-cta-icon">🎯</span>
                  <h4 className="smart-bet-cta-title">Want the full betting breakdown?</h4>
                  <p className="smart-bet-cta-sub">
                    Value bets, model favorite, and the safest pick — all in one tap.
                  </p>
                  <button className="smart-bet-btn" onClick={onStartBetCheck}>
                    Get Your Bet Tips
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
        AI Prediction
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
          <ProbabilityBar label="Draw" value={0.24} color={colors.draw} />
          <ProbabilityBar label="Barcelona" value={0.28} color={colors.away} />
        </div>
      </div>
      <p className="hero-preview-note">
        "Expect a tight first half — Real Madrid's pace on the counter breaks the deadlock after 60'."
      </p>
    </div>
  )
}

const FLOW_STEPS = [
  {
    icon: <IconDataPoints />,
    title: 'Data Ingestion',
    description:
      'Every analysis starts with real club football history — multiple seasons of match ' +
      'results, full league and cup data, and rolling form/goal stats for every club ' +
      'we cover.',
    tags: ['Historical Results', 'Head-to-Head', 'Goal Stats', 'Recent Form'],
  },
  {
    icon: <IconFeatures />,
    title: 'Feature Engineering',
    description:
      'The raw numbers are transformed into signals the models can actually learn from: Elo-style ' +
      'strength ratings, attack and defense ratings per team, head-to-head history, home-advantage ' +
      'adjustments and momentum curves from each team\'s last matches.',
    tags: ['Elo Ratings', 'Attack & Defense Ratings', 'Head-to-Head', 'Home Advantage'],
  },
  {
    icon: <IconNeuralNet />,
    title: 'Ensemble Model Core',
    description:
      'Three independent models analyze every matchup in parallel — a Dixon-Coles Poisson model ' +
      'for realistic scorelines, an XGBoost model for non-linear patterns, and a Random Forest for ' +
      'robustness. Their outputs are combined into a single ensemble verdict.',
    tags: ['Dixon-Coles Poisson', 'XGBoost', 'Random Forest', 'Ensemble Voting'],
  },
  {
    icon: <IconTarget />,
    title: 'Score & Probability Prediction',
    description:
      'The ensemble produces a full probability distribution across every realistic scoreline, ' +
      'then derives the win / draw / loss percentages, the most likely final score and the ' +
      'expected goals (xG) for both teams.',
    tags: ['Win/Draw/Loss %', 'Most Likely Score', 'Expected Goals (xG)'],
  },
  {
    icon: <IconTimeline />,
    title: 'Match Flow Simulation',
    description:
      'A dedicated game-flow engine simulates the 90 minutes minute by minute — kickoff, key ' +
      'chances, goals, the halftime score and the final score — and classifies the overall ' +
      'character of the game, from "Defensive Battle" to "Goal Fest".',
    tags: ['Match Ticker', 'Momentum', 'Match Type', 'Halftime & Fulltime'],
  },
  {
    icon: <IconSpark />,
    title: 'AI Storytelling',
    description:
      'A team of AI agents turns the deterministic match ticker into vivid storylines — tactical ' +
      'breakdowns, dramatic momentum shifts and player-focused moments. Every narrative is locked ' +
      'to the model\'s predicted ticker, so the story never contradicts the prediction.',
    tags: ['AI Agents', 'Tactical Analysis', 'Storylines', 'Consistency-Locked'],
  },
  {
    icon: <IconBroadcast />,
    title: 'Live Delivery',
    description:
      'Once generated, the full analysis is cached and instantly available on the website — ' +
      'including probabilities, scoreline and match ticker — and automatically turned into ready-to-post ' +
      'Instagram carousel content via an automated workflow.',
    tags: ['Website', 'Instagram Carousel', 'Workflow Automation', 'Cached & Instant'],
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
        <span className="how-eyebrow">Behind the Predictions</span>
        <h2 className="section-title">How Our AI Analysis Works</h2>
        <p className="how-intro">
          From the first raw data point to the final social media post — every prediction passes
          through the same seven-stage pipeline. Scroll down to follow the data as it moves through
          each stage.
        </p>
        <button className="flow-back-btn" onClick={onBack}>← Back to Predictions</button>
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
                <span className="flow-scroll-step-num">Stage {i + 1} / {FLOW_STEPS.length}</span>
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
        Back to Predictions
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
  const rows = [{ key: 'ko', minute: "1'", type: 'kickoff', head: '🟢 Kickoff', text: `${homeTeam} vs ${awayTeam} is underway.`, score: '0:0' }]
  let halftimeShown = false
  events.forEach((e, i) => {
    const t = tickerMinute(e.minute)
    if (!halftimeShown && t.base > 45) {
      rows.push({ key: 'ht', minute: 'HT', type: 'halftime', head: '⏸️ Half-time', text: `${homeTeam} ${score()} ${awayTeam} at the break.`, score: score() })
      halftimeShown = true
    }
    if (e.type === 'goal') {
      if (e.team === homeTeam) home += 1; else away += 1
      const how = e.own_goal ? ' (own goal)' : e.penalty ? ' (penalty)' : ''
      rows.push({ key: i, minute: e.minute, type: 'goal', head: `⚽ GOAL! ${e.team}!`,
                  text: `${e.player || 'Unknown'}${how} makes it ${score()}.`, score: score() })
    } else if (e.type === 'red_card') {
      rows.push({ key: i, minute: e.minute, type: 'chance', head: `🟥 Red card — ${e.team}`,
                  text: `${e.player || 'A player'} is sent off. ${e.team} play on with ten.`, score: score() })
    } else if (e.type === 'yellow_card') {
      rows.push({ key: i, minute: e.minute, type: 'yellow', head: `🟨 Yellow card — ${e.team}`,
                  text: `${e.player || 'A player'} is booked.`, score: null })
    }
  })
  if (!halftimeShown) {
    rows.push({ key: 'ht', minute: 'HT', type: 'halftime', head: '⏸️ Half-time', text: `${homeTeam} ${score()} ${awayTeam} at the break.`, score: score() })
  }
  const final = homeScore != null ? `${homeScore}:${awayScore}` : score()
  rows.push({ key: 'ft', minute: 'FT', type: 'fulltime', head: '🏁 Full-time', text: `${homeTeam} ${final} ${awayTeam}.`, score: final })

  return (
    <div className="wm-stories real-ticker">
      <h4>Match Ticker</h4>
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
      <h4>Match Stats</h4>
      <div className="h2h-teams">
        <span><TeamLabel name={homeTeam} /></span>
        <span><TeamLabel name={awayTeam} /></span>
      </div>
      {stats.home.possession != null && (
        <HeadToHeadStat label="Possession" home={stats.home.possession} away={stats.away.possession} suffix="%" />
      )}
      {stats.home.shots != null && (
        <HeadToHeadStat label="Shots" home={stats.home.shots} away={stats.away.shots} />
      )}
      {stats.home.shots_on_target != null && (
        <HeadToHeadStat label="Shots on Target" home={stats.home.shots_on_target} away={stats.away.shots_on_target} />
      )}
      {stats.home.corners != null && (
        <HeadToHeadStat label="Corners" home={stats.home.corners} away={stats.away.corners} />
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
      <p className="wm-subtle" style={{ marginBottom: '0.9rem', fontSize: '0.75rem' }}>Pre-match AI prediction</p>

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
          <span className="legend-title">Win Probability</span>
          <div className="legend-row">
            <span className={`legend-dot ${homeCorrect ? 'hit' : 'gold'}`} />
            <span className="legend-name"><TeamLabel name={aiData.home_team} />{homeCorrect ? ' ✓' : ''}</span>
            <span className="legend-value"><AnimatedNumber value={aiData.probability_home_win * 100} decimals={1} suffix="%" /></span>
          </div>
          <div className="legend-row">
            <span className={`legend-dot ${drawCorrect ? 'hit' : 'gray'}`} />
            <span className="legend-name">Draw{drawCorrect ? ' ✓' : ''}</span>
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
            <h4>Top Scores Predicted</h4>
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
              <h4>Markets</h4>
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
                    <span className="stat-label" style={hit ? { color: '#4ade80', fontWeight: 700 } : {}}>{over ? 'Über' : 'Unter'} {o.line} Tore{hit ? ' ✓' : ''}</span>
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
          <span className="fixture-date">{fixture.date} · {fixture.time}</span>
          <span className="fixture-final-badge">Final</span>
        </div>
        <div className="fixture-teams">
          <span><TeamLabel name={fixture.home_team} /></span>
          <span className="fixture-final-score">{result.home_score} – {result.away_score}</span>
          <span><TeamLabel name={fixture.away_team} /></span>
        </div>
        <span className="fixture-expand-hint">Tap to view details ▾</span>
      </div>
    )
  }

  return (
    <div className="card wm-card">
      <div className="wm-card-header">
        <span className="wm-match-id">{fixture.date} · {fixture.time}</span>
        <div className="wm-card-header-right">
          <span className="wm-match-type" style={{ background: 'rgba(34,197,94,0.15)', color: '#4ade80' }}>Final</span>
          <button className="wm-collapse-btn" onClick={() => setExpanded(false)}>Collapse ▲</button>
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
            {showAI ? '▲ Hide AI Prediction' : '▼ AI Prediction as Comparison'}
          </button>
          {showAI && <AiComparisonPanel fixture={fixture} result={result} aiData={aiData} />}
        </div>
      )}

      {!aiData && (
        <div style={{ marginTop: '1rem' }}>
          {analysisActive
            ? <p className="wm-subtle">Loading AI analysis…</p>
            : <button className="fixture-generate-btn" onClick={onGenerate}>Show AI Pre-Match Analysis</button>
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
    }, 4200)
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
    }, 1800)
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
        <div className="nav-links">
          <a href="#predictions" onClick={() => setPage('home')}>Predictions</a>
          <a href="#how-it-works" onClick={(e) => { e.preventDefault(); setPage('how-it-works') }}>How It Works</a>
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
                  <span className="hero-eyebrow">A New Era of Football Intelligence</span>
                </div>
                <h1>AI-Powered Football Predictions</h1>
                <p>
                  A breakthrough AI model — trained on thousands of club football data points — delivers
                  instant, in-depth analysis for every fixture: match outcomes, scorelines and full
                  match storylines, generated like never before.
                </p>
                <div className="competition-badge">
                  <img src="https://a.espncdn.com/i/leaguelogos/soccer/500-dark/2.png" alt="" className="competition-badge-logo" />
                  <span>Now covering <strong>UEFA Champions League</strong></span>
                </div>
                <div className="hero-stats">
                  <div className="hero-stat">
                    <span className="hero-stat-value">Thousands</span>
                    <span className="hero-stat-label">Data Points Analyzed</span>
                  </div>
                  <div className="hero-stat">
                    <span className="hero-stat-value">36</span>
                    <span className="hero-stat-label">League Phase Clubs</span>
                  </div>
                  <div className="hero-stat">
                    <span className="hero-stat-value">189</span>
                    <span className="hero-stat-label">League Phase Matches</span>
                  </div>
                  <div className="hero-stat">
                    <span className="hero-stat-value">1</span>
                    <span className="hero-stat-label">Trophy</span>
                  </div>
                </div>
              </div>
              <HeroPreviewCard />
            </div>
          </header>

          <main className="main">
            <section id="predictions" className="wm-section">
              <h2 className="section-title">Predictions</h2>

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
                <button className="competition-pill soon" disabled title="Coming soon">
                  <span className="competition-pill-emoji">🏴󠁧󠁢󠁥󠁮󠁧󠁿</span>
                  Premier League
                  <span className="competition-pill-soon">Soon</span>
                </button>
                <button className="competition-pill soon" disabled title="Coming soon">
                  <span className="competition-pill-emoji">🇪🇸</span>
                  La Liga
                  <span className="competition-pill-soon">Soon</span>
                </button>
              </div>

              <div className="group-tabs">
                <button
                  className={`group-tab special-tab ${activeGroup === 'next' ? 'active' : ''}`}
                  onClick={() => setActiveGroup('next')}
                >
                  📅 Next Games
                </button>
                <button
                  className={`group-tab special-tab ${activeGroup === 'hot' ? 'active' : ''}`}
                  onClick={() => setActiveGroup('hot')}
                >
                  🔥 Hot Game
                </button>
                <button
                  className={`group-tab special-tab ${activeGroup === 'combo' ? 'active' : ''}`}
                  onClick={() => { setActiveGroup('combo'); if (combo === null && !comboLoading) loadCombo() }}
                >
                  🎟️ Combo Ticket
                </button>
                {currentGroups.map(g => (
                  <button
                    key={g}
                    className={`group-tab ${activeGroup === g ? 'active' : ''}`}
                    onClick={() => setActiveGroup(g)}
                  >
                    {g.length === 1 ? `Group ${g}` : g}
                  </button>
                ))}
              </div>

              {wmLoading && (
                <div className="analyzing-status loading-inline">
                  <span className="analyzing-spinner" />
                  <span>Loading analyses…</span>
                </div>
              )}

              {activeGroup === 'combo' && (
                <ComboTicketView combo={combo} loading={comboLoading} />
              )}

              {activeGroup === 'next' && nextGames.length === 0 && (
                <p className="wm-subtle">No matches scheduled for today.</p>
              )}

              {activeGroup === 'hot' && (
                nextGames.length === 0
                  ? <p className="wm-subtle">No matches scheduled for today.</p>
                  : <p className="wm-subtle hot-game-subtitle">🔥 Today's marquee matchup — the highest-ranked teams in action.</p>
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
        <p>Football Insights — AI-generated predictions for entertainment purposes only.</p>
      </footer>
    </div>
  )
}
