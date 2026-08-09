/**
 * MODULE 3 — driver-based forecast and budget governor.
 *
 * Four drivers projected separately, a distribution rather than a point, change
 * points on every prompt deploy, and the degradation ladder evaluated against
 * where spend actually is.
 */
import { useState } from 'react'
import {
  Area, CartesianGrid, ComposedChart, Line, ReferenceLine, ResponsiveContainer,
  Tooltip, XAxis, YAxis,
} from 'recharts'
import { api, type Forecast, type Governor } from '../api'
import { useResource } from '../useResource'
import { useApp } from '../store'
import { Card, ErrorBox, Kpi, Loading, Pill, SectionTitle } from '../components/ui'
import { pct, shortDate, usd, usdSmart } from '../format'

export function ForecastPage() {
  const useCase = useApp((s) => s.useCase)
  const [includeIncidents, setIncludeIncidents] = useState(true)
  const fc = useResource<Forecast>(() => api.forecast(useCase), [useCase])
  const gov = useResource<Governor>(
    () => fetch(`/api/v1/forecast/governor?use_case=${useCase}&include_incidents=${includeIncidents}`)
      .then((r) => r.json()),
    [useCase, includeIncidents],
  )

  if (fc.loading) return <Loading what="45 days of production traces" />
  if (fc.error) return <ErrorBox error={fc.error} />
  if (!fc.data) return null
  const f = fc.data

  return (
    <div className="space-y-5">
      <Drivers f={f} />
      <HistoryChart f={f} />
      <div className="grid gap-4 lg:grid-cols-[1fr_1.1fr]">
        <MonthCard f={f} />
        {gov.error ? <ErrorBox error={gov.error} />
          : gov.data && (
            <GovernorCard g={gov.data} includeIncidents={includeIncidents}
              onToggle={setIncludeIncidents} />
          )}
      </div>
    </div>
  )
}

function Drivers({ f }: { f: Forecast }) {
  return (
    <Card>
      <SectionTitle hint={f.regime.note}>
        Drivers — projected separately, not as one trend line
      </SectionTitle>
      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        {f.drivers.map((d) => (
          <div key={d.name} className="rounded-xl border border-slate-200/80 bg-white/50 p-4">
            <div className="text-[11px] uppercase tracking-[0.08em] text-slate-500">{d.label}</div>
            <div className="mt-1 text-2xl font-semibold tabular">
              {d.p50 >= 1000 ? d.p50.toLocaleString('en-US', { maximumFractionDigits: 0 }) : d.p50.toFixed(2)}
            </div>
            <div className="text-[11px] text-slate-400">{d.unit} · p50</div>
            <div className="mt-2 flex justify-between text-[11px] text-slate-500 tabular">
              <span>now {d.current >= 1000 ? Math.round(d.current).toLocaleString() : d.current.toFixed(2)}</span>
              <span>p95 {d.p95 >= 1000 ? Math.round(d.p95).toLocaleString() : d.p95.toFixed(2)}</span>
            </div>
            <p className="mt-2 text-[11px] leading-snug text-slate-500">{d.note}</p>
          </div>
        ))}
      </div>
      <p className="mt-3 text-[11px] leading-relaxed text-slate-500">
        Each driver keeps its own distribution and its own cause. Spend is their product, simulated{' '}
        {f.simulations.toLocaleString()} times — which is why the forecast has a p95 at all.
      </p>
    </Card>
  )
}

function HistoryChart({ f }: { f: Forecast }) {
  const rows = [
    ...f.history.map((h) => ({
      date: h.date, actual: h.spend_usd, p50: null as number | null, p95: null as number | null,
    })),
    ...f.projection.map((p) => ({
      date: p.date, actual: null as number | null, p50: p.p50_usd, p95: p.p95_usd,
    })),
  ]
  return (
    <Card>
      <SectionTitle hint="change points are prompt deploys, not anomalies">
        Daily spend, 45 recorded days and {f.projection.length} projected
      </SectionTitle>
      <ResponsiveContainer width="100%" height={280}>
        <ComposedChart data={rows} margin={{ top: 8, right: 12, bottom: 0, left: -16 }}>
          <defs>
            <linearGradient id="band" x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stopColor="#8b5cf6" stopOpacity={0.20} />
              <stop offset="100%" stopColor="#8b5cf6" stopOpacity={0.02} />
            </linearGradient>
          </defs>
          <CartesianGrid vertical={false} stroke="#f1f2fa" />
          <XAxis dataKey="date" tick={{ fontSize: 10, fill: '#9ba2be' }} axisLine={false}
            tickLine={false} tickFormatter={shortDate} minTickGap={26} />
          <YAxis tick={{ fontSize: 10, fill: '#9ba2be' }} axisLine={false} tickLine={false}
            tickFormatter={(v) => usd(Number(v), 0)} width={58} />
          <Tooltip
            formatter={(v, n) => [usd(Number(v)), String(n)]}
            labelFormatter={(l) => shortDate(String(l))}
            contentStyle={{ borderRadius: 12, border: '1px solid #e6e8f4', fontSize: 12, boxShadow: '0 14px 34px -22px rgb(27 31 54 / 0.4)' }} />
          <Area type="monotone" dataKey="p95" stroke="none" fill="url(#band)" name="p95" />
          <Line type="monotone" dataKey="p50" stroke="#8b5cf6" strokeWidth={2} dot={false}
            strokeDasharray="5 4" name="p50 projection" />
          <Line type="monotone" dataKey="actual" stroke="#5546e8" strokeWidth={2} dot={false}
            name="recorded" />
          {f.change_points.map((c) => (
            <ReferenceLine key={c.date} x={c.date} stroke="#d9820a" strokeDasharray="3 3"
              label={{
                value: c.prompt_version.replace('cv-', ''),
                position: 'insideTopRight', fontSize: 9, fill: '#d9820a',
              }} />
          ))}
        </ComposedChart>
      </ResponsiveContainer>
      <div className="mt-3 grid gap-2 sm:grid-cols-3">
        {f.change_points.map((c) => (
          <div key={c.date} className="rounded-lg border border-orange-200 bg-orange-50/50 px-3 py-2">
            <div className="text-[11px] font-medium text-orange-900">{c.prompt_version}</div>
            <div className="text-[11px] text-orange-800/80 tabular">
              {shortDate(c.date)} · daily spend {c.pct_change === null ? '—'
                : `${c.pct_change > 0 ? '+' : ''}${c.pct_change}%`} across the deploy
            </div>
          </div>
        ))}
      </div>
      <p className="mt-3 text-[11px] leading-relaxed text-slate-500">
        The forecast is fitted on the current regime only ({f.regime.days_in_regime} days since{' '}
        {f.regime.prompt_version}). Data from before the last deploy describes a system that no
        longer exists.
      </p>
    </Card>
  )
}

function MonthCard({ f }: { f: Forecast }) {
  const m = f.month
  return (
    <Card>
      <SectionTitle hint={m.month}>Month projection</SectionTitle>
      <div className="grid grid-cols-2 gap-5">
        <Kpi label="Spend to date" sub={`${m.days_elapsed} days elapsed`}>{usd(m.spend_to_date_usd, 0)}</Kpi>
        <Kpi label="Budget" sub={`${m.days_remaining} days remaining`}>{usd(m.budget_usd, 0)}</Kpi>
        <Kpi label="Projected p50" tone={m.p50_pct_of_budget > 100 ? 'fail' : 'default'}
          sub={`${pct(m.p50_pct_of_budget, 0)} of budget`}>
          {usd(m.projected_p50_usd, 0)}
        </Kpi>
        <Kpi label="Projected p95" tone="projected" sub={`${pct(m.p95_pct_of_budget, 0)} of budget`}>
          {usd(m.projected_p95_usd, 0)}
        </Kpi>
      </div>
      <div className="mt-4 rounded-xl border border-violet-200 bg-violet-50/50 p-3">
        <div className="flex items-baseline justify-between">
          <span className="text-sm font-medium text-violet-900">Tail reserve</span>
          <span className="tabular text-lg font-semibold text-[var(--projected)]">
            {usd(m.tail_reserve_usd, 0)}
          </span>
        </div>
        <p className="mt-1 text-[11px] leading-relaxed text-violet-900/70">
          The gap between p50 and p95. Budget the p50 and hold this much back, or plan to explain a
          variance one month in twenty.
        </p>
      </div>
      {m.incident_spend_usd > 0 && (
        <div className="mt-3 rounded-xl border border-red-200 bg-red-50/50 p-3">
          <div className="flex items-baseline justify-between">
            <span className="text-sm font-medium text-red-900">Incident spend this month</span>
            <span className="tabular text-lg font-semibold text-[var(--fail)]">
              {usd(m.incident_spend_usd, 2)}
            </span>
          </div>
          <p className="mt-1 text-[11px] leading-relaxed text-red-900/70">
            {f.incidents.n_traces} trace(s) above the {usd(f.incidents.threshold_usd, 2)} per-trace
            breaker limit. Counted in spend, excluded from the driver fit — an incident is not demand.
          </p>
        </div>
      )}
    </Card>
  )
}

function GovernorCard({ g, includeIncidents, onToggle }: {
  g: Governor; includeIncidents: boolean; onToggle: (v: boolean) => void
}) {
  return (
    <Card>
      <div className="mb-3 flex flex-wrap items-center justify-between gap-3">
        <SectionTitle hint="degradation ladder from policy.yaml">Budget governor</SectionTitle>
        <div className="flex gap-1">
          {[
            { v: true, label: 'All spend' },
            { v: false, label: 'Ongoing work only' },
          ].map((o) => (
            <button key={String(o.v)} onClick={() => onToggle(o.v)}
              className={`rounded-lg px-2.5 py-1 text-xs transition-colors ${
                includeIncidents === o.v ? 'bg-[var(--accent)] text-white shadow-[var(--shadow-accent)]'
                  : 'bg-slate-100 text-slate-600 hover:bg-slate-200'
              }`}>
              {o.label}
            </button>
          ))}
        </div>
      </div>

      <div className="flex items-baseline justify-between">
        <div>
          <div className="text-3xl font-semibold tabular"
            style={{ color: g.pct_of_budget >= 100 ? 'var(--fail)' : g.pct_of_budget >= 80 ? 'var(--warn)' : 'var(--ink)' }}>
            {pct(g.pct_of_budget, 1)}
          </div>
          <div className="text-xs text-slate-500">
            {usd(g.spend_to_date_usd, 0)} of {usd(g.budget_usd, 0)}
          </div>
        </div>
        {g.active_rung ? (
          <Pill tone={g.active_rung.at_pct >= 100 ? 'fail' : 'warn'}>
            {g.active_rung.action.replace(/_/g, ' ')}
          </Pill>
        ) : <Pill tone="pass">within budget</Pill>}
      </div>

      <div className="mt-4 space-y-2">
        {g.ladder.map((r) => (
          <div key={r.at_pct}
            className={`rounded-xl border p-3 ${
              r.state === 'active' ? 'border-amber-300 bg-amber-50/60' : 'border-slate-200 bg-white/40'
            }`}>
            <div className="flex items-center justify-between gap-3">
              <div className="flex items-center gap-2.5">
                <span className="tabular text-xs font-semibold text-slate-500">{r.at_pct}%</span>
                <span className="text-sm font-medium">{r.action.replace(/_/g, ' ')}</span>
              </div>
              <span className="tabular text-xs text-slate-500">
                {usd(r.threshold_usd, 0)}
                {r.state === 'active' && <span className="ml-2 font-semibold text-[var(--warn)]">active</span>}
              </span>
            </div>
            <p className="mt-1 text-[11px] leading-relaxed text-slate-500">{r.description}</p>
          </div>
        ))}
      </div>

      {g.next_rung && (
        <div className="mt-3 rounded-lg bg-slate-50 px-3 py-2 text-xs text-slate-600">
          Next rung at {g.next_rung.at_pct}% —{' '}
          <span className="tabular font-medium">{usdSmart(g.next_rung.usd_until)}</span> away
          {g.next_rung.projected_date && (
            <> · p50 path crosses it on{' '}
              <span className="font-medium">{shortDate(g.next_rung.projected_date)}</span></>
          )}
        </div>
      )}
      <div className="mt-2 text-xs text-slate-500 tabular">
        End of month: p50 {usd(g.projected_end_of_month.p50_usd, 0)}
        {g.projected_end_of_month.p50_rung !== null && ` → rung ${g.projected_end_of_month.p50_rung}%`}
        {' · '}p95 {usd(g.projected_end_of_month.p95_usd, 0)}
        {g.projected_end_of_month.p95_rung !== null && ` → rung ${g.projected_end_of_month.p95_rung}%`}
      </div>
    </Card>
  )
}
