import test from 'node:test'
import assert from 'node:assert/strict'
import { createComboCacheEntry, comboCacheIsCurrent } from '../src/comboCache.js'

const at = value => Date.parse(value)
const report = leg => ({ days: [{ by_size: [{ ticket: { legs: [leg] } }] }] })

test('cached prices expire after five minutes even without changing tabs', () => {
  const now = at('2026-10-31T12:00:00Z')
  const entry = createComboCacheEntry(report({ commence_time: '2026-10-31T18:30:00Z' }), now)
  assert.equal(entry.expiresAt, now + 300000)
  assert.ok(comboCacheIsCurrent(entry, now + 299999))
  assert.equal(comboCacheIsCurrent(entry, now + 300000), false)
})

test('kickoff, quote expiry and the final-hour refresh end the cache earlier', () => {
  const now = at('2026-10-31T12:00:00Z')
  for (const [leg, expected] of [
    [{ commence_time: '2026-10-31T12:02:00Z' }, '2026-10-31T12:02:00Z'],
    [{ commence_time: '2026-10-31T13:02:00Z' }, '2026-10-31T12:02:00Z'],
    [{ commence_time: '2026-10-31T15:00:00Z', snapshot_valid_until: '2026-10-31T12:01:00Z' }, '2026-10-31T12:01:00Z'],
  ]) assert.equal(createComboCacheEntry(report(leg), now).expiresAt, at(expected))
})

test('empty results expire at midnight Berlin or the daily odds refresh', () => {
  assert.equal(createComboCacheEntry({}, at('2026-10-31T22:59:00Z')).expiresAt, at('2026-10-31T23:00:00Z'))
  assert.equal(createComboCacheEntry({}, at('2026-07-01T21:59:00Z')).expiresAt, at('2026-07-01T22:00:00Z'))
  assert.equal(createComboCacheEntry({}, at('2026-10-31T05:59:00Z')).expiresAt, at('2026-10-31T06:00:00Z'))
})

test('an already started ticket is hidden and retries are bounded', () => {
  const now = at('2026-10-31T12:00:00Z')
  const entry = createComboCacheEntry(report({ commence_time: '2026-10-31T11:59:00Z' }), now)
  assert.deepEqual(entry.data, { error: true })
  assert.equal(entry.expiresAt, now + 60000)
})
