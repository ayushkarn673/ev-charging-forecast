import { useEffect, useState } from 'react'
import { api } from '../api.js'
import { useAsync } from '../useAsync.js'
import { Button, Card, CongestionBadge, ErrorBox, Field, ReplayBadge, Spinner, inputCls } from '../components/ui.jsx'
import SlotGrid from '../components/SlotGrid.jsx'
import { addDays, money, num, pct, todayIn, wallClock } from '../format.js'

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
        <h1 className="text-lg font-semibold text-slate-900">Book a charging slot</h1>
        <p className="mt-1 text-sm text-slate-500">Choose a station, a day and a one-hour slot. The price is calculated by the backend from the LSTM demand forecast.</p>
      </div>
      {stations.loading && <Spinner />}
      <ErrorBox error={stations.error} onRetry={stations.reload} />

      {stations.data && (
        <div className="grid gap-6 lg:grid-cols-5">
          <Card className="lg:col-span-3" title="1 · Station, day and slot">
            <div className="grid gap-4 sm:grid-cols-2">
              <Field label="Station">
                <select className={inputCls} value={stationId ?? ''} onChange={(e) => changeStation(Number(e.target.value))}>
                  {stations.data.map((s) => (
                    <option key={s.id} value={s.id}>
                      {s.code} — {s.name}
                    </option>
                  ))}
                </select>
              </Field>
              <Field label={`Day (${station?.timeZone ?? ''})`}>
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
            <Card title="2 · Price breakdown" actions={quote.data && <ReplayBadge />}>
              {!slot && <p className="text-sm text-slate-500">Select a slot to see its demand-based price.</p>}
              {quote.loading && <Spinner label="Getting the forecast and price…" />}
              <ErrorBox error={quote.error} />
              {quote.data && <QuoteDetails quote={quote.data} />}
            </Card>

            <Card title="3 · Confirm">
              <Field label="Your name">
                <input className={inputCls} maxLength={100} value={name} onChange={(e) => setName(e.target.value)} placeholder="e.g. Priya Sharma" />
              </Field>
              <ErrorBox error={submit.error} />
              <Button className="mt-4 w-full" disabled={!quote.data || !name.trim() || submit.loading} onClick={confirm}>
                {submit.loading ? 'Booking…' : quote.data ? `Confirm booking · ${money(quote.data.price.finalPrice, quote.data.currency)}` : 'Confirm booking'}
              </Button>
              <p className="mt-2 text-xs text-slate-500">
                The backend re-checks the slot, recalculates the price and refuses the booking if the slot filled up or the price changed.
              </p>
            </Card>
          </div>
        </div>
      )}
    </div>
  )
}

function QuoteDetails({ quote }) {
  const { price, forecast } = quote
  return (
    <div className="text-sm">
      <p className="text-slate-600">
        {wallClock(quote.slotStart)} – {wallClock(quote.slotEnd, { date: false })} at <span className="font-mono">{quote.stationCode}</span>
      </p>
      <dl className="mt-4 space-y-2">
        <Line k="Base price (1 hour)" v={money(price.basePrice, quote.currency)} />
        <Line k="Predicted utilization" v={pct(price.utilization)} />
        <Line k="Congestion band" v={<CongestionBadge level={price.congestionLevel} />} />
        <Line k="Demand multiplier" v={`× ${num(price.multiplier)}`} />
        <div className="flex justify-between border-t border-slate-200 pt-3 text-base font-semibold text-slate-900">
          <dt>Final price</dt>
          <dd className="tabular-nums">{money(price.finalPrice, quote.currency)}</dd>
        </div>
      </dl>
      <div className="mt-4 rounded-lg bg-slate-50 p-3 text-xs leading-relaxed text-slate-600">
        <p>{forecast.mapping}</p>
        <p className="mt-1.5">
          Replay forecast time: <span className="font-medium">{wallClock(forecast.replayForecastTime)}</span> (Pacific) · horizon {forecast.horizonHours} h · {forecast.source} ·{' '}
          <span className="font-mono">{forecast.modelId}</span>
        </p>
      </div>
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
    <Card title="Booking confirmed">
      <div className="flex items-start gap-4">
        <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-full bg-emerald-100 text-lg text-emerald-700">✓</div>
        <div className="flex-1 text-sm">
          <p className="text-base font-semibold text-slate-900">
            Booking #{booking.id} — {booking.stationName}
          </p>
          <p className="mt-1 text-slate-600">
            {wallClock(booking.startTime)} – {wallClock(booking.endTime, { date: false })} · {booking.customerName}
          </p>
          <dl className="mt-4 grid max-w-md gap-2">
            <Line k="Status" v={booking.status} />
            <Line k="Base price" v={money(booking.basePrice, booking.currency)} />
            <Line k="Congestion / multiplier" v={<span className="inline-flex items-center gap-2"><CongestionBadge level={booking.congestionLevel} /> × {num(booking.priceMultiplier)}</span>} />
            <Line k="Charged" v={<span className="text-base font-semibold">{money(booking.finalPrice, booking.currency)}</span>} />
          </dl>
          <p className="mt-3 text-xs text-slate-500">Saved in MySQL with the forecast it was priced from ({booking.forecastMode}, {booking.modelId}).</p>
          <div className="mt-5 flex flex-wrap gap-3">
            <Button onClick={onHistory}>View booking history</Button>
            <Button variant="secondary" onClick={onAnother}>
              Book another slot
            </Button>
          </div>
        </div>
      </div>
    </Card>
  )
}
