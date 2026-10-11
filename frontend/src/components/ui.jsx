import { CONGESTION_STYLE } from '../format.js'

export function Card({ title, subtitle, actions, children, className = '' }) {
  return (
    <section className={`rounded-2xl border border-slate-200/80 bg-white shadow-sm ${className}`}>
      {(title || actions) && (
        <header className="flex flex-wrap items-start justify-between gap-3 px-5 pt-5">
          <div>
            {title && <h2 className="text-base font-semibold text-slate-900">{title}</h2>}
            {subtitle && <p className="mt-0.5 text-sm text-slate-500">{subtitle}</p>}
          </div>
          {actions}
        </header>
      )}
      <div className="p-5">{children}</div>
    </section>
  )
}

export function Stat({ label, value, hint, tone = 'default' }) {
  const tones = { default: 'text-slate-900', good: 'text-emerald-700', accent: 'text-violet-700' }
  return (
    <div className="rounded-xl border border-slate-200 bg-white p-4">
      <p className="text-xs font-medium uppercase tracking-wide text-slate-500">{label}</p>
      <p className={`mt-1 text-2xl font-semibold tabular-nums ${tones[tone]}`}>{value}</p>
      {hint && <p className="mt-1 text-xs text-slate-500">{hint}</p>}
    </div>
  )
}

/** Demand level as a vibe badge: Chill / Kinda busy / Busy / Packed. */
export function CongestionBadge({ level, large = false }) {
  const s = CONGESTION_STYLE[level]
  if (!s) return null
  return (
    <span
      className={`inline-flex items-center gap-1 whitespace-nowrap rounded-full px-2.5 py-0.5 font-medium ring-1 ring-inset ${s.cls} ${large ? 'text-sm' : 'text-xs'}`}
      title={`Demand level: ${level.replace('_', ' ').toLowerCase()}`}
    >
      <span aria-hidden>{s.emoji}</span>
      {s.label}
    </span>
  )
}

export function ReplayBadge() {
  return (
    <span className="inline-flex items-center rounded-full bg-violet-50 px-2.5 py-0.5 text-xs font-medium text-violet-700 ring-1 ring-inset ring-violet-600/20">
      Historical replay · not live
    </span>
  )
}

export function Spinner({ label = 'Loading…' }) {
  return (
    <div className="flex items-center gap-2 py-6 text-sm text-slate-500" role="status">
      <span className="h-4 w-4 animate-spin rounded-full border-2 border-slate-300 border-t-violet-600" />
      {label}
    </div>
  )
}

// Backend problem titles -> friendly headlines. 4xx details from the backend are already plain
// English and are shown; server/connection details are technical and are replaced.
const FRIENDLY = {
  'Duplicate booking': 'You already booked this one 👍',
  'Slot unavailable': 'Aw, that slot just filled up',
  'Price changed': 'Heads up: the price just changed',
  'Cancellation not allowed': 'Too late to cancel this one',
  'Validation failed': 'Almost there — check your details',
  'Booking rejected': "That slot can't be booked",
  'Invalid request': "That date doesn't work",
  'Not found': "Couldn't find that",
}

function friendly(error) {
  const p = error.problem || {}
  if (error.status === 0 || error.status === 502 || error.status === 504) {
    return { title: "Can't reach the server 📡", detail: 'Check that the app is running and try again.' }
  }
  if (error.status === 503) {
    return { title: 'Prices are taking a quick nap 😴', detail: "We couldn't work out a price right now. Try again in a moment." }
  }
  if (error.status >= 500) {
    return { title: 'Something broke on our side', detail: 'Please try again.' }
  }
  return { title: FRIENDLY[p.title] ?? p.title ?? 'Something went wrong', detail: error.message }
}

const FIELD_NAMES = { customerName: 'Name', stationId: 'Station', startTime: 'Slot', quotedFinalPrice: 'Price' }

export function ErrorBox({ error, onRetry }) {
  if (!error) return null
  const p = error.problem || {}
  const f = friendly(error)
  return (
    <div className="rounded-xl border border-rose-200 bg-rose-50 p-4 text-sm text-rose-800" role="alert">
      <p className="font-semibold">{f.title}</p>
      {f.detail && <p className="mt-1">{f.detail}</p>}
      {p.errors && (
        <ul className="mt-2 list-inside list-disc">
          {Object.entries(p.errors).map(([field, msg]) => (
            <li key={field}>
              {FIELD_NAMES[field] ?? field}: {msg}
            </li>
          ))}
        </ul>
      )}
      {onRetry && (
        <button onClick={onRetry} className="mt-3 rounded-full bg-white px-3 py-1.5 text-xs font-medium text-rose-700 ring-1 ring-rose-300 hover:bg-rose-100">
          Try again
        </button>
      )}
    </div>
  )
}

export function Button({ children, variant = 'primary', className = '', ...props }) {
  const v = {
    primary:
      'bg-gradient-to-r from-violet-600 to-fuchsia-600 text-white hover:from-violet-500 hover:to-fuchsia-500 disabled:from-slate-300 disabled:to-slate-300 disabled:text-white',
    secondary: 'bg-white text-slate-700 ring-1 ring-inset ring-slate-300 hover:bg-slate-50 disabled:text-slate-400',
  }
  return (
    <button
      className={`inline-flex items-center justify-center gap-2 rounded-full px-4 py-2 text-sm font-semibold shadow-sm transition focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-violet-600 disabled:cursor-not-allowed ${v[variant]} ${className}`}
      {...props}
    >
      {children}
    </button>
  )
}

export function Field({ label, hint, children }) {
  return (
    <label className="block">
      <span className="text-xs font-medium text-slate-600">{label}</span>
      <div className="mt-1">{children}</div>
      {hint && <span className="mt-1 block text-xs text-slate-500">{hint}</span>}
    </label>
  )
}

export const inputCls =
  'block w-full rounded-xl border-0 bg-white px-3 py-2 text-sm text-slate-900 shadow-sm ring-1 ring-inset ring-slate-300 focus:ring-2 focus:ring-violet-600 disabled:bg-slate-100'
