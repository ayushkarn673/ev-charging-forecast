import { useEffect, useState } from 'react'
import { api } from '../api.js'
import { useAsync } from '../useAsync.js'
import { Button, Card, CongestionBadge, ErrorBox, Field, Spinner, inputCls } from '../components/ui.jsx'
import SlotGrid from '../components/SlotGrid.jsx'
import { addDays, money, multiplierChange, pct, placeName, todayIn, wallClock } from '../format.js'

export default function Booking({ preset, onDone }) {
  const stations = useAsync(() => api.stations(), [])
  const [stationId, setStationId] = useState(preset?.stationId ?? null)
  const station = stations.data?.find((s) => s.id === stationId) ?? null
  const today = station ? todayIn(station.timeZone) : null
  const [date, setDate] = useState(preset?.date ?? null)
  const [slot, setSlot] = useState(preset?.startTime ?? null)
  const [name, setName] = useState('')
  const [quote, setQuote] = useState({ data: null, error: null, loading: false })
  const [submit, setSubmit] = useState({ data: null, error: null, loading: false })

  // default to the first station and today once stations load
  useEffect(() => {
    if (stations.data?.length && stationId == null) setStationId(stations.data[0].id)
  }, [stations.data, stationId])
  useEffect(() => {
    if (today && !date) setDate(today)
  }, [today, date])

  const availability = useAsync(
    () => (stationId && date ? api.availability(stationId, date) : Promise.resolve(null)),
    [stationId, date, submit.data?.id],
  )

  // price quote whenever a slot is chosen (calculated on the backend from the LSTM forecast)
  useEffect(() => {
    if (!stationId || !slot) {
      setQuote({ data: null, error: null, loading: false })
      return
    }
    let cancelled = false
    setQuote({ data: null, error: null, loading: true })
    api.quote(stationId, slot).then(
      (data) => !cancelled && setQuote({ data, error: null, loading: false }),
      (error) => !cancelled && setQuote({ data: null, error, loading: false }),
    )
    return () => {
      cancelled = true
    }
  }, [stationId, slot])

  async function confirm() {
    setSubmit({ data: null, error: null, loading: true })
    try {
      const data = await api.createBooking({
        stationId,
        customerName: name,
        startTime: slot,
        quotedFinalPrice: quote.data?.price.finalPrice,
      })
      setSubmit({ data, error: null, loading: false })
      setSlot(null)
    } catch (error) {
      setSubmit({ data: null, error, loading: false })
      if (error.status === 409) availability.reload()
    }
  }

  function changeStation(id) {
    setStationId(id)
    setSlot(null)
    setSubmit({ data: null, error: null, loading: false })
  }

  if (submit.data) return <Confirmation booking={submit.data} onAnother={() => setSubmit({ data: null, error: null, loading: false })} onHistory={onDone} />

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold tracking-tight text-slate-900">Book a slot ⚡</h1>
        <p className="mt-1 text-sm text-slate-500">Pick a spot and an hour. Quieter hours cost less.</p>
      </div>
      {stations.loading && <Spinner />}
      <ErrorBox error={stations.error} onRetry={stations.reload} />

      {stations.data && (
        <div className="grid gap-6 lg:grid-cols-5">
          <Card className="lg:col-span-3" title="1 · Where & when">
            <div className="grid gap-4 sm:grid-cols-2">
              <Field label="Station">
                <select className={inputCls} value={stationId ?? ''} onChange={(e) => changeStation(Number(e.target.value))}>
                  {stations.data.map((s) => (
                    <option key={s.id} value={s.id}>
                      {placeName(s)}
                    </option>
                  ))}
                </select>
              </Field>
              <Field label="Day">
                <input
                  type="date"
                  className={inputCls}
                  min={today ?? undefined}
                  max={today ? addDays(today, 14) : undefined}
                  value={date ?? ''}
                  onChange={(e) => {
                    if (!e.target.value) return
                    setDate(e.target.value)
                    setSlot(null)
                  }}
                />
              </Field>
            </div>
            <div className="mt-5">
              {availability.loading && <Spinner />}
              <ErrorBox error={availability.error} onRetry={availability.reload} />
              {availability.data && !availability.loading && <SlotGrid availability={availability.data} selected={slot} onSelect={setSlot} />}
            </div>
          </Card>

          <div className="space-y-6 lg:col-span-2">
            <Card title="2 · Your price">
              <div aria-live="polite">
                {!slot && <p className="text-sm text-slate-500">Tap a free hour to see its price 👀</p>}
                {quote.loading && <Spinner label="Checking the vibe…" />}
                <ErrorBox error={quote.error} />
                {quote.data && <QuoteDetails quote={quote.data} />}
              </div>
            </Card>

            <Card title="3 · Lock it in">
              <Field label="Your name">
                <input className={inputCls} maxLength={100} value={name} onChange={(e) => setName(e.target.value)} placeholder="e.g. Priya Sharma" />
              </Field>
              <div className="mt-3" aria-live="polite">
                <ErrorBox error={submit.error} />
              </div>
              <Button className="mt-4 w-full py-2.5" disabled={!quote.data || !name.trim() || submit.loading} onClick={confirm}>
                {submit.loading ? 'Locking it in…' : quote.data ? `Lock it in · ${money(quote.data.price.finalPrice, quote.data.currency)}` : 'Lock it in'}
              </Button>
              <p className="mt-2 text-center text-xs text-slate-500">We double-check the slot and the price before confirming.</p>
            </Card>
          </div>
        </div>
      )}
    </div>
  )
}

function QuoteDetails({ quote }) {
  const { price } = quote
  return (
    <div className="text-sm">
      <p className="font-medium text-slate-800">
        {wallClock(quote.slotStart)} – {wallClock(quote.slotEnd, { date: false })}
      </p>
      <dl className="mt-4 space-y-2.5">
        <Line k="Base price" v={money(price.basePrice, quote.currency)} />
        <Line
          k="Vibe"
          v={
            <span className="inline-flex items-center gap-2">
              <CongestionBadge level={price.congestionLevel} />
              <span className="text-xs font-normal text-slate-500">~{pct(price.utilization, 0)} busy</span>
            </span>
          }
        />
        <Line k="Vibe adjustment" v={multiplierChange(price.multiplier)} />
        <div className="flex items-baseline justify-between border-t border-slate-200 pt-3">
          <dt className="font-semibold text-slate-900">You pay</dt>
          <dd className="text-2xl font-bold tabular-nums text-slate-900">{money(price.finalPrice, quote.currency)}</dd>
        </div>
      </dl>
      <details className="mt-4 rounded-xl bg-slate-50 px-3 py-2 text-xs text-slate-600">
        <summary className="cursor-pointer font-medium text-slate-700">Why this price?</summary>
        <p className="mt-2 leading-relaxed">
          Our AI model predicts how busy this hour usually gets, based on real EV charging history. Chill hours get a
          discount; busy ones cost a bit more. This is a demo, so the prediction comes from historical data, not live traffic.
        </p>
      </details>
    </div>
  )
}

function Line({ k, v }) {
  return (
    <div className="flex items-center justify-between gap-3">
      <dt className="text-slate-500">{k}</dt>
      <dd className="font-medium tabular-nums text-slate-800">{v}</dd>
    </div>
  )
}

function Confirmation({ booking, onAnother, onHistory }) {
  return (
    <div className="mx-auto max-w-lg">
      <Card>
        <div className="text-center">
          <div className="mx-auto flex h-14 w-14 items-center justify-center rounded-full bg-gradient-to-br from-violet-600 to-fuchsia-500 text-2xl text-white shadow" aria-hidden>
            ⚡
          </div>
          <h1 className="mt-4 text-2xl font-bold tracking-tight text-slate-900">You're locked in!</h1>
          <p className="mt-1 text-sm text-slate-500">
            {placeName(booking)} · {wallClock(booking.startTime)} – {wallClock(booking.endTime, { date: false })}
          </p>
        </div>
        <dl className="mt-6 space-y-2.5 text-sm">
          <Line k="Booking" v={`#${booking.id} · ${booking.customerName}`} />
          <Line k="Vibe" v={<CongestionBadge level={booking.congestionLevel} />} />
          <Line k="Base price" v={money(booking.basePrice, booking.currency)} />
          <Line k="Vibe adjustment" v={multiplierChange(booking.priceMultiplier)} />
          <div className="flex items-baseline justify-between border-t border-slate-200 pt-3">
            <dt className="font-semibold text-slate-900">You pay</dt>
            <dd className="text-xl font-bold tabular-nums text-slate-900">{money(booking.finalPrice, booking.currency)}</dd>
          </div>
        </dl>
        <div className="mt-6 flex flex-wrap justify-center gap-3">
          <Button onClick={onHistory}>My bookings</Button>
          <Button variant="secondary" onClick={onAnother}>
            Book another
          </Button>
        </div>
      </Card>
    </div>
  )
}
