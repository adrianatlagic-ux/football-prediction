const COMPETITION_PATHS = { cl: 'champions-league', bl: 'bundesliga', nl: 'nations-league' }
const GROUP_PATHS = { next: '', hot: 'topspiele', combo: 'kombis' }

export function sectionPath(competition = 'cl', group = 'next') {
  const base = `/${COMPETITION_PATHS[competition] || COMPETITION_PATHS.cl}`
  const suffix = GROUP_PATHS[group] ?? `spieltag/${encodeURIComponent(group)}`
  return suffix ? `${base}/${suffix}` : base
}

export function matchPath(competition, fixture) {
  return `${sectionPath(competition)}/spiel/${fixture.date}/${encodeURIComponent(fixture.match_id)}`
}

export function parseRoute(pathname, hash = '') {
  const home = { page: 'home', competition: 'cl', group: 'next' }
  if (pathname === '/' || pathname === '') return hash === '#how-it-works' ? { page: 'how-it-works' } : home
  const parts = pathname.replace(/\/$/, '').split('/').slice(1)
  if (parts.length === 1 && parts[0] === 'so-funktionierts') return { page: 'how-it-works' }
  const competition = Object.keys(COMPETITION_PATHS).find(key => COMPETITION_PATHS[key] === parts[0])
  if (!competition) return { page: 'not-found' }
  if (parts.length === 1) return { ...home, competition }
  const group = Object.keys(GROUP_PATHS).find(key => GROUP_PATHS[key] === parts[1])
  if (parts.length === 2 && group) return { ...home, competition, group }
  try {
    if (parts.length === 3 && parts[1] === 'spieltag') {
      return { ...home, competition, group: decodeURIComponent(parts[2]) }
    }
    if (parts.length === 4 && parts[1] === 'spiel' && /^\d{4}-\d{2}-\d{2}$/.test(parts[2])) {
      return { ...home, competition, matchDate: parts[2], matchId: decodeURIComponent(parts[3]) }
    }
  } catch { /* Invalid escaped paths are shown as unavailable. */ }
  return { page: 'not-found' }
}
