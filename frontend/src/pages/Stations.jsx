import { useState } from 'react'
import { api } from '../api.js'
import { useAsync } from '../useAsync.js'
import { Button, Card, ErrorBox, Field, Spinner, inputCls } from '../components/ui.jsx'
import SlotGrid from '../components/SlotGrid.jsx'
import { addDays, money, placeName, todayIn } from '../format.js'

export default function Stations({ onBook }) {
  const stations = useAsync(() => api.stations(), [])
  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold tracking-tight text-slate-900">Stations</h1>
        <p className="mt-1 text-sm text-slate-500">Pick a day to see which hours are free. Tap a free hour to book it.</p>
      </div>
      {stations.loading && <Spinner />}
      <ErrorBox error={stations.error} onRetry={stations.reload} />
      {stations.data?.map((s) => (
        <StationCard key={s.id} station={s} onBook={onBook} />
      ))}
    </div>
  )
}

function StationCard({ station, onBook }) {
  const today = todayIn(station.timeZone)
  const [date, setDate] = useState(today)
  const availability = useAsync(() => api.availability(station.id, date), [station.id, date])
  const free = availability.data?.slots.filter((s) => s.bookable).length

  return (
    <Card
      title={placeName(station)}
      subtitle={
        <span className="inline-flex flex-wrap items-center gap-2">
          <span className="rounded-full bg-slate-100 px-2 py-0.5 text-xs text-slate-600">Demo spot</span>
          <span>
            {station.capacity} chargers · base {money(station.basePricePerHour, station.currency)}/hr
          </span>
        </span>
      }
      actions={
        <Button onClick={() => onBook({ stationId: station.id, date })} variant="secondary">
          Book here
        </Button>
      }
    >
      <div className="flex flex-wrap items-end justify-between gap-3">
        <Field label="Day">
          <input type="date" className={inputCls} min={today} max={addDays(today, 14)} value={date} onChange={(e) => e.target.value && setDate(e.target.value)} />
        </Field>
        <p className="text-sm text-slate-600" aria-live="polite">
          {free == null ? '…' : free === 0 ? 'No free hours on this day 😕' : `${free} free hour${free === 1 ? '' : 's'} ✨`}
        </p>
      </div>
      <div className="mt-4">
        {availability.loading && <Spinner />}
        <ErrorBox error={availability.error} onRetry={availability.reload} />
        {availability.data && !availability.loading && (
          <SlotGrid availability={availability.data} onSelect={(startTime) => onBook({ stationId: station.id, date, startTime })} />
        )}
      </div>
    </Card>
  )
}
