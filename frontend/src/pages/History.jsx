import { useState } from 'react'
import { api } from '../api.js'
import { useAsync } from '../useAsync.js'
import { Button, Card, CongestionBadge, ErrorBox, Field, Spinner, inputCls } from '../components/ui.jsx'
import { money, num, pct, wallClock } from '../format.js'

export default function History() {
  const stations = useAsync(() => api.stations(), [])
  const [stationId, setStationId] = useState('')
  const bookings = useAsync(() => api.bookings(stationId || undefined), [stationId])

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-lg font-semibold text-slate-900">Booking history</h1>
        <p className="mt-1 text-sm text-slate-500">Bookings saved in MySQL, with the price and forecast each one was charged from.</p>
      </div>
      <Card
        title={bookings.data ? `${bookings.data.length} booking${bookings.data.length === 1 ? '' : 's'}` : 'Bookings'}
        actions={
          <div className="flex items-end gap-3">
            <Field label="Station">
              <select className={inputCls} value={stationId} onChange={(e) => setStationId(e.target.value)}>
                <option value="">All stations</option>
                {stations.data?.map((s) => (
                  <option key={s.id} value={s.id}>
                    {s.code}
                  </option>
                ))}
              </select>
            </Field>
            <Button variant="secondary" onClick={bookings.reload}>
              Refresh
            </Button>
          </div>
        }
      >
        {bookings.loading && <Spinner />}
        <ErrorBox error={bookings.error} onRetry={bookings.reload} />
        {bookings.data && !bookings.loading && bookings.data.length === 0 && (
          <p className="py-8 text-center text-sm text-slate-500">No bookings yet. Book a slot to see it here.</p>
        )}
        {bookings.data && bookings.data.length > 0 && (
          <div className="overflow-x-auto">
            <table className="w-full min-w-[860px] text-sm">
              <thead>
                <tr className="border-b border-slate-200 text-left text-xs uppercase tracking-wide text-slate-500">
                  <th className="py-2 pr-3 font-medium">#</th>
                  <th className="py-2 pr-3 font-medium">Station</th>
                  <th className="py-2 pr-3 font-medium">Slot (station time)</th>
                  <th className="py-2 pr-3 font-medium">Customer</th>
                  <th className="py-2 pr-3 font-medium">Status</th>
                  <th className="py-2 pr-3 font-medium">Forecast</th>
                  <th className="py-2 pr-3 text-right font-medium">Base</th>
                  <th className="py-2 pr-3 text-right font-medium">×</th>
                  <th className="py-2 text-right font-medium">Charged</th>
                </tr>
              </thead>
              <tbody>
                {bookings.data.map((b) => (
                  <tr key={b.id} className="border-b border-slate-100 align-top">
                    <td className="py-2.5 pr-3 tabular-nums text-slate-500">{b.id}</td>
                    <td className="py-2.5 pr-3">
                      <span className="font-mono text-xs">{b.stationCode}</span>
                    </td>
                    <td className="py-2.5 pr-3 tabular-nums">
                      {wallClock(b.startTime)}–{wallClock(b.endTime, { date: false })}
                    </td>
                    <td className="py-2.5 pr-3">{b.customerName}</td>
                    <td className="py-2.5 pr-3">
                      <span className={`rounded-full px-2 py-0.5 text-xs font-medium ${b.status === 'CONFIRMED' ? 'bg-emerald-100 text-emerald-800' : 'bg-slate-100 text-slate-600'}`}>{b.status}</span>
                    </td>
                    <td className="py-2.5 pr-3">
                      <CongestionBadge level={b.congestionLevel} />
                      <span className="mt-1 block text-xs text-slate-500">
                        {pct(b.predictedUtilization)} · {b.forecastMode}
                      </span>
                    </td>
                    <td className="py-2.5 pr-3 text-right tabular-nums">{money(b.basePrice, b.currency)}</td>
                    <td className="py-2.5 pr-3 text-right tabular-nums">{num(b.priceMultiplier)}</td>
                    <td className="py-2.5 text-right font-semibold tabular-nums">{money(b.finalPrice, b.currency)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>
    </div>
  )
}
