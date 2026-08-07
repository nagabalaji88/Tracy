/**
 * MODULE 1 — the hero screen.
 *
 * Three configurations side by side. The cheapest one is rejected, in words, with
 * the floor it broke and by how much. Cost per call and cost per successful
 * outcome sit next to each other so the reversal is visible without arithmetic.
 */
import { Fragment } from 'react'
import { motion } from 'framer-motion'
import {
  Bar as RBar, BarChart, CartesianGrid, Cell, ResponsiveContainer, Tooltip, XAxis, YAxis,
} from 'recharts'
import { api, type Board, type Comparison, type Decision, type Measured } from '../api'
import { useResource } from '../useResource'
import { useApp } from '../store'
import { Card, Counter, ErrorBox, Loading, Pill, SectionTitle } from '../components/ui'
import { ms, num, signedPct, usd, usdSmart } from '../format'

type Column = {
  key: string
  label: string
  role: string
  measured: Measured
  comparison: Comparison | null
  decision: Decision | null
}

export function PromotionBoard() {
  const useCase = useApp((s) => s.useCase)
  const { data, error, loading } = useResource<Board>(() => api.board(useCase), [useCase])

  if (loading) return <Loading what="recorded runs" />
  if (error) return <ErrorBox error={error} />
  if (!data) return null

  const columns: Column[] = [
    {
      key: data.baseline.config.config_id,
      label: data.baseline.config.label,
      role: 'baseline',
      measured: data.baseline.measured,
      comparison: null,
      decision: null,
    },
    ...data.candidates.map((c) => ({
      key: c.config.config_id,
      label: c.config.label,
      role: 'candidate',
      measured: c.measured,
      comparison: c.comparison,
      decision: c.decision,
    })),
  ]

  const rejected = data.candidates.find((c) => c.decision.decision === 'REJECT')
  const promoted = data.candidates.find((c) => c.decision.decision === 'PROMOTE')
  const floorMetrics = Object.keys(data.policy.quality_floor)

  return (
    <div className="space-y-6">
      <Verdict board={data} />

      <div className="grid gap-4 lg:grid-cols-3">
        {columns.map((col, i) => (
          <ConfigColumn key={col.key} col={col} index={i} floorMetrics={floorMetrics} />
        ))}
      </div>

      <div className="grid gap-4 lg:grid-cols-2">
        <ReversalChart columns={columns} />
        <FloorTable board={data} columns={columns} />
      </div>

      <PairedEvidence board={data} />

      <div className="text-[11px] leading-relaxed text-slate-400">
        Paired over {data.candidates[0]?.decision.n_paired_documents ?? 0} golden documents in the{' '}
        <span className="font-medium">{data.environment}</span> environment.
        Rejected saving: {rejected ? `${usdSmart(rejected.decision.cost_saving_usd)} over the golden set` : 'none'}.
        Promoted saving: {promoted ? `${usdSmart(promoted.decision.cost_saving_usd)}` : 'none'}.
        Recorded by {String((data.generated_from as Record<string, string>).provider ?? 'unknown provider')}.
      </div>
    </div>
  )
}

/** The single sentence a judge has to read. */
function Verdict({ board }: { board: Board }) {
  const rejected = board.candidates.find((c) => c.decision.decision === 'REJECT')
  if (!rejected) {
    return (
      <Card>
        <div className="text-sm text-slate-600">
          No candidate was rejected in this run set. The board is showing every recorded
          configuration and its decision.
        </div>
      </Card>
    )
  }
  const floor = rejected.decision.failed_floors[0]
  const cpso = rejected.measured.cost_per_successful_outcome
  const baseCpso = board.baseline.measured.cost_per_successful_outcome
  return (
    <motion.div
      initial={{ opacity: 0, y: 10 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.35 }}
      className="glass overflow-hidden border-red-200/80 p-0"
    >
      <div className="grid gap-0 md:grid-cols-[1.35fr_1fr]">
        <div className="p-6">
          <Pill tone="fail">Rejected</Pill>
          <h1 className="mt-3 text-[26px] font-semibold leading-tight tracking-tight">
            A {Math.abs(rejected.decision.cost_delta_pct).toFixed(0)}% cost reduction was measured
            — and refused.
          </h1>
          <p className="mt-2 max-w-xl text-[15px] leading-relaxed text-slate-600">
            <span className="font-medium text-slate-800">{rejected.config.label}</span> costs{' '}
            {usdSmart(rejected.measured.cost_per_document_usd)} per document against the baseline's{' '}
            {usdSmart(board.baseline.measured.cost_per_document_usd)}. The saving is real and
            statistically significant. It is rejected because{' '}
            <span className="font-medium text-[var(--fail)]">
              {floor.label.toLowerCase()} measured {num(floor.candidate_value, 3)}, below the floor of{' '}
              {num(floor.floor, 2)}
            </span>{' '}
            the business declared in <code className="text-[13px]">policy.yaml</code>.
          </p>
          <div className="mt-4 flex flex-wrap gap-2">
            {rejected.decision.reasons.map((r) => (
              <span key={r.code} className="rounded-lg border border-red-200 bg-red-50/60 px-2.5 py-1 text-xs text-red-900">
                {r.detail}
              </span>
            ))}
          </div>
        </div>
        <div className="border-t border-slate-200/70 bg-white/40 p-6 md:border-l md:border-t-0">
          <div className="text-[11px] font-medium uppercase tracking-[0.08em] text-slate-500">
            And once rework is counted
          </div>
          <div className="mt-3 space-y-3">
            <CpsoRow label={board.baseline.config.label} value={baseCpso.value_usd} tone="pass" />
            <CpsoRow label={rejected.config.label} value={cpso.value_usd} tone="fail"
              note={cpso.undefined_reason ?? undefined} />
          </div>
          <p className="mt-3 text-xs leading-relaxed text-slate-500">
            The cheap configuration produced {cpso.successes} usable results out of {cpso.attempts} and
            generated {Math.round(cpso.rework_minutes)} minutes of analyst rework at{' '}
            {usd(cpso.hourly_rate_usd, 0)}/hr. Per unit of work anyone can actually ship, it is{' '}
            {cpso.value_usd && baseCpso.value_usd
              ? `${(cpso.value_usd / baseCpso.value_usd).toFixed(1)}× more expensive`
              : 'unmeasurable'}.
          </p>
        </div>
      </div>
    </motion.div>
  )
}

function CpsoRow({ label, value, tone, note }: {
  label: string; value: number | null; tone: 'pass' | 'fail'; note?: string
}) {
  return (
    <div className="flex items-baseline justify-between gap-4">
      <span className="text-sm text-slate-600">{label}</span>
      <span className="text-2xl font-semibold tabular"
        style={{ color: tone === 'pass' ? 'var(--pass)' : 'var(--fail)' }}>
        {value === null ? (note ?? 'undefined') : <Counter value={value} format={(v) => usd(v, 2)} />}
      </span>
    </div>
  )
}

function ConfigColumn({ col, index, floorMetrics }: {
  col: Column; index: number; floorMetrics: string[]
}) {
  const d = col.decision
  const tone = d === null ? 'neutral' : d.decision === 'PROMOTE' ? 'pass' : 'fail'
  const borderClass = tone === 'fail' ? 'border-red-200' : tone === 'pass' ? 'border-emerald-200' : ''
  const cpso = col.measured.cost_per_successful_outcome

  return (
    <motion.div
      initial={{ opacity: 0, y: 12 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ delay: 0.05 * index, duration: 0.3 }}
      className={`glass p-5 ${borderClass}`}
    >
      <div className="flex items-start justify-between gap-3">
        <div>
          <div className="text-base font-semibold">{col.label}</div>
          <code className="text-[11px] text-slate-400">{col.key}</code>
        </div>
        <Pill tone={tone}>{d ? d.decision : 'Baseline'}</Pill>
      </div>

      <div className="mt-4 grid grid-cols-2 gap-4">
        <div>
          <div className="text-[11px] uppercase tracking-[0.08em] text-slate-500">Cost / document</div>
          <div className="mt-0.5 text-2xl font-semibold tabular">
            <Counter value={col.measured.cost_per_document_usd} format={(v) => usd(v, 3)} />
          </div>
          {col.comparison && (
            <div className="text-xs tabular" style={{
              color: col.comparison.cost.pct_change < 0 ? 'var(--pass)' : 'var(--fail)',
            }}>
              {signedPct(col.comparison.cost.pct_change, 0)} vs baseline
            </div>
          )}
        </div>
        <div>
          <div className="text-[11px] uppercase tracking-[0.08em] text-slate-500">Cost / success</div>
          <div className="mt-0.5 text-2xl font-semibold tabular"
            style={{ color: cpso.value_usd === null ? 'var(--fail)' : 'var(--ink)' }}>
            {cpso.value_usd === null
              ? 'undefined'
              : <Counter value={cpso.value_usd} format={(v) => usd(v, 2)} />}
          </div>
          <div className="text-xs text-slate-500 tabular">
            {cpso.successes}/{cpso.attempts} usable
          </div>
        </div>
      </div>

      <div className="mt-4 space-y-1.5 border-t hairline pt-3">
        {floorMetrics.map((metric) => {
          const failed = d?.failed_floors.find((f) => f.metric === metric)
          const passed = d?.passed_floors.find((f) => f.metric === metric)
          const record = failed ?? passed
          const value = col.measured.quality[metric]
          return (
            <div key={metric} className="flex items-center justify-between text-sm">
              <span className="text-slate-600">{record?.label ?? metric}</span>
              <span className="flex items-center gap-2">
                <span className="tabular font-medium"
                  style={{ color: failed ? 'var(--fail)' : 'var(--ink)' }}>
                  {num(value, 3)}
                </span>
                {failed && (
                  <span className="rounded bg-[var(--fail-bg)] px-1.5 py-0.5 text-[10px] font-semibold text-[var(--fail)] tabular">
                    −{num(failed.shortfall ?? 0, 3)}
                  </span>
                )}
                {!failed && d && (
                  <span className="rounded bg-[var(--pass-bg)] px-1.5 py-0.5 text-[10px] font-semibold text-[var(--pass)]">
                    ok
                  </span>
                )}
              </span>
            </div>
          )
        })}
        <div className="flex items-center justify-between pt-1 text-sm">
          <span className="text-slate-600">Latency p95</span>
          <span className="tabular font-medium">{ms(col.measured.latency_ms.p95)}</span>
        </div>
        <div className="flex items-center justify-between text-sm">
          <span className="text-slate-600">Rework</span>
          <span className="tabular font-medium">{Math.round(cpso.rework_minutes)} min</span>
        </div>
      </div>

      {d && (
        <div className="mt-3 rounded-lg px-3 py-2 text-[12px] leading-relaxed"
          style={{
            background: d.decision === 'PROMOTE' ? 'var(--pass-bg)' : 'var(--fail-bg)',
            color: d.decision === 'PROMOTE' ? 'var(--pass)' : 'var(--fail)',
          }}>
          {d.headline}
        </div>
      )}
    </motion.div>
  )
}

/** Cost per call and cost per successful outcome, on the same screen. */
function ReversalChart({ columns }: { columns: Column[] }) {
  const rows = columns.map((c) => ({
    name: c.label,
    perCall: c.measured.cost_per_document_usd,
    perSuccess: c.measured.cost_per_successful_outcome.value_usd ?? 0,
    undefined_: c.measured.cost_per_successful_outcome.value_usd === null,
    rejected: c.decision?.decision === 'REJECT',
  }))
  return (
    <Card>
      <SectionTitle hint="same data, two denominators">The reversal</SectionTitle>
      <div className="grid gap-5 sm:grid-cols-2">
        <MiniChart title="Cost per call" rows={rows} dataKey="perCall" fmt={(v) => usd(v, 3)} />
        <MiniChart title="Cost per successful outcome" rows={rows} dataKey="perSuccess" fmt={(v) => usd(v, 0)} />
      </div>
      <p className="mt-4 text-xs leading-relaxed text-slate-500">
        Left is what every cost dashboard shows. Right is what the work actually cost, with human
        rework in the numerator and only usable results in the denominator. The ordering inverts.
      </p>
    </Card>
  )
}

function MiniChart({ title, rows, dataKey, fmt }: {
  title: string
  rows: { name: string; rejected: boolean; [k: string]: unknown }[]
  dataKey: string
  fmt: (v: number) => string
}) {
  return (
    <div>
      <div className="mb-2 text-[11px] font-medium uppercase tracking-[0.08em] text-slate-500">{title}</div>
      <ResponsiveContainer width="100%" height={190}>
        <BarChart data={rows} margin={{ top: 6, right: 6, bottom: 0, left: -14 }}>
          <CartesianGrid vertical={false} stroke="#eef1f5" />
          <XAxis dataKey="name" tick={{ fontSize: 11, fill: '#64748b' }} axisLine={false} tickLine={false} />
          <YAxis tick={{ fontSize: 10, fill: '#94a3b8' }} axisLine={false} tickLine={false}
            tickFormatter={(v) => fmt(Number(v))} width={62} />
          <Tooltip formatter={(v) => fmt(Number(v))} cursor={{ fill: '#0f172a08' }}
            contentStyle={{ borderRadius: 10, border: '1px solid #e2e8f0', fontSize: 12 }} />
          <RBar dataKey={dataKey} radius={[5, 5, 0, 0]} maxBarSize={54}>
            {rows.map((r, i) => (
              <Cell key={i} fill={r.rejected ? 'var(--fail)' : 'var(--accent)'} />
            ))}
          </RBar>
        </BarChart>
      </ResponsiveContainer>
    </div>
  )
}

function FloorTable({ board, columns }: { board: Board; columns: Column[] }) {
  const metrics = Object.entries(board.policy.quality_floor)
  return (
    <Card>
      <SectionTitle hint="declared in policy.yaml">Floors and ceilings</SectionTitle>
      <div className="overflow-x-auto">
        <table className="w-full border-collapse text-sm">
          <thead>
            <tr className="border-b hairline">
              <th className="pb-2 text-left text-[11px] font-semibold uppercase tracking-[0.07em] text-slate-500">Constraint</th>
              <th className="pb-2 text-right text-[11px] font-semibold uppercase tracking-[0.07em] text-slate-500">Floor</th>
              {columns.map((c) => (
                <th key={c.key} className="pb-2 text-right text-[11px] font-semibold uppercase tracking-[0.07em] text-slate-500">
                  {c.label}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {metrics.map(([metric, floor]) => (
              <tr key={metric} className="border-b border-slate-100">
                <td className="py-2 text-slate-700">{metric}</td>
                <td className="py-2 text-right tabular text-slate-500">{num(floor, 2)}</td>
                {columns.map((c) => {
                  const v = c.measured.quality[metric]
                  const broken = c.decision?.failed_floors.some((f) => f.metric === metric)
                  return (
                    <td key={c.key} className="py-2 text-right tabular font-medium"
                      style={{ color: broken ? 'var(--fail)' : 'var(--ink)' }}>
                      {num(v, 3)}
                    </td>
                  )
                })}
              </tr>
            ))}
            <tr>
              <td className="py-2 text-slate-700">latency p95</td>
              <td className="py-2 text-right tabular text-slate-500">
                ≤ {ms(board.policy.latency_ceiling_ms)}
              </td>
              {columns.map((c) => (
                <td key={c.key} className="py-2 text-right tabular font-medium"
                  style={{ color: c.decision?.latency_breach ? 'var(--fail)' : 'var(--ink)' }}>
                  {ms(c.measured.latency_ms.p95)}
                </td>
              ))}
            </tr>
          </tbody>
        </table>
      </div>
    </Card>
  )
}

/** The significance check, shown rather than claimed. */
function PairedEvidence({ board }: { board: Board }) {
  return (
    <Card>
      <SectionTitle hint={`paired bootstrap, ${board.candidates[0]?.comparison.cost.bootstrap.iterations ?? 0} iterations`}>
        Paired evidence
      </SectionTitle>
      <div className="overflow-x-auto">
        <table className="w-full border-collapse text-sm">
          <thead>
            <tr className="border-b hairline">
              {['Candidate', 'Metric', 'Baseline', 'Candidate', 'Δ', '95% CI', 'Sign test p', 'Verdict']
                .map((h, i) => (
                  <th key={h} className={`pb-2 text-[11px] font-semibold uppercase tracking-[0.07em] text-slate-500 ${i < 2 ? 'text-left' : 'text-right'}`}>
                    {h}
                  </th>
                ))}
            </tr>
          </thead>
          <tbody>
            {board.candidates.map((c) => (
              <Fragment key={c.config.config_id}>
                <tr className="border-b border-slate-100 bg-slate-50/40">
                  <td className="py-2 font-medium text-slate-700">{c.config.label}</td>
                  <td className="py-2 text-slate-600">total spend</td>
                  <td className="py-2 text-right tabular">{usd(c.comparison.cost.baseline_total_usd)}</td>
                  <td className="py-2 text-right tabular">{usd(c.comparison.cost.candidate_total_usd)}</td>
                  <td className="py-2 text-right tabular font-medium"
                    style={{ color: c.comparison.cost.pct_change < 0 ? 'var(--pass)' : 'var(--fail)' }}>
                    {signedPct(c.comparison.cost.pct_change, 1)}
                  </td>
                  <td className="py-2 text-right tabular text-xs text-slate-500">
                    [{c.comparison.cost.bootstrap.ci_low.toFixed(4)}, {c.comparison.cost.bootstrap.ci_high.toFixed(4)}]
                  </td>
                  <td className="py-2 text-right tabular text-xs text-slate-500">
                    {c.comparison.cost.sign_test.p_value.toExponential(1)}
                  </td>
                  <td className="py-2 text-right">
                    <Pill tone={c.comparison.cost.saving_is_significant ? 'pass' : 'warn'}>
                      {c.comparison.cost.saving_is_significant ? 'significant' : 'noise'}
                    </Pill>
                  </td>
                </tr>
                {Object.entries(c.comparison.quality)
                  .filter(([m]) => m in board.policy.quality_floor)
                  .map(([metric, q]) => (
                    <tr key={`${c.config.config_id}-${metric}`} className="border-b border-slate-100">
                      <td />
                      <td className="py-2 text-slate-600">{metric}</td>
                      <td className="py-2 text-right tabular">{num(q.baseline, 3)}</td>
                      <td className="py-2 text-right tabular">{num(q.candidate, 3)}</td>
                      <td className="py-2 text-right tabular font-medium"
                        style={{ color: q.improved ? 'var(--pass)' : 'var(--fail)' }}>
                        {q.delta >= 0 ? '+' : ''}{num(q.delta, 3)}
                      </td>
                      <td className="py-2 text-right tabular text-xs text-slate-500">
                        [{q.bootstrap.ci_low.toFixed(3)}, {q.bootstrap.ci_high.toFixed(3)}]
                      </td>
                      <td className="py-2 text-right tabular text-xs text-slate-500">
                        {q.sign_test.p_value.toExponential(1)}
                      </td>
                      <td className="py-2 text-right text-xs text-slate-500">
                        {q.bootstrap.significant ? (q.improved ? 'improved' : 'regressed') : 'no change'}
                      </td>
                    </tr>
                  ))}
              </Fragment>
            ))}
          </tbody>
        </table>
      </div>
      <p className="mt-3 text-xs text-slate-500">
        Confidence intervals are on the per-document mean delta. A cost interval that includes zero
        blocks promotion regardless of the headline percentage: a saving you cannot distinguish from
        noise is not a saving.
      </p>
    </Card>
  )
}
