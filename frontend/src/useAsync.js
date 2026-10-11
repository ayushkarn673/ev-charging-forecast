import { useCallback, useEffect, useState } from 'react'

/** Runs an async loader when deps change; returns { data, error, loading, reload }. */
export function useAsync(loader, deps) {
  const [state, setState] = useState({ data: null, error: null, loading: true })
  const [tick, setTick] = useState(0)
  const reload = useCallback(() => setTick((t) => t + 1), [])

  useEffect(() => {
    let cancelled = false
    setState((s) => ({ data: s.data, error: null, loading: true }))
    loader()
      .then((data) => !cancelled && setState({ data, error: null, loading: false }))
      .catch((error) => !cancelled && setState({ data: null, error, loading: false }))
    return () => {
      cancelled = true
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [...deps, tick])

  return { ...state, reload }
}
