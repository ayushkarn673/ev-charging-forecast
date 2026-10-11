import { useState } from 'react'
import StatusBar from './components/StatusBar.jsx'
import Home from './pages/Home.jsx'
import Dashboard from './pages/Dashboard.jsx'
import Stations from './pages/Stations.jsx'
import Booking from './pages/Booking.jsx'
import History from './pages/History.jsx'

const TABS = [
  { key: 'home', label: 'Home' },
  { key: 'stations', label: 'Stations' },
  { key: 'booking', label: 'Book' },
  { key: 'history', label: 'My bookings' },
]

export default function App() {
  const [tab, setTab] = useState('home')
  const [bookingPreset, setBookingPreset] = useState(null)
  const [bookingKey, setBookingKey] = useState(0)

  function openBooking(preset) {
    setBookingPreset(preset)
    setBookingKey((k) => k + 1) // fresh booking form with the chosen station/slot
    setTab('booking')
  }

  function go(key) {
    if (key === 'booking') openBooking(null)
    else setTab(key)
    window.scrollTo({ top: 0 })
  }

  const pill = (active) =>
    `whitespace-nowrap rounded-full px-4 py-1.5 text-sm font-medium transition focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-violet-600 ${
      active ? 'bg-slate-900 text-white' : 'text-slate-600 hover:bg-slate-100 hover:text-slate-900'
    }`

  return (
    <div className="min-h-screen bg-gradient-to-b from-violet-50/60 via-slate-50 to-slate-50">
      <header className="sticky top-0 z-20 border-b border-slate-200/70 bg-white/80 backdrop-blur">
        <div className="mx-auto flex max-w-6xl flex-wrap items-center justify-between gap-3 px-4 py-3 sm:px-6">
          <button onClick={() => go('home')} className="flex items-center gap-2.5 rounded-full focus-visible:outline-2 focus-visible:outline-violet-600" aria-label="EVCharge home">
            <span className="flex h-9 w-9 items-center justify-center rounded-xl bg-gradient-to-br from-violet-600 to-fuchsia-500 text-lg text-white shadow-sm" aria-hidden>
              ⚡
            </span>
            <span className="text-left">
              <span className="block text-base font-bold leading-tight tracking-tight text-slate-900">EVCharge</span>
              <span className="hidden text-xs text-slate-500 sm:block">charge smarter, pay less</span>
            </span>
          </button>
          <nav className="flex gap-1 overflow-x-auto" aria-label="Main">
            {TABS.map((t) => (
              <button key={t.key} onClick={() => go(t.key)} className={pill(tab === t.key)} aria-current={tab === t.key ? 'page' : undefined}>
                {t.label}
              </button>
            ))}
          </nav>
        </div>
      </header>

      <main className="mx-auto max-w-6xl px-4 py-8 sm:px-6">
        {tab === 'home' && <Home onBook={openBooking} onNavigate={go} />}
        {tab === 'stations' && <Stations onBook={openBooking} />}
        {tab === 'booking' && <Booking key={bookingKey} preset={bookingPreset} onDone={() => go('history')} />}
        {tab === 'history' && <History onBook={() => go('booking')} />}
        {tab === 'nerd' && (
          <div className="space-y-6">
            <div className="flex flex-wrap items-center justify-between gap-3">
              <div>
                <h1 className="text-2xl font-bold tracking-tight text-slate-900">Nerd stats 🧠</h1>
                <p className="mt-1 text-sm text-slate-500">What's under the hood: the AI model, how accurate it is, and how prices are set.</p>
              </div>
              <div className="rounded-full border border-slate-200 bg-white px-4 py-2">
                <StatusBar />
              </div>
            </div>
            <Dashboard />
          </div>
        )}
      </main>

      <footer className="mx-auto flex max-w-6xl flex-wrap items-center justify-between gap-3 px-4 pb-10 text-xs text-slate-400 sm:px-6">
        <p>Demo project · stations and bookings are sample data · prices use AI predictions from historical charging data.</p>
        <button onClick={() => go('nerd')} className={`rounded-full px-3 py-1 font-medium ${tab === 'nerd' ? 'bg-slate-900 text-white' : 'text-slate-500 ring-1 ring-slate-300 hover:bg-white'}`}>
          🧠 Nerd stats
        </button>
      </footer>
    </div>
  )
}
