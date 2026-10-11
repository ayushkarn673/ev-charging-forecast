import { hhmm } from '../format.js'

/** 24 one-hour slots of a day. Selectable only when the backend says the slot is bookable. */
export default function SlotGrid({ availability, selected, onSelect }) {
  if (!availability) return null
  return (
    <div>
      <div className="grid grid-cols-3 gap-2 sm:grid-cols-4 lg:grid-cols-6">
        {availability.slots.map((s) => {
          const isSelected = selected === s.startTime
          const full = s.available === 0
          const base = 'rounded-lg border px-2.5 py-2 text-left text-xs transition'
          const cls = isSelected
            ? 'border-indigo-600 bg-indigo-600 text-white shadow'
            : !s.bookable
              ? full
                ? 'cursor-not-allowed border-rose-200 bg-rose-50 text-rose-400'
                : 'cursor-not-allowed border-slate-200 bg-slate-50 text-slate-400'
              : 'border-slate-200 bg-white text-slate-700 hover:border-indigo-400 hover:bg-indigo-50'
          return (
            <button
              key={s.startTime}
              type="button"
              disabled={!s.bookable || !onSelect}
              onClick={() => onSelect?.(s.startTime)}
              className={`${base} ${cls}`}
              title={s.bookable ? 'Available' : full ? 'All chargers booked' : 'Not bookable (past or too far ahead)'}
            >
              <span className="block font-semibold tabular-nums">
                {hhmm(s.startTime)}–{hhmm(s.endTime)}
              </span>
              <span className="block tabular-nums">
                {full ? 'Full' : `${s.available}/${availability.capacity} free`}
              </span>
            </button>
          )
        })}
      </div>
      <div className="mt-3 flex flex-wrap gap-4 text-xs text-slate-500">
        <span className="inline-flex items-center gap-1.5"><span className="h-3 w-3 rounded border border-slate-300 bg-white" />Available</span>
        <span className="inline-flex items-center gap-1.5"><span className="h-3 w-3 rounded border border-rose-200 bg-rose-50" />Fully booked</span>
        <span className="inline-flex items-center gap-1.5"><span className="h-3 w-3 rounded border border-slate-200 bg-slate-100" />Past / outside booking window</span>
      </div>
    </div>
  )
}
