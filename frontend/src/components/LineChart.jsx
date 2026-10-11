import { useMemo, useRef, useState } from 'react'

/**
 * Minimal responsive SVG line chart (no chart library).
 * points: [{ x: label string (ISO), values: { key: number|null } }]
 * series: [{ key, label, color, dashed? }]
 */
export default function LineChart({ points, series, height = 280, yLabel = 'Utilization (%)', format = (v) => `${v.toFixed(1)}%` }) {
  const W = 900
  const H = height
  const pad = { l: 48, r: 16, t: 12, b: 36 }
  const svgRef = useRef(null)
  const [hover, setHover] = useState(null)

  const { yMax, xs, ticks } = useMemo(() => {
    const all = points.flatMap((p) => series.map((s) => p.values[s.key])).filter((v) => v != null)
    const max = Math.max(10, ...all)
    const yMax = Math.ceil(max / 10) * 10
    const n = points.length
    const xs = points.map((_, i) => pad.l + (n <= 1 ? 0 : (i * (W - pad.l - pad.r)) / (n - 1)))
    // one x tick per local midnight
    const ticks = points.map((p, i) => ({ i, label: p.x })).filter((t) => t.label.slice(11, 13) === '00')
    return { yMax, xs, ticks }
  }, [points, series])

  if (!points.length) return <p className="py-8 text-center text-sm text-slate-500">No data for this range.</p>

  const y = (v) => pad.t + (1 - v / yMax) * (H - pad.t - pad.b)
  // Gaps (null values) lift the pen so missing hours are never drawn as data.
  const path = (key) => {
    let d = ''
    let penDown = false
    points.forEach((p, i) => {
      const v = p.values[key]
      if (v == null) {
        penDown = false
        return
      }
      d += `${penDown ? 'L' : 'M'}${xs[i].toFixed(1)},${y(v).toFixed(1)} `
      penDown = true
    })
    return d
  }

  function onMove(e) {
    const rect = svgRef.current.getBoundingClientRect()
    const px = ((e.clientX - rect.left) / rect.width) * W
    let best = 0
    for (let i = 1; i < xs.length; i++) if (Math.abs(xs[i] - px) < Math.abs(xs[best] - px)) best = i
    setHover(best)
  }

  const gridSteps = 5
  const hp = hover != null ? points[hover] : null

  return (
    <div className="relative">
      <div className="mb-3 flex flex-wrap gap-4 text-xs text-slate-600">
        {series.map((s) => (
          <span key={s.key} className="inline-flex items-center gap-1.5">
            <svg width="22" height="6" aria-hidden>
              <line x1="0" y1="3" x2="22" y2="3" stroke={s.color} strokeWidth="2.5" strokeDasharray={s.dashed ? '4 3' : undefined} />
            </svg>
            {s.label}
          </span>
        ))}
      </div>
      <svg
        ref={svgRef}
        viewBox={`0 0 ${W} ${H}`}
        className="h-auto w-full touch-none select-none"
        onMouseMove={onMove}
        onMouseLeave={() => setHover(null)}
        role="img"
        aria-label={`Line chart of ${series.map((s) => s.label).join(', ')}`}
      >
        {Array.from({ length: gridSteps + 1 }, (_, k) => {
          const v = (yMax * k) / gridSteps
          return (
            <g key={k}>
              <line x1={pad.l} x2={W - pad.r} y1={y(v)} y2={y(v)} stroke="#e2e8f0" />
              <text x={pad.l - 8} y={y(v) + 4} textAnchor="end" fontSize="11" fill="#64748b">
                {Math.round(v)}
              </text>
            </g>
          )
        })}
        <text x={14} y={pad.t + (H - pad.t - pad.b) / 2} fontSize="11" fill="#64748b" transform={`rotate(-90 14 ${pad.t + (H - pad.t - pad.b) / 2})`} textAnchor="middle">
          {yLabel}
        </text>
        {ticks.map((t) => (
          <g key={t.i}>
            <line x1={xs[t.i]} x2={xs[t.i]} y1={pad.t} y2={H - pad.b} stroke="#f1f5f9" />
            <text x={xs[t.i]} y={H - pad.b + 16} fontSize="11" fill="#64748b" textAnchor="middle">
              {t.label.slice(5, 10)}
            </text>
          </g>
        ))}
        {series.map((s) => (
          <path key={s.key} d={path(s.key)} fill="none" stroke={s.color} strokeWidth={s.width ?? 2} strokeDasharray={s.dashed ? '5 4' : undefined} strokeLinejoin="round" />
        ))}
        {hp && (
          <g>
            <line x1={xs[hover]} x2={xs[hover]} y1={pad.t} y2={H - pad.b} stroke="#94a3b8" strokeDasharray="3 3" />
            {series.map((s) =>
              hp.values[s.key] == null ? null : <circle key={s.key} cx={xs[hover]} cy={y(hp.values[s.key])} r="3.5" fill={s.color} />,
            )}
          </g>
        )}
      </svg>
      {hp && (
        <div
          className="pointer-events-none absolute top-8 z-10 rounded-md border border-slate-200 bg-white/95 px-3 py-2 text-xs shadow-lg"
          style={{ left: `${Math.min(75, (xs[hover] / W) * 100)}%` }}
        >
          <p className="mb-1 font-medium text-slate-900">{hp.x.slice(0, 16).replace('T', ' ')}</p>
          {series.map((s) => (
            <p key={s.key} className="flex justify-between gap-4 tabular-nums">
              <span style={{ color: s.color }}>{s.label}</span>
              <span className="font-medium text-slate-800">{hp.values[s.key] == null ? '—' : format(hp.values[s.key])}</span>
            </p>
          ))}
        </div>
      )}
    </div>
  )
}
