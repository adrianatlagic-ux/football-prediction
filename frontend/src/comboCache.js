import { fixtureDateTime } from './fixtureSchedule.js'

const MAX_AGE_MS = 5 * 60 * 1000
const RETRY_AFTER_MS = 60 * 1000
const berlinDate = new Intl.DateTimeFormat('sv-SE', { timeZone: 'Europe/Berlin' })

export function comboCacheIsCurrent(entry, now) {
  return Boolean(entry && now < entry.expiresAt)
}

export function createComboCacheEntry(report, fetchedAt) {
  const day = berlinDate.format(new Date(fetchedAt))
  const tomorrow = new Date(Date.parse(`${day}T12:00:00Z`) + 86400000).toISOString().slice(0, 10)
  const dailyRead = new Date(fetchedAt)
  dailyRead.setUTCHours(6, 0, 0, 0)
  if (+dailyRead <= fetchedAt) dailyRead.setUTCDate(dailyRead.getUTCDate() + 1)
  let expiresAt = Math.min(fetchedAt + MAX_AGE_MS, +dailyRead, +fixtureDateTime({ date: tomorrow, time: '00:00' }))
  const tickets = [report.recommended, ...(report.alternatives || []), ...(report.days || []).flatMap(day =>
    (day.by_size || []).flatMap(size => [size.ticket, size.near_miss]))]
  const legs = tickets.flatMap(ticket => ticket?.legs || []).concat((report.days || []).flatMap(day => day.legs || []))
  for (const leg of legs) {
    const kickoff = Date.parse(leg.commence_time)
    const quoteExpiry = Date.parse(leg.snapshot_valid_until)
    // An unexpectedly stale server response must not be displayed or cause
    // an immediate retry loop. Show unavailable and retry after one minute.
    if (kickoff <= fetchedAt || quoteExpiry <= fetchedAt) {
      return { data: { error: true }, expiresAt: fetchedAt + RETRY_AFTER_MS }
    }
    for (const boundary of [kickoff, kickoff - 3600000, quoteExpiry]) {
      if (boundary > fetchedAt) expiresAt = Math.min(expiresAt, boundary)
    }
  }
  if (report.error) expiresAt = Math.min(expiresAt, fetchedAt + RETRY_AFTER_MS)
  return { data: report, expiresAt }
}
