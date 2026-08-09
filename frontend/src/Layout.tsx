import { NavLink, Outlet, useLocation } from 'react-router-dom'
import { AnimatePresence, motion } from 'framer-motion'
import type { ReactNode } from 'react'
import { api, type Spine } from './api'
import { useResource } from './useResource'
import { useApp } from './store'
import { usd } from './format'

/** Stroke icons, 20px grid. Inline so the app pulls no icon dependency. */
const I = {
  overview: 'M4 13h6V4H4v9Zm0 7h6v-5H4v5Zm10 0h6v-9h-6v9Zm0-16v5h6V4h-6Z',
  promotion: 'M5 19V9m7 10V5m7 14v-7',
  explorer: 'M4 6h16M4 12h10M4 18h6',
  forecast: 'M4 16l4.5-5 3.5 3.5L20 6',
  simulator: 'M6 4v6m0 4v6m6-16v10m0 4v2m6-16v3m0 4v9',
  breakers: 'M13 3 5 14h6l-1 7 8-11h-6l1-7Z',
  framework: 'M12 3 4 7.5v9L12 21l8-4.5v-9L12 3Zm0 0v18m8-13.5L4 16.5m16 0L4 7.5',
} as const

const NAV: { to: string; label: string; tag: string; icon: keyof typeof I }[] = [
  { to: '/', label: 'Overview', tag: 'M6', icon: 'overview' },
  { to: '/promotion', label: 'Promotion board', tag: 'M1', icon: 'promotion' },
  { to: '/explorer', label: 'Cost explorer', tag: 'M2', icon: 'explorer' },
  { to: '/forecast', label: 'Forecast & budget', tag: 'M3', icon: 'forecast' },
  { to: '/simulator', label: 'Simulator', tag: 'M4', icon: 'simulator' },
  { to: '/breakers', label: 'Circuit breakers', tag: 'M5', icon: 'breakers' },
  { to: '/framework', label: 'Framework', tag: '', icon: 'framework' },
]

const SUBTITLE: Record<string, string> = {
  '/': 'Cost per successful outcome, and what the floors refused',
  '/promotion': 'Paired evaluation against the declared quality floor',
  '/explorer': 'Where the spend goes, including the buckets nobody attributes',
  '/forecast': 'Drivers projected separately, with the degradation ladder',
  '/simulator': 'Projected lever effects, checked against the floor before they run',
  '/breakers': 'A runaway trace replayed against the policy breakers',
  '/framework': 'The spine, the adapters, and the cost of onboarding a workload',
}

function Icon({ d, className = '' }: { d: string; className?: string }) {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7"
      strokeLinecap="round" strokeLinejoin="round" className={`h-[18px] w-[18px] ${className}`}>
      <path d={d} />
    </svg>
  )
}

/**
 * Which workload is being governed. The list comes from policy.yaml, so an
 * onboarded agent appears here without a frontend change — including ATLAS,
 * which this application did not build.
 */
function UseCasePicker({ spine }: { spine: Spine | null }) {
  const useCase = useApp((s) => s.useCase)
  const setUseCase = useApp((s) => s.setUseCase)
  const names = spine ? Object.keys(spine.policy.use_cases) : [useCase]
  return (
    <label className="flex items-center gap-2 rounded-full border border-slate-200 bg-white py-1.5 pl-3.5 pr-2 shadow-[0_1px_2px_rgb(27_31_54/0.04)]">
      <span className="text-[10px] font-semibold uppercase tracking-[0.12em] text-slate-400">
        Workload
      </span>
      <select
        value={useCase}
        onChange={(e) => setUseCase(e.target.value)}
        className="focus-ring cursor-pointer rounded-full bg-transparent pr-1 text-[13px] font-medium text-slate-800 outline-none"
      >
        {names.map((n) => (
          <option key={n} value={n}>{spine?.policy.use_cases[n]?.label ?? n}</option>
        ))}
      </select>
    </label>
  )
}

/** The declared contract for the selected workload — policy, not measurement. */
function PolicyCard({ spine }: { spine: Spine | null }) {
  const useCase = useApp((s) => s.useCase)
  const policy = spine?.policy.use_cases[useCase]
  const floors = policy ? Object.entries(policy.quality_floor) : []
  return (
    <div className="rounded-2xl border border-slate-200 bg-slate-50/70 p-3.5">
      <div className="text-[10px] font-semibold uppercase tracking-[0.12em] text-slate-400">
        Declared contract
      </div>
      {policy ? (
        <>
          <dl className="mt-2.5 space-y-1.5">
            {floors.map(([metric, floor]) => (
              <Row key={metric} k={metric.replace(/_/g, ' ')} v={String(floor)} />
            ))}
            <Row k="latency ≤" v={`${(policy.latency_ceiling_ms / 1000).toFixed(0)}s`} />
            <Row k="budget" v={`${usd(policy.monthly_budget_usd, 0)}/mo`} />
          </dl>
          <p className="mt-3 border-t border-slate-200 pt-2.5 text-[10px] leading-relaxed text-slate-400">
            From <code className="text-slate-500">policy.yaml</code>. Edit a floor and
            <code className="text-slate-500"> admin/reset</code> to re-decide live.
          </p>
        </>
      ) : (
        <div className="mt-2 text-[11px] text-slate-400">Reading policy…</div>
      )}
    </div>
  )
}

function Row({ k, v }: { k: string; v: ReactNode }) {
  return (
    <div className="flex items-baseline justify-between gap-2">
      <dt className="truncate text-[11px] text-slate-500">{k}</dt>
      <dd className="tabular shrink-0 text-[11px] font-semibold text-slate-700">{v}</dd>
    </div>
  )
}

export function Layout() {
  const location = useLocation()
  const { data: spine } = useResource<Spine>(() => api.spine(), [])
  const current = NAV.find((n) => n.to === location.pathname) ?? NAV[0]

  return (
    <div className="flex min-h-full">
      <aside className="sticky top-0 hidden h-screen w-[252px] shrink-0 flex-col border-r border-slate-200 bg-white/80 px-4 py-5 backdrop-blur-xl lg:flex">
        <div className="flex items-center gap-2.5 px-2">
          <span
            className="grid h-9 w-9 place-items-center rounded-xl text-white"
            style={{ background: 'linear-gradient(145deg,#6a5cf0,#4636d9)', boxShadow: 'var(--shadow-accent)' }}
          >
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.9"
              strokeLinecap="round" strokeLinejoin="round" className="h-[19px] w-[19px]">
              <path d="M12 3 5 6v6c0 4.2 2.9 7.6 7 9 4.1-1.4 7-4.8 7-9V6l-7-3Z" />
              <path d="m9 12 2 2 4-4" />
            </svg>
          </span>
          <div className="leading-tight">
            <div className="text-[14px] font-bold tracking-tight text-slate-900">Cost-Quality</div>
            <div className="text-[11px] font-medium text-slate-400">Control Plane</div>
          </div>
        </div>

        <nav className="mt-7 flex flex-col gap-1">
          {NAV.map((item) => (
            <NavLink
              key={item.to}
              to={item.to}
              end={item.to === '/'}
              className={({ isActive }) =>
                `focus-ring relative flex items-center gap-3 rounded-xl px-3 py-2.5 text-[13px] font-medium transition-colors ${
                  isActive ? 'text-white' : 'text-slate-500 hover:bg-slate-50 hover:text-slate-900'
                }`
              }
            >
              {({ isActive }) => (
                <>
                  {isActive && (
                    <motion.span
                      layoutId="nav-pill"
                      className="nav-active absolute inset-0 rounded-xl"
                      transition={{ type: 'spring', stiffness: 420, damping: 36 }}
                    />
                  )}
                  <Icon d={I[item.icon]} className="relative shrink-0" />
                  <span className="relative flex-1 truncate">{item.label}</span>
                  {item.tag && (
                    <span
                      className={`relative rounded-md px-1.5 py-0.5 text-[9px] font-bold tracking-wide ${
                        isActive ? 'bg-white/20 text-white' : 'bg-slate-100 text-slate-400'
                      }`}
                    >
                      {item.tag}
                    </span>
                  )}
                </>
              )}
            </NavLink>
          ))}
        </nav>

        <div className="mt-auto pt-6">
          <PolicyCard spine={spine} />
        </div>
      </aside>

      <div className="flex min-w-0 flex-1 flex-col">
        <header className="sticky top-0 z-20 border-b border-slate-200 bg-white/75 backdrop-blur-xl">
          <div className="mx-auto flex max-w-[1400px] flex-wrap items-center justify-between gap-x-6 gap-y-3 px-6 py-3.5">
            <div className="min-w-0">
              <h1 className="flex items-center gap-2.5 text-[16px] font-bold tracking-tight text-slate-900">
                <span className="lg:hidden">
                  <Icon d={I[current.icon]} className="text-[var(--accent)]" />
                </span>
                {current.label}
              </h1>
              <p className="mt-0.5 truncate text-[12px] text-slate-500">{SUBTITLE[current.to]}</p>
            </div>
            <div className="flex items-center gap-3">
              <code className="hidden rounded-full bg-slate-100 px-3 py-1.5 text-[11px] font-medium text-slate-500 2xl:inline">
                minimize cost s.t. quality ≥ floor ∧ latency ≤ ceiling
              </code>
              <UseCasePicker spine={spine} />
            </div>
          </div>

          {/* Nav collapses into the header below lg, where the rail is hidden. */}
          <nav className="flex gap-1 overflow-x-auto border-t border-slate-200 px-4 py-2 lg:hidden">
            {NAV.map((item) => (
              <NavLink
                key={item.to}
                to={item.to}
                end={item.to === '/'}
                className={({ isActive }) =>
                  `shrink-0 rounded-lg px-3 py-1.5 text-[12px] font-medium transition-colors ${
                    isActive ? 'nav-active' : 'text-slate-500 hover:bg-slate-50'
                  }`
                }
              >
                {item.label}
              </NavLink>
            ))}
          </nav>
        </header>

        <main className="mx-auto w-full max-w-[1400px] flex-1 px-6 py-7">
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
    </div>
  )
}
