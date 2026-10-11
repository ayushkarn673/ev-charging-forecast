import { api } from '../api.js'
import { useAsync } from '../useAsync.js'
import { Button, CongestionBadge, ErrorBox, Spinner } from '../components/ui.jsx'
import { money, placeName } from '../format.js'

const STEPS = [
  { emoji: '📍', title: 'Pick a spot', text: 'Choose a charging station that works for you.' },
  { emoji: '⏰', title: 'Pick an hour', text: 'See which one-hour slots are still free.' },
  { emoji: '💸', title: 'Pay the vibe price', text: 'Quiet hours cost less. Busy hours cost a bit more.' },
]

const VIBES = [
  { level: 'LOW', text: 'cheaper than the base price' },
  { level: 'MEDIUM', text: 'a little above base' },
  { level: 'HIGH', text: 'peak pricing' },
  { level: 'VERY_HIGH', text: 'top price — try another hour' },
]

export default function Home({ onBook, onNavigate }) {
  const stations = useAsync(() => api.stations(), [])

  return (
    <div className="space-y-10">
      <section className="relative overflow-hidden rounded-3xl bg-gradient-to-br from-violet-600 via-fuchsia-600 to-orange-400 px-6 py-10 text-white shadow-lg sm:px-10 sm:py-14">
        <div className="pointer-events-none absolute -right-16 -top-16 h-56 w-56 rounded-full bg-white/15 blur-2xl" aria-hidden />
        <p className="inline-flex rounded-full bg-white/20 px-3 py-1 text-xs font-semibold backdrop-blur">⚡ EV charging, but make it smart</p>
        <h1 className="mt-4 max-w-xl text-3xl font-extrabold leading-tight tracking-tight sm:text-5xl">Charge when it's chill. Pay less.</h1>
        <p className="mt-3 max-w-lg text-base text-white/90 sm:text-lg">
          Our AI guesses how busy each hour will be, so you can grab a quiet slot and skip the peak price.
        </p>
        <div className="mt-6 flex flex-wrap gap-3">
          <button
            onClick={() => onBook(null)}
            className="rounded-full bg-white px-5 py-2.5 text-sm font-semibold text-violet-700 shadow hover:bg-violet-50 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-white"
          >
            Book a slot →
          </button>
          <button
            onClick={() => onNavigate('stations')}
            className="rounded-full px-5 py-2.5 text-sm font-semibold text-white ring-1 ring-white/60 hover:bg-white/10 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-white"
          >
            See stations
          </button>
        </div>
      </section>

      <section aria-labelledby="how">
        <h2 id="how" className="text-lg font-bold text-slate-900">How it works</h2>
        <ol className="mt-4 grid gap-4 sm:grid-cols-3">
          {STEPS.map((s, i) => (
            <li key={s.title} className="rounded-2xl border border-slate-200/80 bg-white p-5 shadow-sm">
              <span className="text-2xl" aria-hidden>{s.emoji}</span>
              <p className="mt-2 font-semibold text-slate-900">
                {i + 1}. {s.title}
              </p>
              <p className="mt-1 text-sm text-slate-500">{s.text}</p>
            </li>
          ))}
        </ol>
      </section>

      <section aria-labelledby="vibes" className="rounded-2xl border border-slate-200/80 bg-white p-5 shadow-sm">
        <h2 id="vibes" className="text-lg font-bold text-slate-900">Price vibes</h2>
        <p className="mt-1 text-sm text-slate-500">Every hour gets a vibe based on how busy we expect it to be.</p>
        <ul className="mt-4 grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
          {VIBES.map((v) => (
            <li key={v.level} className="flex flex-col items-start gap-2 rounded-xl bg-slate-50 p-3">
              <CongestionBadge level={v.level} large />
              <span className="text-sm text-slate-600">{v.text}</span>
            </li>
          ))}
        </ul>
      </section>

      <section aria-labelledby="spots">
        <div className="flex flex-wrap items-end justify-between gap-3">
          <h2 id="spots" className="text-lg font-bold text-slate-900">Charging spots</h2>
          <button onClick={() => onNavigate('stations')} className="text-sm font-semibold text-violet-700 hover:underline">
            Check free hours →
          </button>
        </div>
        {stations.loading && <Spinner />}
        <div className="mt-4">
          <ErrorBox error={stations.error} onRetry={stations.reload} />
        </div>
        <ul className="grid gap-4 sm:grid-cols-3">
          {stations.data?.map((s) => (
            <li key={s.id} className="flex flex-col rounded-2xl border border-slate-200/80 bg-white p-5 shadow-sm">
              <p className="text-base font-semibold text-slate-900">{placeName(s)}</p>
              <p className="mt-1 text-sm text-slate-500">
                {s.capacity} chargers · base {money(s.basePricePerHour, s.currency)}/hr
              </p>
              <Button className="mt-4 self-start" onClick={() => onBook({ stationId: s.id })}>
                Book here
              </Button>
            </li>
          ))}
        </ul>
      </section>
    </div>
  )
}
