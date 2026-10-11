import { CONGESTION_STYLE } from '../format.js'

export function Card({ title, subtitle, actions, children, className = '' }) {
  return (
    <section className={`rounded-xl border border-slate-200 bg-white shadow-sm ${className}`}>
      {(title || actions) && (
        <header className="flex flex-wrap items-start justify-between gap-3 border-b border-slate-100 px-5 py-4">
          <div>
            {title && <h2 className="text-sm font-semibold text-slate-900">{title}</h2>}
            {subtitle && <p className="mt-0.5 text-xs text-slate-500">{subtitle}</p>}
          </div>
          {actions}
        </header>
      )}
      <div className="p-5">{children}</div>
    </section>
  )
}

export function Stat({ label, value, hint, tone = 'default' }) {
  const tones = { default: 'text-slate-900', good: 'text-emerald-700', accent: 'text-indigo-700' }
  return (
    <div className="rounded-lg border border-slate-200 bg-white p-4">
      <p className="text-xs font-medium uppercase tracking-wide text-slate-500">{label}</p>
      <p className={`mt-1 text-2xl font-semibold tabular-nums ${tones[tone]}`}>{value}</p>
      {hint && <p className="mt-1 text-xs text-slate-500">{hint}</p>}
    </div>
  )
}

export function CongestionBadge({ level, large = false }) {
  const s = CONGESTION_STYLE[level]
  if (!s) return null
  return (
    <span className={`inline-flex items-center gap-1.5 rounded-full px-2.5 py-0.5 font-medium ring-1 ring-inset ${s.cls} ${large ? 'text-sm' : 'text-xs'}`}>
      <span className={`h-1.5 w-1.5 rounded-full ${s.dot}`} />
      {s.label} congestion
    </span>
  )
}

export function ReplayBadge() {
  return (
    <span className="inline-flex items-center rounded-full bg-indigo-50 px-2.5 py-0.5 text-xs font-medium text-indigo-700 ring-1 ring-inset ring-indigo-600/20">
      Historical replay · not live
    </span>
  )
}

export function Spinner({ label = 'Loading…' }) {
  return (
    <div className="flex items-center gap-2 py-6 text-sm text-slate-500" role="status">
      <span className="h-4 w-4 animate-spin rounded-full border-2 border-slate-300 border-t-indigo-600" />
      {label}
    </div>
  )
}

export function ErrorBox({ error, onRetry }) {
  if (!error) return null
  const p = error.problem || {}
  return (
    <div className="rounded-lg border border-rose-200 bg-rose-50 p-4 text-sm text-rose-800" role="alert">
      <p className="font-semibold">{p.title || 'Something went wrong'}</p>
      <p className="mt-1">{error.message}</p>
      {p.errors && (
        <ul className="mt-2 list-inside list-disc">
          {Object.entries(p.errors).map(([field, msg]) => (
            <li key={field}>
              <span className="font-mono">{field}</span>: {msg}
            </li>
          ))}
        </ul>
      )}
      {onRetry && (
        <button onClick={onRetry} className="mt-3 rounded-md bg-white px-3 py-1.5 text-xs font-medium text-rose-700 ring-1 ring-rose-300 hover:bg-rose-100">
          Try again
        </button>
      )}
    </div>
  )
}

export function Button({ children, variant = 'primary', className = '', ...props }) {
  const v = {
    primary: 'bg-indigo-600 text-white hover:bg-indigo-500 disabled:bg-indigo-300',
    secondary: 'bg-white text-slate-700 ring-1 ring-inset ring-slate-300 hover:bg-slate-50 disabled:text-slate-400',
  }
  return (
    <button className={`inline-flex items-center justify-center gap-2 rounded-md px-3.5 py-2 text-sm font-medium shadow-sm transition disabled:cursor-not-allowed ${v[variant]} ${className}`} {...props}>
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
  'block w-full rounded-md border-0 bg-white px-3 py-2 text-sm text-slate-900 shadow-sm ring-1 ring-inset ring-slate-300 focus:ring-2 focus:ring-indigo-600 disabled:bg-slate-100'
