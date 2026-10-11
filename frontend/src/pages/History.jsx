import { useState } from 'react'
import { api } from '../api.js'
import { useAsync } from '../useAsync.js'
import { Button, CongestionBadge, ErrorBox, Spinner, inputCls } from '../components/ui.jsx'
import { money, multiplierChange, placeName, wallClock } from '../format.js'

export default function History({ onBook }) {
  const stations = useAsync(() => api.stations(), [])
  const [stationId, setStationId] = useState('')
  const bookings = useAsync(() => api.bookings(stationId || undefined), [stationId])
  const [confirmingId, setConfirmingId] = useState(null)
  const [cancel, setCancel] = useState({ busyId: null, error: null, done: null })

  async function confirmCancel(b) {
    setCancel({ busyId: b.id, error: null, done: null })
    try {
      await api.cancelBooking(b.id)
      setCancel({ busyId: null, error: null, done: `Booking #${b.id} cancelled. That charger is free again ✌️` })
      setConfirmingId(null)
      bookings.reload()
    } catch (error) {
      setCancel({ busyId: null, error, done: null })
      setConfirmingId(null)
      bookings.reload()
    }
  }

  const list = bookings.data ?? []

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="text-2xl font-bold tracking-tight text-slate-900">My bookings</h1>
          <p className="mt-1 text-sm text-slate-500">
            {bookings.data ? `${list.length} booking${list.length === 1 ? '' : 's'}` : 'Your charging slots'}
          </p>
        </div>
        <div className="flex items-center gap-2">
          <label className="sr-only" htmlFor="station-filter">
            Filter by station
          </label>
          <select id="station-filter" className={`${inputCls} w-auto`} value={stationId} onChange={(e) => setStationId(e.target.value)}>
            <option value="">All stations</option>
            {stations.data?.map((s) => (
              <option key={s.id} value={s.id}>
                {placeName(s)}
              </option>
            ))}
          </select>
          <Button variant="secondary" onClick={bookings.reload} aria-label="Refresh bookings">
            ↻
          </Button>
        </div>
      </div>

      <div aria-live="polite">
        {cancel.done && <p className="rounded-xl bg-emerald-50 px-4 py-3 text-sm text-emerald-800 ring-1 ring-inset ring-emerald-200">{cancel.done}</p>}
        {cancel.error && <ErrorBox error={cancel.error} />}
      </div>

      {bookings.loading && <Spinner />}
      <ErrorBox error={bookings.error} onRetry={bookings.reload} />

      {bookings.data && !bookings.loading && list.length === 0 && (
        <div className="rounded-2xl border border-dashed border-slate-300 bg-white p-10 text-center">
          <p className="text-3xl" aria-hidden>
            🔌
          </p>
          <p className="mt-2 font-semibold text-slate-900">No bookings yet</p>
          <p className="mt-1 text-sm text-slate-500">Grab a chill hour and it'll show up here.</p>
          <Button className="mt-4" onClick={onBook}>
            Book a slot
          </Button>
        </div>
      )}

      {list.length > 0 && (
        <ul className="grid gap-4 md:grid-cols-2">
          {list.map((b) => (
            <li key={b.id} className={`rounded-2xl border bg-white p-5 shadow-sm ${b.status === 'CANCELLED' ? 'border-slate-200 opacity-70' : 'border-slate-200/80'}`}>
              <div className="flex items-start justify-between gap-3">
                <div>
                  <p className="font-semibold text-slate-900">{placeName(b)}</p>
                  <p className="mt-0.5 text-sm text-slate-600 tabular-nums">
                    {wallClock(b.startTime)} – {wallClock(b.endTime, { date: false })}
                  </p>
                </div>
                <StatusPill status={b.status} />
              </div>
              <div className="mt-4 flex flex-wrap items-center gap-2 text-sm">
                <CongestionBadge level={b.congestionLevel} />
                <span className="text-slate-500">
                  base {money(b.basePrice, b.currency)} · {multiplierChange(b.priceMultiplier)}
                </span>
              </div>
              <div className="mt-4 flex items-end justify-between gap-3 border-t border-slate-100 pt-4">
                <div>
                  <p className="text-xs text-slate-500">
                    #{b.id} · {b.customerName}
                  </p>
                  <p className={`text-xl font-bold tabular-nums ${b.status === 'CANCELLED' ? 'text-slate-400 line-through' : 'text-slate-900'}`}>
                    {money(b.finalPrice, b.currency)}
                  </p>
                </div>
                <CancelAction
                  booking={b}
                  confirming={confirmingId === b.id}
                  busy={cancel.busyId === b.id}
                  onAsk={() => {
                    setCancel({ busyId: null, error: null, done: null })
                    setConfirmingId(b.id)
                  }}
                  onKeep={() => setConfirmingId(null)}
                  onConfirm={() => confirmCancel(b)}
                />
              </div>
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}

function StatusPill({ status }) {
  const confirmed = status === 'CONFIRMED'
  return (
    <span className={`shrink-0 rounded-full px-2.5 py-0.5 text-xs font-semibold ${confirmed ? 'bg-emerald-100 text-emerald-800' : 'bg-slate-100 text-slate-600'}`}>
      {confirmed ? 'Confirmed' : 'Cancelled'}
    </span>
  )
}

/**
 * Cancel is offered only for confirmed bookings whose slot has not started (the backend enforces
 * the same rule and answers 409 otherwise). Two steps, so a single misclick cannot cancel.
 */
function CancelAction({ booking, confirming, busy, onAsk, onKeep, onConfirm }) {
  if (booking.status !== 'CONFIRMED') return null
  if (Date.parse(booking.startTime) <= Date.now()) return <span className="text-xs text-slate-400">Slot started</span>
  if (!confirming) {
    return (
      <button
        type="button"
        onClick={onAsk}
        className="rounded-full px-3 py-1.5 text-xs font-semibold text-rose-700 ring-1 ring-inset ring-rose-300 hover:bg-rose-50 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-rose-600"
        aria-label={`Cancel booking ${booking.id}`}
      >
        Cancel
      </button>
    )
  }
  return (
    <span className="inline-flex items-center gap-1.5" role="group" aria-label={`Confirm cancelling booking ${booking.id}`}>
      <button
        type="button"
        onClick={onConfirm}
        disabled={busy}
        className="rounded-full bg-rose-600 px-3 py-1.5 text-xs font-semibold text-white hover:bg-rose-500 disabled:bg-rose-300 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-rose-600"
      >
        {busy ? 'Cancelling…' : 'Yes, cancel'}
      </button>
      <button
        type="button"
        onClick={onKeep}
        disabled={busy}
        className="rounded-full px-3 py-1.5 text-xs font-semibold text-slate-600 ring-1 ring-inset ring-slate-300 hover:bg-slate-50 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-violet-600"
      >
        Keep it
      </button>
    </span>
  )
}
