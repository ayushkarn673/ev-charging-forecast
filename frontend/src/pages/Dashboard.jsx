import { useMemo, useState } from 'react'
import { api } from '../api.js'
import { useAsync } from '../useAsync.js'
import { Card, CongestionBadge, ErrorBox, Field, ReplayBadge, Spinner, Stat, inputCls } from '../components/ui.jsx'
import LineChart from '../components/LineChart.jsx'
import { addDays, num, pct, wallClock } from '../format.js'

// The model's untouched test period. All of it is Pacific Standard Time (UTC-08:00), so the
// datetime-local value can be sent with a fixed -08:00 offset.
const TEST_FIRST = '2019-12-20'
const TEST_LAST = '2020-02-29'
const PST = '-08:00'

const PRESETS = [
  { label: 'Weekday 09:00', value: '2020-02-05T09:00' },
  { label: 'Weekday 13:00', value: '2020-02-05T13:00' },
  { label: 'Weekday 18:00', value: '2020-02-05T18:00' },
  { label: 'Saturday 13:00', value: '2020-02-08T13:00' },
  { label: 'Night 03:00', value: '2020-02-06T03:00' },
]

const APPROACHES = [
  { key: 'lstm', label: 'LSTM (this project)' },
  { key: 'previousHour', label: 'Baseline: previous hour' },
  { key: 'sameHourLastWeek', label: 'Baseline: same hour last week' },
]

export default function Dashboard() {
  const [forecastTime, setForecastTime] = useState('2020-02-05T10:00')
  const [weekStart, setWeekStart] = useState('2020-02-03')
  const [showBaseline, setShowBaseline] = useState(false)

  const forecast = useAsync(() => api.forecast(`${forecastTime}:00${PST}`), [forecastTime])
  const evaluation = useAsync(() => api.evaluation(), [])
  const series = useAsync(() => api.evaluationSeries(weekStart, addDays(weekStart, 6)), [weekStart])

  return (
    <div className="space-y-6">
      <div className="rounded-xl border border-indigo-200 bg-indigo-50 px-5 py-4 text-sm text-indigo-900">
        <p className="font-semibold">Historical replay of real charging data — not a live 2026 feed</p>
        <p className="mt-1 text-indigo-800">
          The LSTM was trained on ACN-Data sessions from the Caltech garage (54 charging spaces, Nov 2018 – Feb 2020).
          Each forecast below is produced now by the trained model, using only observations that existed before the chosen
          time. Pick any hour in the untouched test period ({TEST_FIRST} → {TEST_LAST}, Pacific time).
        </p>
      </div>

      <div className="grid gap-6 lg:grid-cols-3">
        <ForecastPanel
          className="lg:col-span-2"
          forecastTime={forecastTime}
          setForecastTime={setForecastTime}
          state={forecast}
        />
        <PolicyPanel view={forecast.data} />
      </div>

      <PerformancePanel state={evaluation} />

      <Card
        title="Actual vs predicted utilization (saved test-set results)"
        subtitle="One-hour-ahead predictions from the Phase 3 evaluation on data the model never saw during training."
        actions={
          <div className="flex flex-wrap items-end gap-3">
            <Field label="Week starting">
              <input
                type="date"
                className={inputCls}
                min={TEST_FIRST}
                max={addDays(TEST_LAST, -6)}
                value={weekStart}
                onChange={(e) => e.target.value && setWeekStart(e.target.value)}
              />
            </Field>
            <label className="mb-2 inline-flex items-center gap-2 text-xs text-slate-600">
              <input type="checkbox" checked={showBaseline} onChange={(e) => setShowBaseline(e.target.checked)} />
              Show previous-hour baseline
            </label>
          </div>
        }
      >
        {series.loading && <Spinner />}
        <ErrorBox error={series.error} onRetry={series.reload} />
        {series.data && !series.loading && <SeriesChart data={series.data} showBaseline={showBaseline} />}
      </Card>
    </div>
  )
}

function ForecastPanel({ forecastTime, setForecastTime, state, className }) {
  const view = state.data
  const f = view?.forecast
  const p = f?.prediction
  return (
    <Card
      className={className}
      title="Next-hour demand forecast"
      subtitle="LSTM · 24 hours of history in, 1 hour ahead out"
      actions={<ReplayBadge />}
    >
      <div className="flex flex-wrap items-end gap-3">
        <Field label="Forecast time (Pacific time)">
          <input
            type="datetime-local"
            step="3600"
            className={inputCls}
            min={`${TEST_FIRST}T00:00`}
            max={`${TEST_LAST}T23:00`}
            value={forecastTime}
            onChange={(e) => e.target.value && setForecastTime(e.target.value.slice(0, 13) + ':00')}
          />
        </Field>
        <div className="flex flex-wrap gap-1.5 pb-0.5">
          {PRESETS.map((pr) => (
            <button
              key={pr.value}
              onClick={() => setForecastTime(pr.value)}
              className={`rounded-full px-3 py-1 text-xs ring-1 ring-inset ${forecastTime === pr.value ? 'bg-indigo-600 text-white ring-indigo-600' : 'bg-white text-slate-600 ring-slate-300 hover:bg-slate-50'}`}
            >
              {pr.label}
            </button>
          ))}
        </div>
      </div>

      <div className="mt-5">
        {state.loading && <Spinner label="Asking the LSTM service…" />}
        <ErrorBox error={state.error} onRetry={state.reload} />
        {f && !state.loading && (
          <>
            <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
              <Stat label="Predicted utilization" value={pct(p.utilization)} tone="accent" hint={`${wallClock(f.targetStart, { date: false })}–${wallClock(f.targetEnd, { date: false })} on ${wallClock(f.targetStart, { time: false })}`} />
              <Stat label="Est. occupied spaces" value={`${p.estimatedOccupiedSpacesRounded} / ${f.installedCapacitySpaces}`} hint={`hourly average ${num(p.estimatedOccupiedSpaces)} (rounded up)`} />
              <Stat label="Est. available spaces" value={p.estimatedAvailableSpacesRounded} hint="never overstated" tone="good" />
              <div className="rounded-lg border border-slate-200 bg-white p-4">
                <p className="text-xs font-medium uppercase tracking-wide text-slate-500">Congestion</p>
                <div className="mt-2">
                  <CongestionBadge level={view.congestionLevel} large />
                </div>
                <p className="mt-2 text-xs text-slate-500">from the pricing policy thresholds</p>
              </div>
            </div>

            <dl className="mt-5 grid gap-x-6 gap-y-2 text-sm sm:grid-cols-2">
              <Row k="Source" v={view.source} />
              <Row k="Mode" v={`${f.mode}${f.isSimulation ? ' (simulation)' : ''}`} />
              <Row k="Forecast made at" v={`${wallClock(f.forecastTime)} (${f.forecastTimeUtc})`} />
              <Row k="Horizon" v={`${f.horizonHours} hour`} />
              <Row k="Model" v={<span className="font-mono text-xs">{f.modelId}</span>} />
              <Row
                k="Recorded outcome"
                v={f.observedOutcome ? `${f.observedOutcome.utilizationPercent}% (error ${num(p.utilizationPercent - f.observedOutcome.utilizationPercent, 1)} pp)` : 'not in dataset'}
              />
            </dl>
            {f.observedOutcome && <p className="mt-2 text-xs text-slate-500">{f.observedOutcome.note}</p>}

            {f.warnings?.length > 0 && (
              <ul className="mt-4 space-y-1.5">
                {f.warnings.map((w) => (
                  <li key={w.code} className="rounded-md bg-amber-50 px-3 py-2 text-xs text-amber-900 ring-1 ring-inset ring-amber-200">
                    <span className="font-mono font-semibold">{w.code}</span> — {w.message}
                  </li>
                ))}
              </ul>
            )}
          </>
        )}
      </div>
    </Card>
  )
}

function Row({ k, v }) {
  return (
    <div className="flex justify-between gap-4 border-b border-slate-100 py-1.5">
      <dt className="text-slate-500">{k}</dt>
      <dd className="text-right font-medium text-slate-800">{v}</dd>
    </div>
  )
}

function PolicyPanel({ view }) {
  const policy = view?.pricingPolicy
  const bands = policy
    ? [
        { level: 'LOW', range: `< ${pct(policy.thresholds.medium, 0)}`, m: policy.multipliers.low },
        { level: 'MEDIUM', range: `${pct(policy.thresholds.medium, 0)} – ${pct(policy.thresholds.high, 0)}`, m: policy.multipliers.medium },
        { level: 'HIGH', range: `${pct(policy.thresholds.high, 0)} – ${pct(policy.thresholds.veryHigh, 0)}`, m: policy.multipliers.high },
        { level: 'VERY_HIGH', range: `≥ ${pct(policy.thresholds.veryHigh, 0)}`, m: policy.multipliers.veryHigh },
      ]
    : []
  return (
    <Card title="Demand-based pricing policy" subtitle="Price = station base price × band multiplier">
      {!policy && <Spinner />}
      {policy && (
        <>
          <table className="w-full text-sm">
            <thead>
              <tr className="text-left text-xs uppercase tracking-wide text-slate-500">
                <th className="pb-2 font-medium">Band</th>
                <th className="pb-2 font-medium">Predicted utilization</th>
                <th className="pb-2 text-right font-medium">Multiplier</th>
              </tr>
            </thead>
            <tbody>
              {bands.map((b) => (
                <tr key={b.level} className={b.level === view.congestionLevel ? 'bg-indigo-50' : ''}>
                  <td className="py-2 pl-1">
                    <CongestionBadge level={b.level} />
                  </td>
                  <td className="py-2 tabular-nums text-slate-700">{b.range}</td>
                  <td className="py-2 pr-1 text-right font-semibold tabular-nums">× {num(b.m)}</td>
                </tr>
              ))}
            </tbody>
          </table>
          <p className="mt-4 text-xs leading-relaxed text-slate-500">
            These thresholds and multipliers are an operator <strong>policy</strong> set in configuration — they are not
            learned by the LSTM. The model supplies the predicted utilization; the policy turns it into a price. Lower bounds
            are inclusive. Highlighted row = band of the forecast on the left.
          </p>
        </>
      )}
    </Card>
  )
}

function PerformancePanel({ state }) {
  const e = state.data
  return (
    <Card
      title="Model performance on the untouched test set"
      subtitle={e ? `${e.overall.lstm.n} hourly forecasts, ${wallClock(e.testPeriodLocal[0], { time: false })} – ${wallClock(e.testPeriodLocal[1], { time: false })} · pp = percentage points of utilization` : 'Saved Phase 3 evaluation'}
    >
      {state.loading && <Spinner />}
      <ErrorBox error={state.error} onRetry={state.reload} />
      {e && (
        <>
          <div className="grid gap-3 sm:grid-cols-3">
            <Stat label="LSTM MAE" value={`${num(e.overall.lstm.maePp, 2)} pp`} hint={`≈ ${num(e.overall.lstm.maeSpaces, 2)} of ${e.installedCapacitySpaces} spaces`} tone="accent" />
            <Stat label="LSTM RMSE" value={`${num(e.overall.lstm.rmsePp, 2)} pp`} hint={`≈ ${num(e.overall.lstm.rmseSpaces, 2)} spaces`} />
            <Stat label="LSTM WAPE" value={`${num(e.overall.lstm.wapePercent, 1)}%`} hint="Σ|error| ÷ Σ actual (a percentage error)" />
          </div>
          <div className="mt-5 overflow-x-auto">
            <table className="w-full min-w-[560px] text-sm">
              <thead>
                <tr className="border-b border-slate-200 text-left text-xs uppercase tracking-wide text-slate-500">
                  <th className="py-2 font-medium">Approach</th>
                  <th className="py-2 text-right font-medium">MAE (pp)</th>
                  <th className="py-2 text-right font-medium">RMSE (pp)</th>
                  <th className="py-2 text-right font-medium">WAPE</th>
                  <th className="py-2 text-right font-medium">MAE vs LSTM</th>
                </tr>
              </thead>
              <tbody>
                {APPROACHES.map((a) => {
                  const r = e.overall[a.key]
                  const cmp = a.key === 'lstm' ? null : e.comparisons[`lstmVs${a.key[0].toUpperCase()}${a.key.slice(1)}`]
                  return (
                    <tr key={a.key} className={`border-b border-slate-100 ${a.key === 'lstm' ? 'font-semibold text-indigo-800' : ''}`}>
                      <td className="py-2">{a.label}</td>
                      <td className="py-2 text-right tabular-nums">{num(r.maePp, 3)}</td>
                      <td className="py-2 text-right tabular-nums">{num(r.rmsePp, 3)}</td>
                      <td className="py-2 text-right tabular-nums">{num(r.wapePercent, 1)}%</td>
                      <td className="py-2 text-right text-xs font-normal text-slate-600">
                        {cmp ? (
                          <>
                            LSTM {num(cmp.maeReductionPercent, 1)}% lower
                            <span className="block text-slate-400">
                              95% CI of difference [{num(cmp.maeDifferenceCi95Pp[0], 2)}, {num(cmp.maeDifferenceCi95Pp[1], 2)}] pp
                            </span>
                          </>
                        ) : (
                          '—'
                        )}
                      </td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
          <p className="mt-3 text-xs text-slate-500">
            Honest caveat from the same evaluation: on weekends and holidays the simple previous-hour baseline had a lower MAE
            than the LSTM ({num(e.bySubset?.weekend?.previousHour?.maePp, 2)} vs{' '}
            {num(e.bySubset?.weekend?.lstm?.maePp, 2)} pp on weekends). The test period never exceeded 70%
            utilization, so the HIGH and VERY_HIGH bands are untested on real data.
          </p>
        </>
      )}
    </Card>
  )
}

function SeriesChart({ data, showBaseline }) {
  const points = useMemo(
    () =>
      data.points.map((p) => ({
        x: p.targetTime,
        values: { actual: p.actual * 100, lstm: p.lstm * 100, previousHour: p.previousHour * 100 },
      })),
    [data],
  )
  const series = [
    { key: 'actual', label: 'Actual (recorded)', color: '#0f172a', width: 2 },
    { key: 'lstm', label: 'LSTM prediction', color: '#4f46e5', width: 2 },
    ...(showBaseline ? [{ key: 'previousHour', label: 'Previous-hour baseline', color: '#d97706', dashed: true, width: 1.5 }] : []),
  ]
  return (
    <>
      <LineChart points={points} series={series} />
      <p className="mt-2 text-xs text-slate-500">{data.source} Times are Pacific (site local).</p>
    </>
  )
}
