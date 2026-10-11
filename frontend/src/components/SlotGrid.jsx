import { hhmm } from '../format.js'

// Mirrors the backend SlotStatus enum (GET /api/slots/availability -> slots[].status).
const STATUS = {
  AVAILABLE: {
    text: (s, cap) => `${s.available}/${cap} free`,
    say: (s, cap) => `available, ${s.available} of ${cap} chargers free`,
    cls: 'border-slate-200 bg-white text-slate-700 hover:border-indigo-400 hover:bg-indigo-50',
  },
  FULL: {
    text: () => 'Full',
    say: () => 'fully booked, cannot be booked',
    cls: 'cursor-not-allowed border-rose-200 bg-rose-50 text-rose-500',
  },
  STARTED: {
    text: () => 'Started',
    say: () => 'already started, cannot be booked',
    cls: 'cursor-not-allowed border-slate-200 bg-slate-100 text-slate-400',
  },
  NOT_OPEN: {
    text: () => 'Not open yet',
    say: () => 'outside the 14-day booking window, cannot be booked yet',
    cls: 'cursor-not-allowed border-dashed border-slate-300 bg-white text-slate-400',
  },
}

/** Status from the backend; derived only if an older backend omits it. */
function statusOf(s) {
  if (s.status && STATUS[s.status]) return s.status
  if (s.bookable) return 'AVAILABLE'
  return s.available === 0 && Date.parse(s.startTime) > Date.now() ? 'FULL' : 'STARTED'
}

/** 24 one-hour slots of a day. Selectable only when the backend says the slot is bookable. */
export default function SlotGrid({ availability, selected, onSelect }) {
  if (!availability) return null
  const cap = availability.capacity
  return (
    <div>
      <div className="grid grid-cols-3 gap-2 sm:grid-cols-4 lg:grid-cols-6" role="group" aria-label="One-hour charging slots">
        {availability.slots.map((s) => {
          const status = statusOf(s)
          const st = STATUS[status]
          const isSelected = selected === s.startTime
          const bookable = status === 'AVAILABLE'
          const time = `${hhmm(s.startTime)}–${hhmm(s.endTime)}`
          const cls = isSelected ? 'border-indigo-600 bg-indigo-600 text-white shadow' : st.cls
          return (
            <button
              key={s.startTime}
              type="button"
              disabled={!bookable || !onSelect}
              aria-pressed={onSelect ? isSelected : undefined}
              aria-label={`${hhmm(s.startTime)} to ${hhmm(s.endTime)}: ${isSelected ? 'selected, ' : ''}${st.say(s, cap)}`}
              title={st.say(s, cap)}
              onClick={() => onSelect?.(s.startTime)}
              className={`rounded-lg border px-2.5 py-2 text-left text-xs transition focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-indigo-600 ${cls}`}
            >
              <span className="block font-semibold tabular-nums">{time}</span>
              <span className="block tabular-nums">{st.text(s, cap)}</span>
            </button>
          )
        })}
      </div>
      <div className="mt-3 flex flex-wrap gap-4 text-xs text-slate-500">
        <span className="inline-flex items-center gap-1.5"><span className="h-3 w-3 rounded border border-slate-300 bg-white" aria-hidden />Available</span>
        <span className="inline-flex items-center gap-1.5"><span className="h-3 w-3 rounded border border-rose-200 bg-rose-50" aria-hidden />Full</span>
        <span className="inline-flex items-center gap-1.5"><span className="h-3 w-3 rounded border border-slate-200 bg-slate-100" aria-hidden />Started</span>
        <span className="inline-flex items-center gap-1.5"><span className="h-3 w-3 rounded border border-dashed border-slate-300 bg-white" aria-hidden />Not open yet (more than 14 days ahead)</span>
      </div>
    </div>
  )
}
