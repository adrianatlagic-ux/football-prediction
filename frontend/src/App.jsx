import { useState, useEffect } from 'react'
import axios from 'axios'
import './App.css'
import WC2026_FIXTURES from './wc2026_fixtures.json'
import FIFA_RANKINGS from './fifa_rankings.json'
import wc2026Logo from './assets/wc2026-logo.png'

const API_BASE = 'http://127.0.0.1:8000'

const GROUPS = [...new Set(WC2026_FIXTURES.map(f => f.group))].sort()

function todayStr() {
  const d = new Date()
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`
}

const TODAY = todayStr()
const TODAYS_FIXTURES = WC2026_FIXTURES.filter(f => f.date === TODAY).sort((a, b) => a.time.localeCompare(b.time))

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
  for (const fixture of TODAYS_FIXTURES) {
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

const TICKER_ICONS = {
  kickoff: '🟢',
  goal: '⚽',
  chance: '🔥',
  halftime: '⏸️',
  fulltime: '🏁',
}

function TeamLabel({ name }) {
  const flag = TEAM_FLAGS[name]
  return <>{flag && <span style={{ marginRight: '0.4em' }}>{flag}</span>}{name}</>
}

function ProbabilityBar({ label, value, color, animate }) {
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
      <span className="prob-value">{(value * 100).toFixed(1)}%</span>
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

function BettingMarkets({ data }) {
  const bm = (data.score_prediction || {}).betting_markets
  if (!bm) return null

  const home = data.home_team
  const away = data.away_team
  const { double_chance: dc, over_under: ou = [], win_margin: wm, btts } = bm

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

      <div>
        <h4>Double Chance</h4>
        <div className="market-grid">
          <div className="market-card">
            <div className="market-card-label"><TeamLabel name={home} /> or Draw</div>
            <div className="market-card-value">{(dc.home_or_draw * 100).toFixed(1)}%</div>
          </div>
          <div className="market-card">
            <div className="market-card-label"><TeamLabel name={home} /> or <TeamLabel name={away} /></div>
            <div className="market-card-value">{(dc.home_or_away * 100).toFixed(1)}%</div>
          </div>
          <div className="market-card">
            <div className="market-card-label">Draw or <TeamLabel name={away} /></div>
            <div className="market-card-value">{(dc.draw_or_away * 100).toFixed(1)}%</div>
          </div>
        </div>
      </div>

      <div>
        <h4>Total Goals (Over / Under)</h4>
        {ou.map(o => (
          <div className="over-under-row" key={o.line}>
            <span className="over-under-line">{o.line}</span>
            <div className="over-under-track">
              <div className="over-under-fill" style={{ width: `${o.over * 100}%` }} />
            </div>
            <span className="over-under-value">over {(o.over * 100).toFixed(1)}%</span>
          </div>
        ))}
      </div>

      <div className="market-card btts-card">
        <div className="market-card-label">Both Teams to Score</div>
        <div className="btts-split">
          <div className="btts-half">
            <div className="market-card-value">{(btts.yes * 100).toFixed(1)}%</div>
            <div className="market-card-sub">Yes</div>
          </div>
          <div className="btts-half">
            <div className="market-card-value">{(btts.no * 100).toFixed(1)}%</div>
            <div className="market-card-sub">No</div>
          </div>
        </div>
      </div>

      <div>
        <h4>If <TeamLabel name={favorite} /> win ({(margin1 * 100).toFixed(1)}%) — by how much?</h4>
        <div className="market-grid">
          <div className="market-card">
            <div className="market-card-label">1+ goal</div>
            <div className="market-card-value">{(margin1 * 100).toFixed(1)}%</div>
          </div>
          <div className="market-card">
            <div className="market-card-label">2+ goals</div>
            <div className="market-card-value">{(margin2 * 100).toFixed(1)}%</div>
          </div>
          <div className="market-card">
            <div className="market-card-label">3+ goals</div>
            <div className="market-card-value">{(margin3 * 100).toFixed(1)}%</div>
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
  'Calculating goal probabilities…',
  'Generating match flow scenarios…',
  'Finalizing the result…',
]

function HeadToHeadStat({ label, home, away, suffix = '' }) {
  const total = home + away
  const homePct = total > 0 ? (home / total) * 100 : 50
  return (
    <div className="h2h-row">
      <span className="h2h-value h2h-home">{home}{suffix}</span>
      <div className="h2h-mid">
        <span className="h2h-label">{label}</span>
        <div className="h2h-bar-track">
          <div className="h2h-bar-home" style={{ width: `${homePct}%` }} />
          <div className="h2h-bar-away" style={{ width: `${100 - homePct}%` }} />
        </div>
      </div>
      <span className="h2h-value h2h-away">{away}{suffix}</span>
    </div>
  )
}

function RevealSection({ visible, className = '', children }) {
  if (!visible) return null
  return <div className={`wm-reveal ${className}`}>{children}</div>
}

function WmPredictionCard({ matchId, data, fixture, onCollapse, revealStep = Infinity }) {
  const sp = data.score_prediction || {}
  const gf = data.game_flow || {}
  const ps = gf.predicted_stats || {}

  const analyzing = revealStep < ANALYZING_STEPS.length
  const show = (n) => revealStep >= n

  return (
    <div className="card wm-card">
      <div className="wm-card-header">
        <span className="wm-match-id">
          {fixture ? `${fixture.date} · ${fixture.time}` : matchId}
        </span>
        <div className="wm-card-header-right">
          {gf.match_type && show(4) && <span className="wm-match-type">{gf.match_type}</span>}
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
        <ProbabilityBar label={<TeamLabel name={data.home_team} />} value={data.probability_home_win} color="linear-gradient(90deg,var(--gold),var(--gold-light))" animate />
        <ProbabilityBar label="Draw" value={data.probability_draw} color="linear-gradient(90deg,#6b7280,#9ca3af)" animate />
        <ProbabilityBar label={<TeamLabel name={data.away_team} />} value={data.probability_away_win} color="linear-gradient(90deg,#ef4444,#f97316)" animate />
      </RevealSection>

      <RevealSection visible={show(2)}>
        <BettingMarkets data={data} />
      </RevealSection>

      <RevealSection visible={show(2)} className="explanation-grid wm-grid">
        <div className="stat-card">
          <h4>Most Likely Score</h4>
          <div className="wm-score-highlight">{sp.most_likely_score}</div>
          <p className="wm-subtle">xG: {sp.home_xg} : {sp.away_xg}</p>
          {(sp.top_scorelines || []).slice(0, 3).map((s, i) => (
            <div className="stat-row" key={i}>
              <span className="stat-label">{s.score}</span>
              <span className="stat-val">{(s.probability * 100).toFixed(1)}%</span>
            </div>
          ))}
        </div>

        <div className="stat-card">
          <h4>Halftime</h4>
          {(gf.top_halftime_scores || []).slice(0, 3).map((h, i) => (
            <div className="stat-row" key={i}>
              <span className="stat-label">{h.score}</span>
              <span className="stat-val">{(h.probability * 100).toFixed(1)}%</span>
            </div>
          ))}
          <div className="stat-row">
            <span className="stat-label">Late drama (75'+)</span>
            <span className="stat-val">{((gf.late_drama_probability || 0) * 100).toFixed(0)}%</span>
          </div>
        </div>
      </RevealSection>

      {ps.possession && (
        <RevealSection visible={show(3)} className="h2h-stats">
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
        <RevealSection visible={show(4)}>
          <p className="wm-description">{gf.match_description}</p>
        </RevealSection>
      )}

      {(gf.match_ticker || []).length > 0 && (
        <RevealSection visible={show(4)} className="wm-stories">
          <h4>Match Ticker</h4>
          {gf.match_ticker.map((e, i) => (
            <div className={`wm-ticker-event wm-ticker-${e.type}`} key={i}>
              <span className="wm-ticker-minute">{e.minute}'</span>
              <div className="wm-ticker-body">
                <div className="wm-ticker-head">
                  <span>{TICKER_ICONS[e.type] || '▪️'} {e.headline}</span>
                  {e.score_after && <span className="wm-ticker-score">{e.score_after}</span>}
                </div>
                <p>{e.description}</p>
              </div>
            </div>
          ))}
        </RevealSection>
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

export default function App() {
  const [page, setPage] = useState('home')
  const [predictionsById, setPredictionsById] = useState({})
  const [wmLoading, setWmLoading] = useState(true)
  const [activeGroup, setActiveGroup] = useState(GROUPS[0])
  const [analysisStep, setAnalysisStep] = useState({})

  function startAnalysis(matchId) {
    setAnalysisStep(prev => ({ ...prev, [matchId]: 0 }))
    let step = 0
    const interval = setInterval(() => {
      step += 1
      if (step >= ANALYZING_STEPS.length) {
        clearInterval(interval)
        setAnalysisStep(prev => ({ ...prev, [matchId]: Infinity }))
      } else {
        setAnalysisStep(prev => ({ ...prev, [matchId]: step }))
      }
    }, 1500)
  }

  function collapseAnalysis(matchId) {
    setAnalysisStep(prev => {
      const next = { ...prev }
      delete next[matchId]
      return next
    })
  }

  useEffect(() => {
    async function loadWmPredictions() {
      try {
        const list = await axios.get(`${API_BASE}/predictions`)
        const ids = (list.data.match_ids || []).filter(id =>
          WC2026_FIXTURES.some(f => f.match_id === id)
        )
        const all = await Promise.all(
          ids.map(id => axios.get(`${API_BASE}/predictions/${id}`).then(r => ({ matchId: id, data: r.data })))
        )
        const byId = {}
        all.forEach(({ matchId, data }) => { byId[matchId] = data })
        setPredictionsById(byId)
        setAnalysisStep(prev => {
          const next = { ...prev }
          Object.keys(byId).forEach(id => { next[id] = Infinity })
          return next
        })
      } catch (e) {
        // Backend may not have any cached predictions yet - not an error state
      } finally {
        setWmLoading(false)
      }
    }
    loadWmPredictions()
  }, [])

  return (
    <div className="app">
      <nav className="navbar">
        <div className="nav-brand" onClick={() => setPage('home')} role="button">
          <img src={wc2026Logo} alt="FIFA World Cup 2026" className="nav-logo" />
          <span className="nav-title">WC 2026 Predictor</span>
        </div>
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
                <img src={wc2026Logo} alt="FIFA World Cup 2026" className="hero-logo" />
                <span className="hero-eyebrow">A New Era of Football Intelligence</span>
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
                {GROUPS.map(g => (
                  <button
                    key={g}
                    className={`group-tab ${activeGroup === g ? 'active' : ''}`}
                    onClick={() => setActiveGroup(g)}
                  >
                    Group {g}
                  </button>
                ))}
              </div>

              {wmLoading && <p className="wm-subtle">Loading analyses…</p>}

              {activeGroup === 'next' && TODAYS_FIXTURES.length === 0 && (
                <p className="wm-subtle">No matches scheduled for today.</p>
              )}

              {activeGroup === 'hot' && (
                TODAYS_FIXTURES.length === 0
                  ? <p className="wm-subtle">No matches scheduled for today.</p>
                  : <p className="wm-subtle hot-game-subtitle">🔥 Today's marquee matchup — the highest-ranked teams in action.</p>
              )}

              <div className="fixtures-list">
                {(() => {
                  let fixtures
                  if (activeGroup === 'next') {
                    fixtures = TODAYS_FIXTURES
                  } else if (activeGroup === 'hot') {
                    const hotFixture = getHotFixture(predictionsById)
                    fixtures = hotFixture ? [hotFixture] : []
                  } else {
                    fixtures = WC2026_FIXTURES.filter(f => f.group === activeGroup)
                  }
                  return fixtures.map(fixture => {
                    const data = predictionsById[fixture.match_id]
                    if (!data) {
                      return <FixtureRow key={fixture.match_id} fixture={fixture} />
                    }
                    const step = analysisStep[fixture.match_id]
                    if (step === undefined) {
                      return (
                        <FixtureReadyRow
                          key={fixture.match_id}
                          fixture={fixture}
                          onGenerate={() => startAnalysis(fixture.match_id)}
                        />
                      )
                    }
                    return (
                      <WmPredictionCard
                        key={fixture.match_id}
                        matchId={fixture.match_id}
                        data={data}
                        fixture={fixture}
                        revealStep={step}
                        onCollapse={step === Infinity ? () => collapseAnalysis(fixture.match_id) : undefined}
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
