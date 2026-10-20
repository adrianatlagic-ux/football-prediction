// Fixture feeds carry Berlin wall-clock dates, regardless of browser timezone.
const berlinOffset = new Intl.DateTimeFormat('en-US', { timeZone: 'Europe/Berlin', timeZoneName: 'shortOffset' })
const berlinDate = new Intl.DateTimeFormat('sv-SE', { timeZone: 'Europe/Berlin' })
const berlinHour = new Intl.DateTimeFormat('en-GB', { timeZone: 'Europe/Berlin', hour: '2-digit', hourCycle: 'h23' })

export function fixtureDateTime(fixture) {
  const wall = Date.parse(`${fixture.date}T${fixture.time}:00Z`)
  if (!Number.isFinite(wall)) return new Date(NaN)
  const offset = instant => {
    const zone = berlinOffset.formatToParts(new Date(instant)).find(p => p.type === 'timeZoneName').value
    const match = zone.match(/GMT([+-])(\d+)(?::(\d+))?/)
    return match ? (match[1] === '+' ? 1 : -1) * (Number(match[2]) * 60 + Number(match[3] || 0)) * 60000 : 0
  }
  const guess = wall - offset(wall)
  return new Date(wall - offset(guess))
}

export function nextGamesFor(fixtures, now = new Date()) {
  const ordered = fixtures.filter(f => Number.isFinite(+fixtureDateTime(f)))
    .slice().sort((a, b) => fixtureDateTime(a) - fixtureDateTime(b))
  // Keep an evening's matches/results until 06:00 Berlin, including early kickoffs.
  let day = berlinDate.format(now)
  if (Number(berlinHour.format(now)) < 6) {
    day = new Date(Date.parse(`${day}T12:00:00Z`) - 86400000).toISOString().slice(0, 10)
  }
  const start = fixtureDateTime({ date: day, time: '06:00' })
  const tomorrow = new Date(Date.parse(`${day}T12:00:00Z`) + 86400000).toISOString().slice(0, 10)
  const end = fixtureDateTime({ date: tomorrow, time: '06:00' })
  const current = ordered.filter(f => fixtureDateTime(f) >= start && fixtureDateTime(f) < end)
  if (current.length) return current

  const upcoming = ordered.filter(f => fixtureDateTime(f) >= now)
  if (!upcoming.length) return []
  const first = upcoming[0]
  // Group by the next matchday, including a Fri–Mon Bundesliga weekend.
  // Bound generic phase labels (e.g. "League Phase") to four calendar days.
  const lastDay = new Date(Date.parse(`${first.date}T12:00:00Z`) + 3 * 86400000).toISOString().slice(0, 10)
  return upcoming.filter(f => f.group === first.group && f.date <= lastDay)
}
