// Formatting helpers. Times from the API are ISO strings that already carry the right offset
// (station time or ACN site time), so they are displayed as written - never re-zoned by the browser.

export const pct = (ratio, digits = 1) => (ratio == null ? '—' : `${(ratio * 100).toFixed(digits)}%`)
export const num = (v, digits = 2) => (v == null ? '—' : Number(v).toFixed(digits))

export function money(amount, currency = 'INR') {
  if (amount == null) return '—'
  return new Intl.NumberFormat('en-IN', { style: 'currency', currency, minimumFractionDigits: 2 }).format(amount)
}

/** "2030-01-16T10:00:00+05:30" -> "16 Jan 2030, 10:00" (wall-clock time as given) */
export function wallClock(iso, { date = true, time = true } = {}) {
  if (!iso) return '—'
  const m = /^(\d{4})-(\d{2})-(\d{2})(?:[T ](\d{2}):(\d{2}))?/.exec(iso)
  if (!m) return iso
  const months = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']
  const d = `${Number(m[3])} ${months[Number(m[2]) - 1]} ${m[1]}`
  const t = m[4] ? `${m[4]}:${m[5]}` : ''
  return [date && d, time && t].filter(Boolean).join(', ')
}

export const hhmm = (iso) => (iso ? iso.slice(11, 16) : '—')

export function offsetOf(iso) {
  const m = /([+-]\d{2}:\d{2}|Z)$/.exec(iso || '')
  return m ? (m[1] === 'Z' ? 'UTC' : `UTC${m[1]}`) : ''
}

/** Today's date (YYYY-MM-DD) in an IANA time zone. */
export function todayIn(timeZone) {
  return new Intl.DateTimeFormat('en-CA', { timeZone, year: 'numeric', month: '2-digit', day: '2-digit' }).format(new Date())
}

export function addDays(isoDate, days) {
  const d = new Date(`${isoDate}T00:00:00Z`)
  d.setUTCDate(d.getUTCDate() + days)
  return d.toISOString().slice(0, 10)
}

export const CONGESTION_STYLE = {
  LOW: { label: 'Low', cls: 'bg-emerald-100 text-emerald-800 ring-emerald-600/20', dot: 'bg-emerald-500' },
  MEDIUM: { label: 'Medium', cls: 'bg-amber-100 text-amber-800 ring-amber-600/20', dot: 'bg-amber-500' },
  HIGH: { label: 'High', cls: 'bg-orange-100 text-orange-800 ring-orange-600/20', dot: 'bg-orange-500' },
  VERY_HIGH: { label: 'Very high', cls: 'bg-rose-100 text-rose-800 ring-rose-600/20', dot: 'bg-rose-500' },
}
