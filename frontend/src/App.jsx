import { useState, useEffect } from 'react'
import axios from 'axios'
import './App.css'
import WC2026_FIXTURES from './wc2026_fixtures.json'
import FIFA_RANKINGS from './fifa_rankings.json'
import wc2026Logo from './assets/wc2026-logo.png'

const API_BASE = import.meta.env.DEV ? 'http://127.0.0.1:8000' : ''

const GROUPS = [...new Set(WC2026_FIXTURES.map(f => f.group))].sort()

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
const NEXT_GAMES = WC2026_FIXTURES
  .filter(f => { const d = fixtureDateTime(f); return d >= _NG_START && d < _NG_END })
  .sort((a, b) => fixtureDateTime(a) - fixtureDateTime(b))

const WORST_RANK = Math.max(...Object.values(FIFA_RANKINGS))

// Higher value = stronger team (rank 1 -> highest score)
function teamStrength(team) {
  const rank = FIFA_RANKINGS[team] || WORST_RANK
  return WORST_RANK + 1 - rank
}

// How much "star power" a matchup has, based on both teams' FIFA rankings
function matchQuality(fixture) {
  return teamStrength(fixture.home_team) + teamStrength(fixture.away_team)
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
function getHotFixture(predictionsById) {
  let best = null
  let bestScore = -Infinity
  for (const fixture of NEXT_GAMES) {
    const data = predictionsById[fixture.match_id]
    const score = matchQuality(fixture) * 3 + (data ? excitementScore(data) : 0)
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
  const flag = TEAM_FLAGS[name]
  return <>{flag && <span style={{ marginRight: '0.4em' }}>{flag}</span>}{name}</>
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

function renderScenario(text, home, away) {
  const terms = [home, away, '2+ goals', '3+ goals', 'high-scoring game', 'low-scoring game']
  const escaped = terms.map(t => t.replace(/[.*+?^${}()|[\]\\]/g, '\\$&'))
  const parts = text.split(new RegExp(`(${escaped.join('|')})`, 'g'))
  return parts.map((part, i) =>
    terms.includes(part)
      ? <span className="scenario-highlight" key={i}>{part}</span>
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

  return (
    <div className="form-rating-box">
      <h4>Form Rating</h4>
      <div className="form-rating-row">
        <span className="form-rating-label">
          <TeamLabel name={home} />{homeBetter && <span className="form-rating-flame">🔥</span>}
        </span>
        <div className="form-rating-track">
          <div className="form-rating-fill" style={{ width: `${homeRating}%`, background: "linear-gradient(90deg,var(--gold),var(--gold-light))" }} />
        </div>
        <span className="form-rating-value">{homeRating}</span>
      </div>
      <p className="form-rating-detail">
        {explanation.form_last_10_avg_pts[home]} pts/game &middot; {explanation.avg_goals_scored[home]} scored &middot; {explanation.avg_goals_conceded[home]} conceded &middot; {explanation.clean_sheet_rate[home]} clean sheets
      </p>

      <div className="form-rating-row">
        <span className="form-rating-label">
          <TeamLabel name={away} />{!homeBetter && <span className="form-rating-flame">🔥</span>}
        </span>
        <div className="form-rating-track">
          <div className="form-rating-fill" style={{ width: `${awayRating}%`, background: "linear-gradient(90deg,#ef4444,#f97316)" }} />
        </div>
        <span className="form-rating-value">{awayRating}</span>
      </div>
      <p className="form-rating-detail">
        {explanation.form_last_10_avg_pts[away]} pts/game &middot; {explanation.avg_goals_scored[away]} scored &middot; {explanation.avg_goals_conceded[away]} conceded &middot; {explanation.clean_sheet_rate[away]} clean sheets
      </p>
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
      <div className="scenario-box">
        <h4>Most Likely Scenario</h4>
        <p>{renderScenario(bm.scenario, home, away)}</p>
      </div>

      <FormRating data={data} />

      {dc && (
        <div>
          <h4>Double Chance</h4>
          <div className="market-grid">
            <div className="market-card">
              <div className="market-card-label"><TeamLabel name={home} /> or Draw</div>
              <div className="market-card-value"><AnimatedNumber value={dc.home_or_draw * 100} decimals={1} suffix="%" /></div>
            </div>
            <div className="market-card">
              <div className="market-card-label"><TeamLabel name={home} /> or <TeamLabel name={away} /></div>
              <div className="market-card-value"><AnimatedNumber value={dc.home_or_away * 100} decimals={1} suffix="%" /></div>
            </div>
            <div className="market-card">
              <div className="market-card-label">Draw or <TeamLabel name={away} /></div>
              <div className="market-card-value"><AnimatedNumber value={dc.draw_or_away * 100} decimals={1} suffix="%" /></div>
            </div>
          </div>
        </div>
      )}

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

function SmartBetCard({ betStep, betInfo }) {
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

  const best = betInfo.recommendation
  const recWarning = betInfo.recommendation_warning
  const agentEval = betInfo.agent_eval
  const agentPick = agentEval && agentEval.pick
  const sameBet = (a, b) => a.market === b.market && a.outcome === b.outcome && a.team === b.team
  const greens = betInfo.green_bets || []
  const reds = betInfo.red_bets || []

  const renderRow = (b, i, kind) => {
    const isRec = best && sameBet(b, best)
    const isAgentPick = agentPick && sameBet(b, agentPick)
    return (
      <div className={`smart-bet-table-row ${kind === 'red' ? 'is-red' : ''} ${isRec ? 'is-rec' : ''}`} key={`${kind}-${i}`}>
        <span className="smart-bet-col-market">{marketGroupLabel(b.market)}{b.suspicious ? ' ⚠' : ''}</span>
        <span className="smart-bet-col-pick">{isRec ? '★ ' : ''}{isAgentPick ? '✨ ' : ''}{betOutcomeLabel(b)}</span>
        <span className="smart-bet-col-odds">{b.best_odds.toFixed(2)}</span>
        <span className={`smart-bet-col-edge ${b.expected_value >= 0 ? 'positive' : 'negative'}`}>
          {b.expected_value >= 0 ? '+' : ''}{(b.expected_value * 100).toFixed(0)}%
        </span>
        <span className="smart-bet-col-stake">{b.expected_value > 0 ? `${b.kelly_stake_pct}%` : '–'}</span>
      </div>
    )
  }

  return (
    <div className="wm-reveal smart-bet-card">
      {best ? (
        <div className={`smart-bet-best ${recWarning ? 'is-warning' : ''}`}>
          <span className="smart-bet-label">Top Recommendation</span>
          <div className="smart-bet-pick">{betOutcomeLabel(best)}</div>
          <div className="smart-bet-odds-row">
            <span className="smart-bet-odds">{best.best_odds.toFixed(2)}</span>
            <span className="smart-bet-edge positive">
              +{(best.expected_value * 100).toFixed(0)}% edge
            </span>
          </div>
          <div className="smart-bet-best-meta">
            at {best.bookmaker} · model estimates {(best.probability * 100).toFixed(0)}%
            {best.market_probability != null && `, market estimates ${(best.market_probability * 100).toFixed(0)}%`}
          </div>
          {recWarning ? (
            <div className="smart-bet-warning">
              ⚠ High edge with a large deviation from the market — likely a model weakness, not a real tip.
              Treat with caution.
            </div>
          ) : best.kelly_stake_pct > 0 && (
            <div className="smart-bet-kelly">
              Recommended stake: <strong>{best.kelly_stake_pct}%</strong> of your bankroll (Quarter-Kelly)
            </div>
          )}
        </div>
      ) : (
        <p className="smart-bet-notip">
          <strong>No clear tip for this match.</strong><br />
          No bet offers an edge here — better to sit this one out. Odds below for comparison.
        </p>
      )}

      {(greens.length > 0 || reds.length > 0) && (
        <div className="smart-bet-table">
          <div className="smart-bet-table-head">
            <span>Market</span>
            <span>Tip</span>
            <span>Odds</span>
            <span>Edge</span>
            <span>Stake</span>
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
          {agentPick && (
            <span className="smart-bet-agent-agree">
              {agentEval.agrees_with_model ? '✓ agrees with the model' : '↔ differs from the model'}
            </span>
          )}
          <p className="smart-bet-agent-text">{agentEval.bet_reasoning}</p>
          {agentEval.bet_points.length > 0 && (
            <ul className="smart-bet-agent-points">
              {agentEval.bet_points.map((p, i) => <li key={i}>{p}</li>)}
            </ul>
          )}
        </div>
      )}

      <div className="smart-bet-finePrint">
        <p><strong>★</strong> top pick by edge. <strong>✨</strong> AI agent's own pick after live research — may agree or differ.</p>

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

      <RevealSection visible={show(1)} className="probabilities">
        {(() => {
          const probs = [data.probability_home_win, data.probability_draw, data.probability_away_win]
          const maxProb = Math.max(...probs)
          const grayColor = "linear-gradient(90deg,#6b7280,#9ca3af)"
          const winColor = "linear-gradient(90deg,var(--gold),var(--gold-light))"
          const goldText = "var(--gold-light)"
          return (
            <>
              <ProbabilityBar label={<TeamLabel name={data.home_team} />} value={data.probability_home_win} color={data.probability_home_win === maxProb ? winColor : grayColor} valueColor={data.probability_home_win === maxProb ? goldText : undefined} animate />
              <ProbabilityBar label="Draw" value={data.probability_draw} color={data.probability_draw === maxProb ? winColor : grayColor} valueColor={data.probability_draw === maxProb ? goldText : undefined} animate />
              <ProbabilityBar label={<TeamLabel name={data.away_team} />} value={data.probability_away_win} color={data.probability_away_win === maxProb ? winColor : grayColor} valueColor={data.probability_away_win === maxProb ? goldText : undefined} animate />
            </>
          )
        })()}
      </RevealSection>

      <RevealSection visible={show(2)}>
        <BettingMarkets data={data} />
      </RevealSection>

      <RevealSection visible={show(3)} className="explanation-grid wm-grid">
        <div className="stat-card">
          <h4>Most Likely Score</h4>
          <div className="wm-score-highlight">{sp.most_likely_score}</div>
          <p className="wm-subtle">
            xG: <AnimatedNumber value={sp.home_xg} decimals={2} /> : <AnimatedNumber value={sp.away_xg} decimals={2} />
          </p>
          {(sp.top_scorelines || []).slice(0, 3).map((s, i) => (
            <div className="stat-row" key={i}>
              <span className="stat-label">{s.score}</span>
              <span className="stat-val"><AnimatedNumber value={s.probability * 100} decimals={1} suffix="%" /></span>
            </div>
          ))}
        </div>

        <div className="stat-card">
          <h4>Halftime</h4>
          {(gf.top_halftime_scores || []).slice(0, 3).map((h, i) => (
            <div className="stat-row" key={i}>
              <span className="stat-label">{h.score}</span>
              <span className="stat-val"><AnimatedNumber value={h.probability * 100} decimals={1} suffix="%" /></span>
            </div>
          ))}
          <div className="stat-row">
            <span className="stat-label">Late drama (75'+)</span>
            <span className="stat-val"><AnimatedNumber value={(gf.late_drama_probability || 0) * 100} decimals={0} suffix="%" /></span>
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

      {gf.match_description && (
        <RevealSection visible={show(5)}>
          <p className="wm-description">{gf.match_description}</p>
        </RevealSection>
      )}

      {!analyzing && betInfo && betInfo.agent_eval && betInfo.agent_eval.research && (
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

      {!analyzing && onStartBetCheck && (
        <div className="smart-bet-section">
          {betStep === undefined ? (
            <button className="fixture-generate-btn smart-bet-btn" onClick={onStartBetCheck}>
              Smart Bet Tip
            </button>
          ) : (
            <SmartBetCard betStep={betStep} betInfo={betInfo} />
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

function HeroPreviewCard() {
  return (
    <div className="hero-preview card">
      <div className="hero-preview-badge">AI Prediction</div>
      <div className="hero-preview-teams">
        <span className="hero-preview-team">Brazil</span>
        <span className="hero-preview-vs">vs</span>
        <span className="hero-preview-team">Argentina</span>
      </div>
      <div className="hero-preview-score">2 – 1</div>
      <div className="hero-preview-bars">
        <ProbabilityBar label="Brazil" value={0.48} color="linear-gradient(90deg,var(--gold),var(--gold-light))" />
        <ProbabilityBar label="Draw" value={0.24} color="linear-gradient(90deg,#6b7280,#9ca3af)" />
        <ProbabilityBar label="Argentina" value={0.28} color="linear-gradient(90deg,#ef4444,#f97316)" />
      </div>
      <p className="hero-preview-note">
        "Expect a tight first half — Brazil's pace on the counter breaks the deadlock after 60'."
      </p>
    </div>
  )
}

const FLOW_STEPS = [
  {
    icon: <IconDataPoints />,
    title: 'Data Ingestion',
    description:
      'Every analysis starts with decades of raw football history — international match ' +
      'results since the 1990s, full datasets from the 2018 and 2022 World Cups, official FIFA ' +
      'rankings, current squad market values and recent form for all 48 World Cup 2026 nations.',
    tags: ['Historical Results', 'FIFA Rankings', 'Market Values', 'Recent Form'],
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

function AnalysisFlowPage({ onBack }) {
  return (
    <section className="card flow-section">
      <span className="how-eyebrow">Behind the Predictions</span>
      <h2 className="section-title">How Our AI Analysis Works</h2>
      <p className="how-intro">
        From the first raw data point to the final social media post — every World Cup 2026
        prediction passes through the same seven-stage pipeline. Here's what happens behind the
        scenes every time a match gets analyzed.
      </p>

      <div className="flow-diagram">
        {FLOW_STEPS.map((step, i) => (
          <div className="flow-step-wrap" key={step.title}>
            <div className="flow-step">
              <div className="flow-step-marker">
                <span className="flow-step-icon">{step.icon}</span>
                <span className="flow-step-number">{i + 1}</span>
              </div>
              <div className="flow-step-content">
                <h3>{step.title}</h3>
                <p>{step.description}</p>
                <div className="flow-step-tags">
                  {step.tags.map(tag => (
                    <span className="flow-tag" key={tag}>{tag}</span>
                  ))}
                </div>
              </div>
            </div>
            {i < FLOW_STEPS.length - 1 && (
              <div className="flow-connector"><IconArrowDown /></div>
            )}
          </div>
        ))}
      </div>

      <button className="flow-back-btn" onClick={onBack}>← Back to Predictions</button>
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

  const HIT = 'linear-gradient(90deg,#16a34a,#4ade80)'
  const MISS_HOME = 'linear-gradient(90deg,var(--gold),var(--gold-light))'
  const MISS_DRAW = 'linear-gradient(90deg,#6b7280,#9ca3af)'
  const MISS_AWAY = 'linear-gradient(90deg,#ef4444,#f97316)'

  return (
    <div className="ai-prediction-inner">
      <p className="wm-subtle" style={{ marginBottom: '0.9rem', fontSize: '0.75rem' }}>Pre-match AI prediction</p>

      {/* Winner probabilities */}
      <div className="probabilities">
        <ProbabilityBar label={<TeamLabel name={aiData.home_team} />} value={aiData.probability_home_win} color={homeCorrect ? HIT : MISS_HOME} />
        <ProbabilityBar label="Draw" value={aiData.probability_draw} color={drawCorrect ? HIT : MISS_DRAW} />
        <ProbabilityBar label={<TeamLabel name={aiData.away_team} />} value={aiData.probability_away_win} color={awayCorrect ? HIT : MISS_AWAY} />
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
  const [activeGroup, setActiveGroup] = useState(GROUPS[0])
  const [analysisStep, setAnalysisStep] = useState({})
  const [bestBets, setBestBets] = useState(null)  // null = not loaded, [] = loaded empty
  const [bestBetsLoading, setBestBetsLoading] = useState(false)

  async function loadBestBets() {
    setBestBetsLoading(true)
    const games = NEXT_GAMES.filter(f => predictionsById[f.match_id])
    try {
      const results = await Promise.all(games.map(f =>
        axios.get(`${API_BASE}/value-bets`, { params: { home_team: f.home_team, away_team: f.away_team } })
          .then(r => ({ fixture: f, data: r.data })).catch(() => null)
      ))
      const clean = results
        .filter(x => x && x.data.odds_found && x.data.recommendation && !x.data.recommendation_warning)
        .map(x => ({
          fixture: x.fixture,
          rec: x.data.recommendation,
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
            WC2026_FIXTURES.some(f => f.match_id === id)
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

      {page === 'home' && (
        <>
          <header className="hero">
            <HeroVisual />
            <div className="hero-grid">
              <div className="hero-content">
                <div className="hero-top">
                  <img src={wc2026Logo} alt="FIFA World Cup 2026" className="hero-logo" />
                  <span className="hero-eyebrow">A New Era of Football Intelligence</span>
                </div>
                <h1>AI-Powered World Cup 2026 Predictions</h1>
                <p>
                  A breakthrough AI model — trained on millions of football data points — delivers
                  instant, in-depth analysis for every World Cup 2026 fixture: match outcomes,
                  scorelines and full match storylines, generated like never before.
                </p>
                <div className="hero-stats">
                  <div className="hero-stat">
                    <span className="hero-stat-value">Millions</span>
                    <span className="hero-stat-label">Data Points Analyzed</span>
                  </div>
                  <div className="hero-stat">
                    <span className="hero-stat-value">72</span>
                    <span className="hero-stat-label">Group Stage Matches</span>
                  </div>
                  <div className="hero-stat">
                    <span className="hero-stat-value">48</span>
                    <span className="hero-stat-label">Teams</span>
                  </div>
                  <div className="hero-stat">
                    <span className="hero-stat-value">12</span>
                    <span className="hero-stat-label">Groups</span>
                  </div>
                </div>
              </div>
              <HeroPreviewCard />
            </div>
          </header>

          <main className="main">
            <section id="predictions" className="wm-section">
              <h2 className="section-title">World Cup 2026 — Group Stage</h2>

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
                  className={`group-tab special-tab ${activeGroup === 'best' ? 'active' : ''}`}
                  onClick={() => { setActiveGroup('best'); if (bestBets === null && !bestBetsLoading) loadBestBets() }}
                >
                  ⭐ Best Bets
                </button>
                {GROUPS.map(g => (
                  <button
                    key={g}
                    className={`group-tab ${activeGroup === g ? 'active' : ''}`}
                    onClick={() => setActiveGroup(g)}
                  >
                    {g.length === 1 ? `Group ${g}` : g}
                  </button>
                ))}
              </div>

              {wmLoading && <p className="wm-subtle">Loading analyses…</p>}

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
                  {bestBetsLoading && <p className="wm-subtle">Scanning the next games…</p>}
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
                              <span><span className="bb-stat-label">Edge</span> <span className="positive">+{(r.expected_value * 100).toFixed(0)}%</span></span>
                              <span><span className="bb-stat-label">Stake</span> {r.kelly_stake_pct}% of budget</span>
                            </div>
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

              <div className="fixtures-list">
                {(() => {
                  if (activeGroup === 'best') return null
                  let fixtures
                  if (activeGroup === 'next') {
                    fixtures = NEXT_GAMES
                  } else if (activeGroup === 'hot') {
                    const hotFixture = getHotFixture(predictionsById)
                    fixtures = hotFixture ? [hotFixture] : []
                  } else {
                    fixtures = WC2026_FIXTURES.filter(f => f.group === activeGroup)
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
        <p>WC 2026 Predictor — AI-generated predictions for entertainment purposes only.</p>
      </footer>
    </div>
  )
}
