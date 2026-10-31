import test from 'node:test'
import assert from 'node:assert/strict'
import { matchPath, parseRoute, sectionPath } from '../src/navigation.js'

test('league and section addresses restore the selected view', () => {
  for (const competition of ['cl', 'bl', 'nl']) {
    for (const group of ['next', 'hot', 'combo', 'Spieltag 8', 'Round of 16', 'Größe / Phase']) {
      assert.deepEqual(parseRoute(sectionPath(competition, group)), { page: 'home', competition, group })
    }
  }
  assert.deepEqual(parseRoute('/so-funktionierts'), { page: 'how-it-works' })
  assert.equal(parseRoute('/', '#how-it-works').page, 'how-it-works')
})

test('match links include the date and survive opening directly or reloading', () => {
  const fixture = { date: '2026-10-31', match_id: 'bayern_munich_vs_borussia_dortmund_bl' }
  const path = matchPath('bl', fixture)
  assert.equal(path, '/bundesliga/spiel/2026-10-31/bayern_munich_vs_borussia_dortmund_bl')
  assert.deepEqual(parseRoute(path), { page: 'home', competition: 'bl', group: 'next',
    matchDate: fixture.date, matchId: fixture.match_id })
})

test('unknown and malformed addresses do not open a different match', () => {
  for (const path of ['/unknown', '/bundesliga/nope', '/bundesliga/spiel/no-date/id', '/bundesliga/spieltag/%XX']) {
    assert.deepEqual(parseRoute(path), { page: 'not-found' })
  }
  assert.equal(parseRoute('/bundesliga/').competition, 'bl')
})
