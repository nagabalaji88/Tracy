import { NavLink, Outlet, useLocation } from 'react-router-dom'
import { AnimatePresence, motion } from 'framer-motion'

const NAV = [
  { to: '/', label: 'Overview', tag: 'M6' },
  { to: '/promotion', label: 'Promotion board', tag: 'M1' },
  { to: '/explorer', label: 'Cost explorer', tag: 'M2' },
  { to: '/forecast', label: 'Forecast & budget', tag: 'M3' },
  { to: '/simulator', label: 'Simulator', tag: 'M4' },
  { to: '/breakers', label: 'Circuit breakers', tag: 'M5' },
  { to: '/framework', label: 'Framework', tag: '' },
]

export function Layout() {
  const location = useLocation()
  return (
    <div className="min-h-full">
      <header className="sticky top-0 z-20 border-b border-slate-200/70 bg-white/70 backdrop-blur-xl">
        <div className="mx-auto flex max-w-[1400px] flex-wrap items-center gap-x-8 gap-y-3 px-6 py-3">
          <div className="flex items-baseline gap-3">
            <span className="text-[15px] font-semibold tracking-tight">Cost-Quality Control Plane</span>
            <code className="hidden text-[11px] text-slate-400 lg:inline">
              minimize cost s.t. quality ≥ floor ∧ latency ≤ ceiling
            </code>
          </div>
          <nav className="flex flex-wrap items-center gap-1">
            {NAV.map((item) => (
              <NavLink
                key={item.to}
                to={item.to}
                end={item.to === '/'}
                className={({ isActive }) =>
                  `relative rounded-lg px-3 py-1.5 text-[13px] transition-colors ${
                    isActive ? 'text-slate-900' : 'text-slate-500 hover:text-slate-800'
                  }`
                }
              >
                {({ isActive }) => (
                  <>
                    {isActive && (
                      <motion.span
                        layoutId="nav-pill"
                        className="absolute inset-0 rounded-lg bg-slate-900/[0.06]"
                        transition={{ type: 'spring', stiffness: 400, damping: 34 }}
                      />
                    )}
                    <span className="relative">{item.label}</span>
                    {item.tag && (
                      <span className="relative ml-1.5 text-[10px] font-medium text-slate-400">{item.tag}</span>
                    )}
                  </>
                )}
              </NavLink>
            ))}
          </nav>
        </div>
      </header>

      <main className="mx-auto max-w-[1400px] px-6 py-7">
        <AnimatePresence mode="wait">
          <motion.div
            key={location.pathname}
            initial={{ opacity: 0, y: 8 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: -6 }}
            transition={{ duration: 0.22, ease: [0.22, 1, 0.36, 1] }}
          >
            <Outlet />
          </motion.div>
        </AnimatePresence>
      </main>
    </div>
  )
}
