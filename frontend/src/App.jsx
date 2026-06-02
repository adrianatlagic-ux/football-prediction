import { useState } from 'react'
import axios from 'axios'
import './App.css'

const TEAMS = [
  "France", "Spain", "Argentina", "England", "Portugal", "Brazil",
  "Netherlands", "Morocco", "Belgium", "Germany", "Croatia", "Italy",
  "Colombia", "Senegal", "Mexico", "United States", "Uruguay", "Japan",
  "Switzerland", "Denmark", "IR Iran", "Turkey", "Ecuador", "Austria",
  "South Korea", "Nigeria", "Australia", "Algeria", "Egypt", "Canada",
  "Norway", "Ukraine", "Panama", "Ivory Coast", "Poland", "Wales",
  "Sweden", "Serbia", "Paraguay", "Czech Republic", "Hungary", "Scotland",
  "Tunisia", "Cameroon", "DR Congo", "Greece", "Slovakia", "Venezuela",
  "Uzbekistan", "Qatar", "Iraq", "South Africa", "Saudi Arabia", "Jordan",
  "Bosnia and Herzegovina", "Cape Verde", "Ghana", "New Zealand", "Haiti", "Curacao"
].sort()

function ProbabilityBar({ label, value, color }) {
  return (
    <div className="prob-row">
      <span className="prob-label">{label}</span>
      <div className="prob-bar-track">
        <div className="prob-bar-fill" style={{ width: `${value * 100}%`, background: color }} />
      </div>
      <span className="prob-value">{(value * 100).toFixed(1)}%</span>
    </div>
  )
}

function StatCard({ title, rows }) {
  return (
    <div className="stat-card">
      <h4>{title}</h4>
      {rows.map(([label, val], i) => (
        <div className="stat-row" key={i}>
          <span className="stat-label">{label}</span>
          <span className="stat-val">{val}</span>
        </div>
      ))}
    </div>
  )
}

export default function App() {
  const [homeTeam, setHomeTeam] = useState('')
  const [awayTeam, setAwayTeam] = useState('')
  const [result, setResult] = useState(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState(null)

  async function predict() {
    if (!homeTeam || !awayTeam) return
    if (homeTeam === awayTeam) { setError('Bitte zwei verschiedene Teams wählen.'); return }
    setLoading(true); setError(null); setResult(null)
    try {
      const res = await axios.post('http://localhost:8000/predict', { home_team: homeTeam, away_team: awayTeam })
      setResult(res.data)
    } catch (e) {
      setError(e.response?.data?.detail || 'Fehler beim Laden der Vorhersage.')
    } finally {
      setLoading(false)
    }
  }

  const e = result?.explanation

  return (
    <div className="app">
      <header className="header">
        <div className="header-icon">⚽</div>
        <h1>WM 2026 Predictor</h1>
        <p>KI-gestützte Spielvorhersagen basierend auf echten Länderspielen</p>
      </header>

      <main className="main">
        <div className="card selector-card">
          <div className="team-selectors">
            <div className="team-select-group">
              <label>Heimteam</label>
              <select value={homeTeam} onChange={e => setHomeTeam(e.target.value)}>
                <option value="">Team wählen...</option>
                {TEAMS.map(t => <option key={t} value={t}>{t}</option>)}
              </select>
            </div>
            <div className="vs-badge">VS</div>
            <div className="team-select-group">
              <label>Auswärtsteam</label>
              <select value={awayTeam} onChange={e => setAwayTeam(e.target.value)}>
                <option value="">Team wählen...</option>
                {TEAMS.map(t => <option key={t} value={t}>{t}</option>)}
              </select>
            </div>
          </div>
          <button className="predict-btn" onClick={predict} disabled={!homeTeam || !awayTeam || loading}>
            {loading ? 'Analysiere...' : '⚡ Vorhersage starten'}
          </button>
          {error && <p className="error">{error}</p>}
        </div>

        {result && (
          <>
            <div className="card result-card">
              <div className="result-header">
                <span className="team-name">{result.home_team}</span>
                <div className="prediction-badge">
                  {result.prediction === 'H' ? `${result.home_team} gewinnt` :
                   result.prediction === 'A' ? `${result.away_team} gewinnt` : 'Unentschieden'}
                </div>
                <span className="team-name">{result.away_team}</span>
              </div>
              <div className="probabilities">
                <ProbabilityBar label={result.home_team} value={result.probability_home_win} color="linear-gradient(90deg,#3b82f6,#6366f1)" />
                <ProbabilityBar label="Unentschieden" value={result.probability_draw} color="linear-gradient(90deg,#6b7280,#9ca3af)" />
                <ProbabilityBar label={result.away_team} value={result.probability_away_win} color="linear-gradient(90deg,#ef4444,#f97316)" />
              </div>
            </div>

            {e && (
              <div className="explanation-grid">
                <StatCard title="🏆 FIFA-Ranking" rows={[
                  [result.home_team, `#${e.fifa_ranking[result.home_team]} · ${e.fifa_points[result.home_team]} Pkt`],
                  [result.away_team, `#${e.fifa_ranking[result.away_team]} · ${e.fifa_points[result.away_team]} Pkt`],
                ]} />
                <StatCard title="📈 Form (letzte 10)" rows={[
                  [result.home_team, `Ø ${e.form_last_10_avg_pts[result.home_team]} Pkt/Spiel · Siege ${e.win_rate_last_10[result.home_team]}`],
                  [result.away_team, `Ø ${e.form_last_10_avg_pts[result.away_team]} Pkt/Spiel · Siege ${e.win_rate_last_10[result.away_team]}`],
                ]} />
                <StatCard title="⚽ Tore (letzte 10)" rows={[
                  [`${result.home_team} geschossen`, e.avg_goals_scored[result.home_team]],
                  [`${result.home_team} kassiert`, e.avg_goals_conceded[result.home_team]],
                  [`${result.away_team} geschossen`, e.avg_goals_scored[result.away_team]],
                  [`${result.away_team} kassiert`, e.avg_goals_conceded[result.away_team]],
                ]} />
                <StatCard title="🔁 Head-to-Head" rows={Object.entries(e.h2h_last_10).map(([k, v]) => [k, String(v)])} />
              </div>
            )}
          </>
        )}
      </main>
    </div>
  )
}
