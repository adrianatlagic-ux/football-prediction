import { useState, useEffect, useRef } from 'react'
import axios from 'axios'
import './App.css'
import CL_FIXTURES from './cl_fixtures.json'
import BL_FIXTURES from './bl_fixtures.json'
import CLUB_CRESTS from './club_crests.json'

const API_BASE = import.meta.env.DEV ? 'http://127.0.0.1:8000' : ''

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

// Bundesliga: one "Spieltag N" group per matchday, sorted numerically.
const BL_GROUPS = [...new Set(BL_FIXTURES.map(f => f.group))].sort((a, b) => {
  const na = parseInt(a.replace(/\D/g, ''), 10) || 0
  const nb = parseInt(b.replace(/\D/g, ''), 10) || 0
  return na - nb
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
const NEXT_GAMES = CL_FIXTURES
  .filter(f => { const d = fixtureDateTime(f); return d >= _NG_START && d < _NG_END })
  .sort((a, b) => fixtureDateTime(a) - fixtureDateTime(b))

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
function getHotFixture(predictionsById) {
  let best = null
  let bestScore = -Infinity
  for (const fixture of NEXT_GAMES) {
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

// club_crests.json's colors come straight from ESPN's team API, which for
// several Bundesliga clubs just returns a generic placeholder (#ffffff, or
// the same #DA0308 red for four unrelated teams) instead of a real brand
// color. Override the ones that are wrong or collide with another club in
// this season's fixture list; everything else still falls through to the
// scraped ESPN color.
const TEAM_COLOR_OVERRIDES = {
  '1. FC Köln': '#ED1C24',
  'Augsburg': '#BA3733',
  'Bayer Leverkusen': '#E32219',
  'Borussia Mönchengladbach': '#00983A',
  'Eintracht Frankfurt': '#E1000F',
  'SC Freiburg': '#FFFFFF',
  'RB Leipzig': '#FFFFFF',
  'Elversberg': '#FFFFFF',
  'Union Berlin': '#F97316',
}

function getTeamColor(name, fallback) {
  return TEAM_COLOR_OVERRIDES[name] || CLUB_CRESTS[name]?.color || fallback
}

function hexColorDistance(a, b) {
  if (!/^#[0-9a-f]{6}$/i.test(a) || !/^#[0-9a-f]{6}$/i.test(b)) return Infinity
  const pa = parseInt(a.slice(1), 16), pb = parseInt(b.slice(1), 16)
  const dr = ((pa >> 16) & 255) - ((pb >> 16) & 255)
  const dg = ((pa >> 8) & 255) - ((pb >> 8) & 255)
  const db = (pa & 255) - (pb & 255)
  return Math.sqrt(dr * dr + dg * dg + db * db)
}

// Two clubs can legitimately share (near-)identical brand colors (e.g. two
// clubs both wearing blue). When that happens for the two teams actually
// facing each other, the donut/legend would show one indistinguishable
// color twice - swap the away team to a neutral accent so the two sides
// always read as visually distinct.
function getMatchColors(homeTeam, awayTeam) {
  const home = getTeamColor(homeTeam, 'var(--gold)')
  let away = getTeamColor(awayTeam, 'var(--cyan)')
  if (home.toLowerCase() === away.toLowerCase() || hexColorDistance(home, away) < 60) {
    away = home.toLowerCase() === 'var(--cyan)'.toLowerCase() ? '#f97316' : 'var(--cyan)'
  }
  return { home, draw: '#6b7280', away }
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
  // Split the full track between the two teams in proportion to their own
  // ratings, so the bar always reads as one continuous tug-of-war (no gap or
  // overlap in the middle) while still reflecting the size of the gap
  // between the two ratings, not just who's ahead.
  const ratingTotal = homeRating + awayRating
  const homePct = ratingTotal > 0 ? (homeRating / ratingTotal) * 100 : 50
  const awayPct = 100 - homePct

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

function FixtureRow({ fixture }) {
  return (
    <div className="fixture-row fixture-pending">
      <div className="fixture-meta">
        <span className="fixture-date">{fixture.date} · {fixture.time}</span>
        <span className="fixture-pending-badge">Analysis pending</span>
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
  if (b.outcome === 'Over') return `Over ${b.market.replace('Over/Under ', '')}`
  if (b.outcome === 'Under') return `Under ${b.market.replace('Over/Under ', '')}`
  return b.outcome
}

function marketGroupLabel(market) {
  if (market === '1X2') return 'Match Result'
  if (market === 'Handicap +0.5') return 'Double Chance'
  if (market === 'Handicap 0.0') return 'Draw No Bet'
  if (market.startsWith('Handicap')) return 'Handicap'
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
          {leg.passes_single_bet_test === false && (
            <span className="combo-leg-flag"> · not recommended as a single</span>
          )}
        </div>
      </div>
      <div className="combo-leg-numbers">
        <span className="combo-leg-odds">{leg.best_odds.toFixed(2)}</span>
        <span className="combo-leg-prob">{(leg.probability * 100).toFixed(0)}%</span>
      </div>
    </div>
  )
}

function ComboTicketCard({ ticket, primary }) {
  const hit = ticket.probability * 100
  return (
    <div className={`combo-ticket ${primary ? 'is-primary' : ''}`}>
      <div className="combo-ticket-head">
        <span className="combo-ticket-legs">{ticket.leg_count}-fold</span>
        <span className="combo-ticket-odds">{ticket.combined_odds.toFixed(2)}</span>
      </div>
      <div className="combo-legs">
        {ticket.legs.map((leg, i) => <ComboLegRow key={i} leg={leg} index={i} />)}
      </div>
      <div className="combo-ticket-stats">
        <div className="combo-stat">
          <span className="combo-stat-label">Hit chance</span>
          <span className="combo-stat-value">{hit.toFixed(1)}%</span>
        </div>
        <div className="combo-stat">
          <span className="combo-stat-label">Payout</span>
          <span className="combo-stat-value">{ticket.combined_odds.toFixed(2)}×</span>
        </div>
        <div className="combo-stat">
          <span className="combo-stat-label">Model EV</span>
          <span className={`combo-stat-value ${ticket.expected_value >= 0 ? 'positive' : 'negative'}`}>
            {ticket.expected_value >= 0 ? '+' : ''}{(ticket.expected_value * 100).toFixed(0)}%
          </span>
        </div>
        <div className="combo-stat">
          <span className="combo-stat-label">Stake</span>
          <span className="combo-stat-value">{ticket.stake_pct.toFixed(1)}%</span>
        </div>
      </div>
      {primary && (
        <p className="combo-ticket-note">
          After a fixed 3-point safety haircut on every leg, the expected value is still
          <strong> {(ticket.stressed_expected_value * 100).toFixed(0)}%</strong>
          {' '}(hit chance {(ticket.stressed_probability * 100).toFixed(1)}%).
          {ticket.margin_cost != null && (
            <> The bookmaker prices this combo at {(ticket.market_probability * 100).toFixed(1)}% —
            the {(ticket.margin_cost * 100).toFixed(1)} point gap is the margin compounded across
            every leg.</>
          )}
        </p>
      )}
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
      <p className="best-bets-intro">
        A combo only pays if <strong>every</strong> leg wins. That's why at most one bet per match is
        used — only independent legs may have their probabilities multiplied — and why safer picks are
        preferred over the biggest odds. The bookmaker's margin compounds with every added leg, which
        makes combos structurally worse value than singles.
      </p>

      {!combo.recommended && (
        <p className="smart-bet-notip">
          <strong>No combo ticket today.</strong><br />
          {combo.reason}
        </p>
      )}

      {combo.recommended?.legs_passing_single_bet_test === 0 && (
        <p className="combo-warning">
          ⚠ None of these matches has a Game Pick in its own analysis — that view applies a stricter
          test. This ticket therefore rests on bets that would <strong>not</strong> be recommended on their own.
        </p>
      )}

      {combo.days?.map(day => (
        <div className="combo-day" key={day.date}>
          <span className="combo-section-label">
            {new Date(day.date + 'T12:00:00').toLocaleDateString('en-GB', { weekday: 'long', day: 'numeric', month: 'short' })}
            {' · '}{day.eligible_legs} eligible {day.eligible_legs === 1 ? 'match' : 'matches'}
          </span>

          {!day.recommended && <p className="smart-bet-notip">{day.reason}</p>}

          {day.recommended && (
            <>
              <ComboTicketCard ticket={day.recommended} primary />

              {day.all_in && day.all_in.leg_count > day.recommended.leg_count && (
                <div className="combo-allin">
                  <span className="combo-allin-label">
                    All {day.all_in.leg_count} eligible matches on one slip
                  </span>
                  <div className="combo-allin-row">
                    <span>Odds <strong>{day.all_in.combined_odds.toFixed(2)}</strong></span>
                    <span>Hit chance <strong>{(day.all_in.probability * 100).toFixed(1)}%</strong></span>
                    <span>Model EV <strong className={day.all_in.expected_value >= 0 ? 'positive' : 'negative'}>
                      {day.all_in.expected_value >= 0 ? '+' : ''}{(day.all_in.expected_value * 100).toFixed(0)}%
                    </strong></span>
                  </div>
                  <p className="combo-allin-note">
                    {day.all_in_is_worse
                      ? <>Higher expected value, but it only lands {(day.all_in.probability * 100).toFixed(1)}% of
                        the time versus {(day.recommended.probability * 100).toFixed(1)}% above — worse for growing a
                        bankroll, which is why it is not the suggestion.</>
                      : <>Shown for comparison. More legs always means a lower chance of the slip landing.</>}
                  </p>
                </div>
              )}
            </>
          )}
        </div>
      ))}

      <p className="smart-bet-finePrint">
        Ranked by Kelly growth rather than raw expected value — otherwise the longest ticket with the
        slimmest chance of landing would always win. Only combinations that stay positive after the
        safety haircut are offered. This is an experimental model, not evidence that combo betting pays.
        Only stake money you can afford to lose. 18+.
      </p>
    </div>
  )
}

function SmartBetCard({ betStep, betInfo, data }) {
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
  // thin fallback, not a real tip, so it must not be promoted to ★/Value Bet
  // status just because it was the least-bad green available.
  const recWarning = betInfo.recommendation_warning
  const best = recWarning ? null : betInfo.recommendation
  const agentEval = betInfo.agent_eval
  const agentPick = agentEval && agentEval.pick
  const combined = betInfo.combined
  const consensusPick = combined && combined.consensus_pick
  const selectionCheck = consensusPick?.selection_assessment
  const modelFavorite = betInfo.model_favorite
  const safestPick = betInfo.safest_pick
  const scenarioText = data?.score_prediction?.betting_markets?.scenario
  const sameBet = (a, b) => a.market === b.market && a.outcome === b.outcome && a.team === b.team
  const greens = betInfo.green_bets || []
  const reds = betInfo.red_bets || []

  const renderRow = (b, i, kind) => {
    const isRec = best && sameBet(b, best)
    const isGamePick = consensusPick && sameBet(b, consensusPick)
    const isAgentPick = agentPick && sameBet(b, agentPick)
    const isModelFavorite = modelFavorite && sameBet(b, modelFavorite)
    const isSafestPick = safestPick && sameBet(b, safestPick)
    // Any marked signal (Game Pick, value bet, AI pick ✨, model favorite ◆,
    // safest pick 🛡) is a headline in its own right - dimming its row to 40%
    // opacity just because its edge happens to be negative buries it visually
    // even though we deliberately show these regardless of edge. The Game
    // Pick especially is *expected* to have flat/negative edge at short odds
    // (that's the whole "swim with the market" point), so graying it out
    // here would visually contradict the headline box above.
    const keepFullOpacity = isRec || isGamePick || isAgentPick || isModelFavorite || isSafestPick
    return (
      <div className={`smart-bet-table-row ${kind === 'red' && !keepFullOpacity ? 'is-red' : ''} ${isRec ? 'is-rec' : ''}`} key={`${kind}-${i}`}>
        <span className="smart-bet-col-market">{marketGroupLabel(b.market)}{b.suspicious ? ' ⚠' : ''}</span>
        <span className="smart-bet-col-pick">
          {isRec ? '★ ' : ''}{isAgentPick ? '✨ ' : ''}{isModelFavorite ? '◆ ' : ''}{isSafestPick ? '🛡 ' : ''}{betOutcomeLabel(b)}
        </span>
        <span className="smart-bet-col-odds">{b.best_odds.toFixed(2)}</span>
        <span className={`smart-bet-col-edge ${b.expected_value >= 0 ? 'positive' : 'negative'}`}>
          {b.expected_value >= 0 ? '+' : ''}{(b.expected_value * 100).toFixed(0)}%
        </span>
        <span className="smart-bet-col-stake">{isGamePick && selectionCheck ? `${selectionCheck.paper_stake_pct.toFixed(2)}% paper` : `${b.kelly_stake_pct}% Kelly`}</span>
      </div>
    )
  }

  return (
    <div className="wm-reveal smart-bet-card">
      {betInfo.odds_fetched_at && (
        <p className="smart-bet-finePrint">
          {betInfo.odds_stage === 'final' ? 'Final pre-match snapshot' : 'Daily odds snapshot'}:{' '}
          <time dateTime={betInfo.odds_fetched_at}>
            {new Date(betInfo.odds_fetched_at).toLocaleString('en-GB', { day: '2-digit', month: 'short', hour: '2-digit', minute: '2-digit', timeZoneName: 'short' })}
          </time>. Prices are from this snapshot, not live.
          {betInfo.final_refresh_status === 'pending_or_failed' && ' Final odds refresh is pending or unavailable; this is the earlier snapshot.'}
          {betInfo.calculated_at && <> Calculated at {new Date(betInfo.calculated_at).toLocaleTimeString('en-GB', { hour: '2-digit', minute: '2-digit', timeZoneName: 'short' })}.</>}
        </p>
      )}
      {consensusPick ? (
        <div className="smart-bet-best">
          <span className="smart-bet-label">Game Pick</span>
          <div className="smart-bet-pick">{betOutcomeLabel(consensusPick)}</div>
          <div className="smart-bet-odds-row">
            <span className="smart-bet-odds">{consensusPick.best_odds.toFixed(2)}</span>
            {consensusPick.market_probability != null && (
              <span className="smart-bet-winprob">
                {(consensusPick.market_probability * 100).toFixed(0)}% market estimate
              </span>
            )}
          </div>
          <div className="smart-bet-best-meta">at {consensusPick.bookmaker} · Experimental selection</div>
          {selectionCheck && (
            <p className="smart-bet-agent-text">
              Estimated return after the fixed stress tests: <strong>{(selectionCheck.stressed_expected_value * 100).toFixed(1)}%</strong> per unit staked.
              {' '}Minimum qualifying odds: <strong>{selectionCheck.min_acceptable_odds.toFixed(2)}</strong>.
              {' '}Compared with {selectionCheck.reference_book_count} other bookmakers.
              {' '}Paper stake: {selectionCheck.paper_stake_pct.toFixed(2)}% of the test budget.
              {' '}These checks are assumptions, not a statistical confidence interval or proof of profit.
            </p>
          )}
          <div className="smart-bet-agree-row">
            <span className={`smart-bet-agree-chip ${combined.model_agrees ? 'yes' : 'no'}`}>
              {combined.model_agrees ? '◆ Model agrees ✓' : '◆ Model differs ✕'}
            </span>
            <span className={`smart-bet-agree-chip ${combined.agent_agrees ? 'yes' : 'no'}`}>
              {combined.agent_agrees ? '✨ AI agrees ✓' : '✨ AI differs ✕'}
            </span>
          </div>
        </div>
      ) : (
        <p className="smart-bet-notip">
          <strong>No clear tip for this match.</strong><br />
          {combined?.selection?.reason || 'No eligible bet is available for this snapshot.'}
        </p>
      )}

      {(greens.length > 0 || reds.length > 0) && (
        <div className="smart-bet-table">
          <div className="smart-bet-table-head">
            <span>Market</span>
            <span>Tip</span>
            <span>Odds</span>
            <span>Model EV</span>
            <span>Sizing</span>
          </div>
          {greens.map((b, i) => renderRow(b, i, 'green'))}
          {reds.map((b, i) => renderRow(b, i, 'red'))}
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
            <span className="smart-bet-signal-headline">★ Value Bet: {betOutcomeLabel(best)}</span>
          </div>
          <p className="smart-bet-agent-text">
            {best.market_probability != null ? (
              <>We rate this at <strong className="smart-bet-highlight-green">{(best.probability * 100).toFixed(0)}%</strong> model probability of a positive payout. The available odds are <strong className="smart-bet-highlight-green">{best.best_odds.toFixed(2)}</strong>; the margin-adjusted market estimate is {(best.market_probability * 100).toFixed(0)}%.
              The model estimates a <strong className="smart-bet-highlight-green">{(best.expected_value * 100).toFixed(1)}%</strong> return per unit staked. This is an estimate, not proven profit.</>
            ) : (
              <>We rate this at <strong className="smart-bet-highlight-green">{(best.probability * 100).toFixed(0)}%</strong> at odds of <strong className="smart-bet-highlight-green">{best.best_odds.toFixed(2)}</strong> from {best.bookmaker}, with no
              reliable market comparison available for this one.</>
            )}
          </p>
        </div>
      ) : (
        <div className="smart-bet-signal-box is-green">
          <div className="smart-bet-agent-headtitle">
            <span className="smart-bet-signal-headline">★ Value Bet: No Bet Available</span>
          </div>
          <p className="smart-bet-agent-text">
            {recWarning
              ? 'No candidate passed all value filters: minimum stake, model–market disagreement and the edge ceiling.'
              : 'No eligible positive-edge bet with a recent quote is available.'}
          </p>
        </div>
      )}

      {modelFavorite && (
        <div className="smart-bet-signal-box is-gold">
          <div className="smart-bet-agent-headtitle">
            <span className="smart-bet-signal-headline">◆ Model's Choice: {betOutcomeLabel(modelFavorite)}</span>
          </div>
          <p className="smart-bet-agent-text">
            {scenarioText
              ? <>{renderScenario(scenarioText, data.home_team, data.away_team)} Our model rates this at <strong className="smart-bet-highlight-gold">{(modelFavorite.probability * 100).toFixed(0)}%</strong>.</>
              : <>at {modelFavorite.bookmaker} · model estimates <strong className="smart-bet-highlight-gold">{(modelFavorite.probability * 100).toFixed(0)}%</strong>
                {modelFavorite.market_probability != null && <>, market estimates {(modelFavorite.market_probability * 100).toFixed(0)}%</>}</>}
          </p>
        </div>
      )}

      {safestPick ? (
        <div className="smart-bet-signal-box is-red">
          <div className="smart-bet-agent-headtitle">
            <span className="smart-bet-signal-headline">🛡 Safest Bet: {betOutcomeLabel(safestPick)}</span>
          </div>
          <p className="smart-bet-agent-text">
            At odds of <strong className="smart-bet-highlight-red">{safestPick.best_odds.toFixed(2)}</strong> from {safestPick.bookmaker}, this is the <strong className="smart-bet-highlight-red">highest model probability of a positive payout</strong> among available bets at odds of 1.50 or below.
            The model estimates a <strong className="smart-bet-highlight-red">{(safestPick.probability * 100).toFixed(0)}%</strong> chance. Short odds do not guarantee safety or a positive return.
          </p>
        </div>
      ) : (
        <div className="smart-bet-signal-box is-red">
          <div className="smart-bet-agent-headtitle">
            <span className="smart-bet-signal-headline">🛡 Safest Bet: No Bet Available</span>
          </div>
          <p className="smart-bet-agent-text">
            No outcome in this match is priced at 1.50 odds or below
            {modelFavorite && <> — even the model's favorite, {betOutcomeLabel(modelFavorite)}, sits at {modelFavorite.best_odds.toFixed(2)}</>} —
            so none meets this display filter.
          </p>
        </div>
      )}

      <div className="smart-bet-finePrint">
        <p>Game Pick uses the experimental stress checks. Its paper sizing is capped at 1%; other rows show raw model Kelly for comparison. <strong>★</strong> value-filter pick. <strong>✨</strong> AI agent's own pick after live research. <strong>◆</strong> model's
        most likely outcome (no proven market edge required). <strong>🛡</strong> safest pick across all markets (highest
        model probability among bets priced at odds 1.50 or below; this does not establish safety or profit).</p>

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

      </div>

      {!analyzing && (
        (betInfo && betInfo.agent_eval && betInfo.agent_eval.research) || onStartBetCheck
      ) && (
        <div className="wm-cluster wm-cluster-bet">
          <span className="wm-cluster-label">Smart Bet</span>

          {betInfo && betInfo.agent_eval && betInfo.agent_eval.research && (
            <div className="wm-reveal agent-factors">
              <h4>✨ External Factors (AI Agent)</h4>
              {[
                ['⚕', 'Lineups & injuries', betInfo.agent_eval.research.lineups_injuries],
                ['📈', 'Form', betInfo.agent_eval.research.form],
                ['🏆', 'Table situation', betInfo.agent_eval.research.table_situation],
                ['💬', 'Other', betInfo.agent_eval.research.other],
              ].filter(([, , text]) => text).map(([icon, label, text]) => (
                <div className="agent-factors-row" key={label}>
                  <span className="agent-factors-cat">{icon} {label}</span>
                  <p className="agent-factors-text">{text}</p>
                </div>
              ))}
            </div>
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

function MatchTicker() {
  const items = [...CL_FIXTURES]
    .sort((a, b) => fixtureDateTime(a) - fixtureDateTime(b))
    .slice(0, 14)
  if (items.length === 0) return null
  const loop = [...items, ...items]
  return (
    <div className="match-ticker">
      <div className="match-ticker-track">
        {loop.map((f, i) => (
          <span className="match-ticker-item" key={`${f.match_id}-${i}`}>
            <span className="match-ticker-team"><TeamLabel name={f.home_team} /></span>
            <span className="match-ticker-vs">vs</span>
            <span className="match-ticker-team"><TeamLabel name={f.away_team} /></span>
            <span className="match-ticker-date">{f.date.slice(5)}</span>
          </span>
        ))}
      </div>
    </div>
  )
}

function HeroPreviewCard() {
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
        <ResultDonut home={0.48} draw={0.24} away={0.28} score="2–1" />
        <div className="hero-preview-bars">
          <ProbabilityBar label="Real Madrid" value={0.48} color="linear-gradient(90deg,var(--gold),var(--gold-light))" />
          <ProbabilityBar label="Draw" value={0.24} color="linear-gradient(90deg,#6b7280,#9ca3af)" />
          <ProbabilityBar label="Barcelona" value={0.28} color="linear-gradient(90deg,var(--cyan),var(--cyan-light))" />
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
    const key = `${r.home_team}__${r.away_team}`
    map[key] = r
  }
  return map
}

function RealTicker({ events, homeTeam, awayTeam }) {
  if (!events || events.length === 0) return null
  const goalEvents = events.filter(e => e.type === 'goal')
  const cardEvents = events.filter(e => e.type === 'red_card')
  if (goalEvents.length === 0 && cardEvents.length === 0) return null

  return (
    <div className="wm-stories real-ticker">
      <h4>Match Events</h4>
      {events.filter(e => e.type === 'goal' || e.type === 'red_card').map((e, i) => (
        <div className={`wm-ticker-event wm-ticker-${e.type === 'goal' ? 'goal' : 'chance'}`} key={i}>
          <span className="wm-ticker-minute">{e.minute}</span>
          <div className="wm-ticker-body">
            <div className="wm-ticker-head">
              <span>
                {e.type === 'goal' ? '⚽' : '🟥'}
                {' '}{e.player}
                {e.own_goal ? ' (OG)' : ''}
                {e.penalty ? ' (P)' : ''}
                {' — '}{e.team}
              </span>
            </div>
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

      <RealTicker events={result.events} homeTeam={fixture.home_team} awayTeam={fixture.away_team} />
      <RealStats stats={result.stats} homeTeam={fixture.home_team} awayTeam={fixture.away_team} />

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
  const [wmLoading, setWmLoading] = useState(true)
  const [activeCompetition, setActiveCompetition] = useState('cl')
  const [activeGroup, setActiveGroup] = useState(GROUPS[0])
  const currentFixtures = activeCompetition === 'bl' ? BL_FIXTURES : CL_FIXTURES
  const currentGroups = activeCompetition === 'bl' ? BL_GROUPS : GROUPS
  const switchCompetition = (comp) => {
    setActiveCompetition(comp)
    setActiveGroup(comp === 'bl' ? BL_GROUPS[0] : GROUPS[0])
  }
  const [analysisStep, setAnalysisStep] = useState({})
  const [bestBets, setBestBets] = useState(null)  // null = not loaded, [] = loaded empty
  const [bestBetsLoading, setBestBetsLoading] = useState(false)
  const [combo, setCombo] = useState(null)
  const [comboLoading, setComboLoading] = useState(false)

  const COMPETITION_SPORT_KEYS = { bl: 'soccer_germany_bundesliga', cl: 'soccer_uefa_champs_league' }

  async function loadCombo(comp) {
    setComboLoading(true)
    setCombo(null)
    try {
      const r = await axios.get(`${API_BASE}/combo-ticket`, {
        params: { competition: COMPETITION_SPORT_KEYS[comp] },
      })
      setCombo(r.data)
    } catch {
      setCombo({ error: true })
    } finally {
      setComboLoading(false)
    }
  }

  async function loadBestBets() {
    setBestBetsLoading(true)
    const games = NEXT_GAMES.filter(f => predictionsById[f.match_id])
    try {
      const results = await Promise.all(games.map(f =>
        axios.get(`${API_BASE}/value-bets`, { params: { home_team: f.home_team, away_team: f.away_team } })
          .then(r => ({ fixture: f, data: r.data })).catch(() => null)
      ))
      const clean = results
        .filter(x => x && x.data.odds_found && x.data.combined && x.data.combined.consensus_pick)
        .map(x => ({
          fixture: x.fixture,
          rec: x.data.combined.consensus_pick,
          consensusLabel: x.data.combined.consensus_label,
          commence: x.data.commence_time,
          agentEval: x.data.agent_eval,
        }))
        .sort((a, b) => (a.commence || '').localeCompare(b.commence || ''))
      setBestBets(clean)
    } finally {
      setBestBetsLoading(false)
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
  function goToMatchSmartBet(fixture) {
    setActiveGroup(fixture.group)
    setAnalysisStep(prev => ({ ...prev, [fixture.match_id]: Infinity }))  // reveal instantly
    setBetStepById(prev => ({ ...prev, [fixture.match_id]: Infinity }))   // show bets instantly
    if (betInfoById[fixture.match_id] === undefined) {
      axios.get(`${API_BASE}/value-bets`, { params: { home_team: fixture.home_team, away_team: fixture.away_team } })
        .then(r => setBetInfoById(prev => ({ ...prev, [fixture.match_id]: r.data })))
        .catch(() => setBetInfoById(prev => ({ ...prev, [fixture.match_id]: { odds_found: false, bets: [] } })))
    }
    setTimeout(() => {
      document.getElementById(`match-${fixture.match_id}`)?.scrollIntoView({ behavior: 'smooth', block: 'start' })
    }, 120)
  }

  useEffect(() => {
    async function loadAll() {
      try {
        const [listResp, resultsResp] = await Promise.allSettled([
          axios.get(`${API_BASE}/predictions`),
          axios.get(`${API_BASE}/real-results`),
        ])
        if (listResp.status === 'fulfilled') {
          const ids = (listResp.value.data.match_ids || []).filter(id =>
            CL_FIXTURES.some(f => f.match_id === id) || BL_FIXTURES.some(f => f.match_id === id)
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

      {page === 'home' && <MatchTicker />}

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
                <button
                  className={`competition-pill ${activeCompetition === 'cl' ? 'active' : ''}`}
                  onClick={() => switchCompetition('cl')}
                >
                  <img src="https://a.espncdn.com/i/leaguelogos/soccer/500-dark/2.png" alt="" />
                  Champions League
                </button>
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
                <button
                  className={`competition-pill ${activeCompetition === 'bl' ? 'active' : ''}`}
                  onClick={() => switchCompetition('bl')}
                >
                  <span className="competition-pill-emoji">🇩🇪</span>
                  Bundesliga
                </button>
              </div>

              <div className="group-tabs">
                {activeCompetition === 'cl' && (
                  <button
                    className={`group-tab special-tab ${activeGroup === 'next' ? 'active' : ''}`}
                    onClick={() => setActiveGroup('next')}
                  >
                    📅 Next Games
                  </button>
                )}
                {activeCompetition === 'cl' && (
                  <button
                    className={`group-tab special-tab ${activeGroup === 'hot' ? 'active' : ''}`}
                    onClick={() => setActiveGroup('hot')}
                  >
                    🔥 Hot Game
                  </button>
                )}
                {activeCompetition === 'cl' && (
                  <button
                    className={`group-tab special-tab ${activeGroup === 'best' ? 'active' : ''}`}
                    onClick={() => { setActiveGroup('best'); if (bestBets === null && !bestBetsLoading) loadBestBets() }}
                  >
                    ⭐ Best Bets
                  </button>
                )}
                <button
                  className={`group-tab special-tab ${activeGroup === 'combo' ? 'active' : ''}`}
                  onClick={() => { setActiveGroup('combo'); loadCombo(activeCompetition) }}
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

              {activeGroup === 'next' && NEXT_GAMES.length === 0 && (
                <p className="wm-subtle">No matches scheduled for today.</p>
              )}

              {activeGroup === 'hot' && (
                NEXT_GAMES.length === 0
                  ? <p className="wm-subtle">No matches scheduled for today.</p>
                  : <p className="wm-subtle hot-game-subtitle">🔥 Today's marquee matchup — the highest-ranked teams in action.</p>
              )}

              {activeGroup === 'best' && (
                <div className="best-bets-view">
                  <p className="best-bets-intro">
                    Our strongest value bets from the next matchday. Each one is a bet where the odds pay
                    <strong> more</strong> than the outcome's real chance — that's your edge. Place them as
                    <strong> single bets</strong> (not one combo slip). Tap any card for the full breakdown.
                  </p>
                  {bestBetsLoading && (
                    <div className="analyzing-status loading-inline">
                      <span className="analyzing-spinner" />
                      <span>Scanning the next games…</span>
                    </div>
                  )}
                  {!bestBetsLoading && bestBets && bestBets.length === 0 && (
                    <div className="best-bets-empty">
                      <strong>No clear bets right now.</strong> None of the next games offers a reliable edge —
                      the disciplined move is to sit this round out.
                      <button className="best-bets-refresh" onClick={loadBestBets}>↻ Refresh</button>
                    </div>
                  )}
                  {!bestBetsLoading && bestBets && bestBets.length > 0 && (
                    <div className="best-bets-cards">
                      {bestBets.map((b, i) => {
                        const r = b.rec
                        const dt = b.commence ? new Date(b.commence) : fixtureDateTime(b.fixture)
                        const when = dt.toLocaleString('en-GB', { weekday: 'short', hour: '2-digit', minute: '2-digit' })
                        return (
                          <button className="best-bet-card" key={i} onClick={() => goToMatchSmartBet(b.fixture)}>
                            <div className="best-bet-card-top">
                              <span className="best-bet-card-match">
                                <TeamLabel name={b.fixture.home_team} /> v <TeamLabel name={b.fixture.away_team} />
                              </span>
                              <span className="best-bet-card-when">{when}</span>
                            </div>
                            <div className="best-bet-card-pick">{plainBetPhrase(r)}</div>
                            <div className="best-bet-card-stats">
                              <span><span className="bb-stat-label">Odds</span> {r.best_odds.toFixed(2)}</span>
                              <span><span className="bb-stat-label">Edge</span> <span className={r.expected_value >= 0 ? 'positive' : 'negative'}>{r.expected_value >= 0 ? '+' : ''}{(r.expected_value * 100).toFixed(0)}%</span></span>
                              {r.selection_assessment && <span><span className="bb-stat-label">Paper stake</span> {r.selection_assessment.paper_stake_pct.toFixed(2)}% of test budget</span>}
                            </div>
                            <div className="best-bet-card-consensus">{b.consensusLabel}</div>
                            {b.agentEval && (
                              <div className="best-bet-card-agent">
                                ✨ {b.agentEval.agrees_with_model ? 'AI agrees' : 'AI sees it differently'} — {b.agentEval.bet_reasoning}
                              </div>
                            )}
                            <span className="best-bet-card-cta">View full analysis →</span>
                          </button>
                        )
                      })}
                    </div>
                  )}
                </div>
              )}

              {activeGroup === 'combo' && (
                <ComboTicketView combo={combo} loading={comboLoading} />
              )}

              <div className="fixtures-list">
                {(() => {
                  if (activeGroup === 'best' || activeGroup === 'combo') return null
                  let fixtures
                  if (activeCompetition === 'cl' && activeGroup === 'next') {
                    fixtures = NEXT_GAMES
                  } else if (activeCompetition === 'cl' && activeGroup === 'hot') {
                    const hotFixture = getHotFixture(predictionsById)
                    fixtures = hotFixture ? [hotFixture] : []
                  } else {
                    fixtures = currentFixtures.filter(f => f.group === activeGroup)
                  }
                  return fixtures.map(fixture => {
                    const realKey = `${fixture.home_team}__${fixture.away_team}`
                    const realResult = realResultsMap[realKey]
                    const aiData = predictionsById[fixture.match_id]

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
