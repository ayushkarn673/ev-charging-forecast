import { useState } from 'react'
import StatusBar from './components/StatusBar.jsx'
import Dashboard from './pages/Dashboard.jsx'
import Stations from './pages/Stations.jsx'
import Booking from './pages/Booking.jsx'
import History from './pages/History.jsx'

const TABS = [
  { key: 'dashboard', label: 'Analytics' },
  { key: 'stations', label: 'Stations' },
  { key: 'booking', label: 'Book a slot' },
  { key: 'history', label: 'Booking history' },
]

export default function App() {
  const [tab, setTab] = useState('dashboard')
  const [bookingPreset, setBookingPreset] = useState(null)
  const [bookingKey, setBookingKey] = useState(0)

  function openBooking(preset) {
    setBookingPreset(preset)
    setBookingKey((k) => k + 1) // fresh booking form with the chosen station/slot
    setTab('booking')
  }

  return (
    <div className="min-h-screen">
      <header className="bg-slate-900 text-white">
        <div className="mx-auto flex max-w-7xl flex-wrap items-center justify-between gap-4 px-4 py-4 sm:px-6">
          <div className="flex items-center gap-3">
            <div className="flex h-9 w-9 items-center justify-center rounded-lg bg-indigo-500 text-lg font-bold" aria-hidden>
              ⚡
            </div>
            <div>
              <p className="text-sm font-semibold leading-tight">EV Charge Forecast</p>
              <p className="text-xs text-slate-400">LSTM demand forecasting · dynamic slot booking · demand-based pricing</p>
            </div>
          </div>
          <StatusBar />
        </div>
        <nav className="mx-auto flex max-w-7xl gap-1 overflow-x-auto px-4 sm:px-6" aria-label="Main">
          {TABS.map((t) => (
            <button
              key={t.key}
              onClick={() => (t.key === 'booking' ? openBooking(null) : setTab(t.key))}
              className={`whitespace-nowrap rounded-t-md px-4 py-2.5 text-sm font-medium transition ${tab === t.key ? 'bg-slate-50 text-slate-900' : 'text-slate-300 hover:bg-slate-800 hover:text-white'}`}
              aria-current={tab === t.key ? 'page' : undefined}
            >
              {t.label}
            </button>
          ))}
        </nav>
      </header>

      <main className="mx-auto max-w-7xl px-4 py-6 sm:px-6">
        {tab === 'dashboard' && <Dashboard />}
        {tab === 'stations' && <Stations onBook={openBooking} />}
        {tab === 'booking' && <Booking key={bookingKey} preset={bookingPreset} onDone={() => setTab('history')} />}
        {tab === 'history' && <History />}
      </main>

      <footer className="mx-auto max-w-7xl px-4 pb-8 text-xs text-slate-400 sm:px-6">
        Forecasts: LSTM trained on ACN-Data (Caltech, Lee, Li &amp; Low, e-Energy 2019), served in historical-replay mode.
        Stations and bookings are demonstration data.
      </footer>
    </div>
  )
}
