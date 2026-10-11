import { useState } from 'react'
import { api } from '../api.js'
import { useAsync } from '../useAsync.js'
import { Button, Card, ErrorBox, Field, Spinner, inputCls } from '../components/ui.jsx'
import SlotGrid from '../components/SlotGrid.jsx'
import { addDays, money, todayIn } from '../format.js'

export default function Stations({ onBook }) {
  const stations = useAsync(() => api.stations(), [])
  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-lg font-semibold text-slate-900">Charging stations</h1>
        <p className="mt-1 text-sm text-slate-500">
          Demonstration stations (codes starting DEMO-) stored in MySQL. They are not ACN-Data sites. Each slot is one hour;
          capacity is the number of chargers that can be booked in the same hour.
        </p>
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
      title={
        <span>
          {station.name} <span className="ml-1 font-mono text-xs font-normal text-slate-400">{station.code}</span>
        </span>
      }
      subtitle={station.address}
      actions={
        <Button onClick={() => onBook({ stationId: station.id, date })} variant="secondary">
          Book at this station
        </Button>
      }
    >
      <dl className="grid gap-3 text-sm sm:grid-cols-4">
        <Info k="Capacity" v={`${station.capacity} chargers`} />
        <Info k="Base price" v={`${money(station.basePricePerHour, station.currency)} / hour`} />
        <Info k="Time zone" v={station.timeZone} />
        <Info k="Bookable slots on this day" v={free == null ? '…' : free} />
      </dl>
      <div className="mt-5 flex flex-wrap items-end gap-3">
        <Field label="Availability for">
          <input type="date" className={inputCls} min={today} max={addDays(today, 14)} value={date} onChange={(e) => e.target.value && setDate(e.target.value)} />
        </Field>
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

function Info({ k, v }) {
  return (
    <div className="rounded-lg bg-slate-50 px-3 py-2">
      <dt className="text-xs text-slate-500">{k}</dt>
      <dd className="mt-0.5 font-medium text-slate-900">{v}</dd>
    </div>
  )
}
