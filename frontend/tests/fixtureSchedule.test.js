import test from 'node:test'
import assert from 'node:assert/strict'
import { fixtureDateTime, nextGamesFor } from '../src/fixtureSchedule.js'

const fixture = (date, time = '20:30', group = 'Spieltag 7') => ({ date, time, group })

test('days without games show the next whole matchday in chronological order', () => {
  const rows = [fixture('2026-10-25'), fixture('2026-10-30', '20:30', 'Spieltag 8'),
    fixture('2026-10-23'), fixture('2026-10-24')]
  assert.deepEqual(nextGamesFor(rows, new Date('2026-10-22T12:00:00Z')), [rows[2], rows[3], rows[0]])
  assert.equal(rows[0].date, '2026-10-25') // caller's fixture list stays untouched
})

test('current day includes early matches and stays visible until 06:00 Berlin', () => {
  const rows = [fixture('2026-10-24', '13:30'), fixture('2026-10-24', '20:30'), fixture('2026-10-25')]
  assert.equal(nextGamesFor(rows, new Date('2026-10-24T10:00:00Z')).length, 2)
  assert.equal(nextGamesFor(rows, new Date('2026-10-25T02:00:00Z')).length, 2)
  assert.deepEqual(nextGamesFor(rows, new Date('2026-10-25T06:00:00Z')), [rows[2]])
})

test('Berlin kickoffs are independent of browser timezone and daylight saving', () => {
  assert.equal(fixtureDateTime(fixture('2026-10-24')).toISOString(), '2026-10-24T18:30:00.000Z')
  assert.equal(fixtureDateTime(fixture('2026-10-25')).toISOString(), '2026-10-25T19:30:00.000Z')
})

test('generic phase labels do not show the whole season; no invented future fixtures', () => {
  const rows = [fixture('2026-11-03', '20:30', 'League Phase'), fixture('2026-11-04', '20:30', 'League Phase'),
    fixture('2026-11-17', '20:30', 'League Phase')]
  assert.equal(nextGamesFor(rows, new Date('2026-10-22T12:00:00Z')).length, 2)
  assert.deepEqual(nextGamesFor(rows, new Date('2027-01-01T12:00:00Z')), [])
  assert.deepEqual(nextGamesFor([], new Date()), [])
  assert.deepEqual(nextGamesFor([fixture('invalid')], new Date()), [])
})
