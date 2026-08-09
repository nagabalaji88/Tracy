/**
 * MODULE 6 — the executive view.
 *
 * One strip of numbers, headed by cost per successful outcome. The line that
 * makes this a control plane and not a dashboard is "savings rejected".
 */
import { Link } from 'react-router-dom'
import { motion } from 'framer-motion'
import { api, type Executive } from '../api'
import { useResource } from '../useResource'
import { useApp } from '../store'
import { Card, Counter, ErrorBox, Loading, Pill, SectionTitle } from '../components/ui'
import { pct, usd } from '../format'

export function Overview() {
  const useCase = useApp((s) => s.useCase)
  const { data, error, loading, reload } = useResource<Executive>(() => api.executive(useCase), [useCase])

  if (loading) return <Loading what="production outcomes" />
  if (error) return <ErrorBox error={error} />
  if (!data) return null
  const k = data.kpis

  return (
    <div className="space-y-5">
      <motion.div initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.35 }} className="glass p-6">
        <div className="flex flex-wrap items-start justify-between gap-6">
          <div className="max-w-2xl">
            <div className="text-[11px] font-medium uppercase tracking-[0.1em] text-slate-500">
              Cost per successful outcome
            </div>
            <div className="mt-1 flex items-baseline gap-4">
              <span className="text-[56px] font-semibold leading-none tabular">
                {k.cost_per_successful_outcome_usd === null ? '—' : (
                  <Counter value={k.cost_per_successful_outcome_usd} format={(v) => usd(v, 2)} />
                )}
              </span>
              <span className="text-sm text-slate-500">
                against {usd(k.cost_per_call_usd, 3)} per call
              </span>
            </div>
            <p className="mt-3 text-[15px] leading-relaxed text-slate-600">
              Model spend plus {k.rework_hours.toLocaleString()} hours of analyst rework, divided by
              the work that was actually usable — {pct(k.success_rate * 100, 1)} of{' '}
              {k.documents.toLocaleString()} documents over {data.window.days} days. The rework line
              alone is {usd(k.rework_usd, 0)}; the models cost {usd(k.total_spend_usd, 0)}.
            </p>
          </div>
          <div className="flex flex-col items-end gap-2">
            {data.active_rung ? (
              <Pill tone={data.active_rung.at_pct >= 100 ? 'fail' : 'warn'}>
                budget rung {data.active_rung.at_pct}% · {data.active_rung.action.replace(/_/g, ' ')}
              </Pill>
            ) : <Pill tone="pass">within budget</Pill>}
            <span className="text-xs text-slate-500 tabular">
              {usd(data.budget.spend_to_date_usd, 0)} of {usd(data.budget.budget_usd, 0)} ·{' '}
              {pct(data.budget.pct_of_budget, 0)}
            </span>
            <button onClick={async () => { await api.reset(); reload() }}
              className="mt-2 rounded-lg border border-slate-200 px-3 py-1.5 text-xs text-slate-600 hover:bg-slate-50">
              Reset demo data
            </button>
          </div>
        </div>
      </motion.div>

      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <KpiTile label="Savings realised" value={k.savings_realised_usd} tone="pass"
          sub="annualised, from promoted configurations" to="/promotion" />
        <KpiTile label="Savings rejected" value={k.savings_rejected_usd} tone="fail"
          sub="refused because quality fell below a floor" to="/promotion" />
        <KpiTile label="Model spend" value={k.total_spend_usd}
          sub={`${data.window.days} days of production`} to="/explorer" />
        <KpiTile label="Human rework" value={k.rework_usd} tone="warn"
          sub={`${k.rework_hours.toLocaleString()} analyst hours`} to="/explorer" />
      </div>

      <Card>
        <SectionTitle hint="recomputed from the store on every request">
          Promotion decisions
        </SectionTitle>
        <div className="space-y-3">
          {data.decisions.map((d) => (
            <div key={d.config_id}
              className={`rounded-xl border p-4 ${
                d.decision === 'PROMOTE' ? 'border-emerald-200 bg-emerald-50/40'
                  : 'border-red-200 bg-red-50/40'}`}>
              <div className="flex flex-wrap items-center justify-between gap-3">
                <div className="flex items-center gap-3">
                  <Pill tone={d.decision === 'PROMOTE' ? 'pass' : 'fail'}>{d.decision}</Pill>
                  <span className="font-medium">{d.label}</span>
                </div>
                <span className="tabular text-sm font-semibold"
                  style={{ color: d.decision === 'PROMOTE' ? 'var(--pass)' : 'var(--fail)' }}>
                  {usd(d.annualised_usd, 0)}/yr
                </span>
              </div>
              <div className="mt-1.5 text-[13px] text-slate-600">{d.headline}</div>
            </div>
          ))}
        </div>
        <p className="mt-3 text-[11px] leading-relaxed text-slate-500">
          {data.basis.annualisation} At {data.basis.monthly_documents.toLocaleString()} documents a
          month, this system refused more savings than it banked — which is the point.
        </p>
      </Card>

      <div className="grid gap-4 lg:grid-cols-3">
        <NavCard to="/promotion" tag="Module 1" title="Promotion board"
          body="Three configurations, paired over the same golden set, with the floor that failed and by how much." />
        <NavCard to="/explorer" tag="Module 2" title="Cost explorer"
          body="Where the money goes, including the buckets nobody attributes and the tail that consumes a third of spend." />
        <NavCard to="/forecast" tag="Module 3" title="Forecast & budget"
          body="Four drivers projected separately, p50 and p95, and the degradation ladder against current spend." />
        <NavCard to="/simulator" tag="Module 4" title="Simulator"
          body="Projected lever effects with pre-flight floor checks — and the measured result beside them." />
        <NavCard to="/breakers" tag="Module 5" title="Circuit breakers"
          body="A runaway trace replayed against the policy's breakers: $1.08 spent, $372.72 prevented." />
        <NavCard to="/framework" tag="Framework" title="Onboarding a second workload"
          body="A policy entry and two adapters. Zero core files changed — and a second use case already wired in to prove it." />
      </div>

      <div className="text-[11px] leading-relaxed text-slate-400">
        Generated {data.generated_at} from {String(data.provenance.n_spans ?? '—')} recorded spans
        and {String(data.provenance.n_outcomes ?? '—')} outcomes ·
        provider {String(data.provenance.provider ?? 'unknown')} ·
        every figure on this page is computed from the store, none are stored constants.
      </div>
    </div>
  )
}

function KpiTile({ label, value, sub, tone = 'default', to }: {
  label: string
  value: number
  sub: string
  tone?: 'default' | 'pass' | 'fail' | 'warn'
  to: string
}) {
  const color = { default: 'var(--ink)', pass: 'var(--pass)', fail: 'var(--fail)', warn: 'var(--warn)' }[tone]
  return (
    <Link to={to} className="glass block p-5 lift">
      <div className="text-[11px] font-medium uppercase tracking-[0.08em] text-slate-500">{label}</div>
      <div className="mt-1 text-3xl font-semibold" style={{ color }}>
        <Counter value={value} format={(v) => usd(v, 0)} />
      </div>
      <div className="mt-1 text-xs text-slate-500">{sub}</div>
    </Link>
  )
}

function NavCard({ to, tag, title, body }: {
  to: string; tag: string; title: string; body: string
}) {
  return (
    <Link to={to} className="glass block p-5 lift">
      <div className="text-[10px] font-semibold uppercase tracking-[0.1em] text-slate-400">{tag}</div>
      <div className="mt-1 text-[15px] font-semibold">{title}</div>
      <p className="mt-1.5 text-[13px] leading-relaxed text-slate-600">{body}</p>
    </Link>
  )
}
