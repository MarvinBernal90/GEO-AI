/**
 * ==============================================================================
 * NUMBER AND DATE FORMATTERS (Spanish)
 * ==============================================================================
 * File: frontend/src/utils/format.js
 *
 * Every function accepts null/undefined and returns an em dash, so a missing
 * value ("unknown", "no first token") is never shown as a misleading zero.
 */

const DASH = '—'

const integer = new Intl.NumberFormat('es-ES')
const compact = new Intl.NumberFormat('es-ES', { notation: 'compact', maximumFractionDigits: 1 })
const dateTime = new Intl.DateTimeFormat('es-ES', {
  day: '2-digit',
  month: 'short',
  hour: '2-digit',
  minute: '2-digit',
  second: '2-digit',
})
const day = new Intl.DateTimeFormat('es-ES', { day: '2-digit', month: 'short' })
const hourOfDay = new Intl.DateTimeFormat('es-ES', { hour: '2-digit', minute: '2-digit' })

const isNumber = (n) => typeof n === 'number' && Number.isFinite(n)

/** 12345 -> "12.345" */
export const formatNumber = (n) => (isNumber(n) ? integer.format(n) : DASH)

/** 12345 -> "12,3 mil" (for axis ticks and tiles) */
export const formatCompact = (n) => (isNumber(n) ? compact.format(n) : DASH)

/** 0.0734 -> "7,3 %" */
export function formatPercent(fraction, digits = 1) {
  if (!isNumber(fraction)) return DASH
  return `${(fraction * 100).toLocaleString('es-ES', { minimumFractionDigits: digits, maximumFractionDigits: digits })} %`
}

/** 850 -> "850 ms", 2340 -> "2,3 s", 95000 -> "1 min 35 s", 300000 -> "5 min" */
export function formatMs(ms) {
  if (!isNumber(ms)) return DASH
  if (ms < 1000) return `${Math.round(ms)} ms`
  if (ms < 60_000) return `${(ms / 1000).toLocaleString('es-ES', { maximumFractionDigits: 1 })} s`
  const minutes = Math.floor(ms / 60_000)
  const seconds = Math.round((ms % 60_000) / 1000)
  return seconds ? `${minutes} min ${seconds} s` : `${minutes} min`
}

/**
 * Cost in euros when the backend sends a rate, otherwise in dollars (the stored currency).
 * Prices are tiny per request, so small amounts keep four decimals.
 */
export function formatCost(usd, eurPerUsd = null) {
  if (!isNumber(usd)) return DASH
  const euros = isNumber(eurPerUsd) && eurPerUsd > 0
  const value = euros ? usd * eurPerUsd : usd
  const digits = Math.abs(value) < 1 ? 4 : 2
  return new Intl.NumberFormat('es-ES', {
    style: 'currency',
    currency: euros ? 'EUR' : 'USD',
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  }).format(value)
}

/** ISO string -> "22 oct, 14:03:07" in the viewer's time zone. */
export function formatDateTime(iso) {
  const date = new Date(iso)
  return Number.isNaN(date.getTime()) ? DASH : dateTime.format(date)
}

/** Label of a time-series bucket: hours show the time, days show the date. */
export function formatBucket(iso, bucket) {
  const date = new Date(iso)
  if (Number.isNaN(date.getTime())) return DASH
  return bucket === 'hour' ? `${day.format(date)} ${hourOfDay.format(date)}` : day.format(date)
}

/** Short trace id for tables: the full value stays in the title/tooltip. */
export const shortTrace = (id) => (id && id.length > 12 ? `${id.slice(0, 8)}…` : (id ?? DASH))
