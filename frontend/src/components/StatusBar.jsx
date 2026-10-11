import { useEffect, useState } from 'react'
import { api } from '../api.js'

const CHECKS = [
  { key: 'backend', label: 'Backend', run: api.health },
  { key: 'db', label: 'MySQL', run: api.dbHealth },
  { key: 'ml', label: 'LSTM service', run: api.mlStatus },
]

/** Live status of the three services, re-checked every 30 s. */
export default function StatusBar() {
  const [status, setStatus] = useState({})

  useEffect(() => {
    let alive = true
    async function check() {
      const results = await Promise.all(
        CHECKS.map((c) =>
          c.run().then(
            () => [c.key, 'up'],
            () => [c.key, 'down'],
          ),
        ),
      )
      if (alive) setStatus(Object.fromEntries(results))
    }
    check()
    const id = setInterval(check, 30000)
    return () => {
      alive = false
      clearInterval(id)
    }
  }, [])

  return (
    <div className="flex flex-wrap items-center gap-3 text-xs">
      {CHECKS.map((c) => {
        const s = status[c.key]
        const color = s === 'up' ? 'bg-emerald-500' : s === 'down' ? 'bg-rose-500' : 'bg-slate-300'
        return (
          <span key={c.key} className="inline-flex items-center gap-1.5 text-slate-300" title={s ? `${c.label}: ${s}` : 'checking…'}>
            <span className={`h-2 w-2 rounded-full ${color}`} />
            {c.label}
          </span>
        )
      })}
    </div>
  )
}
