// Thin wrapper around the Spring Boot API (proxied by Vite under /api).
// Errors carry the backend's RFC 9457 problem details so screens can show the real reason.

export class ApiError extends Error {
  constructor(status, problem) {
    super(problem?.detail || problem?.title || `Request failed (${status})`)
    this.status = status
    this.problem = problem || {}
  }
}

async function request(path, options = {}) {
  let res
  try {
    res = await fetch(path, {
      ...options,
      headers: { Accept: 'application/json', ...(options.body ? { 'Content-Type': 'application/json' } : {}) },
    })
  } catch {
    throw new ApiError(0, { title: 'Backend unreachable', detail: 'Cannot reach the backend on port 8080. Is Spring Boot running?' })
  }
  const text = await res.text()
  let body = null
  try {
    body = text ? JSON.parse(text) : null
  } catch {
    body = null
  }
  if (!res.ok) {
    if (res.status === 502 || res.status === 504 || (res.status === 500 && !body)) {
      throw new ApiError(res.status, { title: 'Backend unreachable', detail: 'The backend did not respond. Is Spring Boot running on port 8080?' })
    }
    throw new ApiError(res.status, body)
  }
  return body
}

const qs = (params) => new URLSearchParams(Object.entries(params).filter(([, v]) => v != null && v !== '')).toString()

export const api = {
  health: () => request('/api/health'),
  dbHealth: () => request('/api/health/db'),
  mlStatus: () => request('/api/forecast/status'),
  modelInfo: () => request('/api/forecast/model-info'),
  evaluation: () => request('/api/forecast/evaluation'),
  evaluationSeries: (from, to) => request(`/api/forecast/evaluation/series?${qs({ from, to })}`),
  forecast: (forecastTime) => request(`/api/forecast/next-hour?${qs({ forecastTime })}`),
  stations: () => request('/api/stations'),
  availability: (stationId, date) => request(`/api/slots/availability?${qs({ stationId, date })}`),
  quote: (stationId, startTime) => request(`/api/pricing/quote?${qs({ stationId, startTime })}`),
  bookings: (stationId) => request(`/api/bookings?${qs({ stationId })}`),
  createBooking: (body) => request('/api/bookings', { method: 'POST', body: JSON.stringify(body) }),
  cancelBooking: (id) => request(`/api/bookings/${encodeURIComponent(id)}/cancel`, { method: 'POST' }),
}
