/**
 * MODULE 2 — attribution and cost explorer.
 *
 * The rollups are table stakes. The three things here that other tools do not
 * show: the cost buckets nobody attributes, whether each agent stage earns its
 * cost, and the shape of the tail.
 */
import { useState } from 'react'
import {
  Bar, BarChart, CartesianGrid, Cell, Legend, Pie, PieChart, ResponsiveContainer,
  Tooltip, XAxis, YAxis,
} from 'recharts'
import { api, type Attribution, type HeavyTail, type RollupRow, type StageEconomics } from '../api'
import { useResource } from '../useResource'
import { useApp } from '../store'
import { Bar as MiniBar, Card, ErrorBox, Kpi, Loading, Pill, SectionTitle, Table } from '../components/ui'
import { compactTokens, num, pct, usd, usdSmart } from '../format'

const DIMENSIONS = [
  { key: 'by_team', label: 'Team' },
  { key: 'by_stage', label: 'Stage' },
  { key: 'by_model', label: 'Model' },
  { key: 'by_prompt_version', label: 'Prompt version' },
  { key: 'by_use_case', label: 'Use case' },
] as const

const PALETTE = ['#5546e8', '#2f8bf0', '#8b5cf6', '#f59e0b', '#10b981', '#f43f5e']

export function Explorer() {
  const useCase = useApp((s) => s.useCase)
  const roll = useResource<Attribution>(() => api.attribution(useCase), [useCase])
  const stages = useResource<StageEconomics>(() => api.stageEconomics(useCase), [useCase])
  const tail = useResource<HeavyTail>(() => api.heavyTail(useCase), [useCase])

  if (roll.loading) return <Loading what="production traces" />
  if (roll.error) return <ErrorBox error={roll.error} />
  if (!roll.data) return null
  const a = roll.data

  return (
    <div className="space-y-5">
      <Card>
        <div className="grid gap-6 sm:grid-cols-2 lg:grid-cols-4">
          <Kpi label="Model spend" sub={`${a.window.days} days of production + CI`}>
            {usd(a.model_spend_usd, 0)}
          </Kpi>
          <Kpi label="Human rework" tone="fail"
            sub={`${a.rework_hours.toLocaleString()} analyst hours`}>
            {usd(a.rework_usd, 0)}
          </Kpi>
          <Kpi label="True cost of the work" sub="model spend + rework">
            {usd(a.grand_total_usd, 0)}
          </Kpi>
          <Kpi label="Rework / model spend" tone="warn"
            sub="the line no LLM cost tool carries">
            {a.rework_multiple_of_model_spend?.toFixed(1)}×
          </Kpi>
        </div>
      </Card>

      <div className="grid gap-4 lg:grid-cols-[1.15fr_1fr]">
        <Buckets attribution={a} />
        <CacheCard attribution={a} />
      </div>

      <Rollups attribution={a} />

      {stages.error ? <ErrorBox error={stages.error} />
        : stages.data && <StageEconomicsCard data={stages.data} />}

      {tail.error ? <ErrorBox error={tail.error} />
        : tail.data && <HeavyTailCard data={tail.data} />}
    </div>
  )
}

function Buckets({ attribution }: { attribution: Attribution }) {
  return (
    <Card>
      <SectionTitle hint="share of the true cost of the work">
        Where the money actually goes
      </SectionTitle>
      <div className="space-y-3">
        {attribution.buckets.map((b, i) => (
          <div key={b.key}>
            <div className="flex items-baseline justify-between gap-3">
              <span className="text-sm font-medium text-slate-700">{b.label}</span>
              <span className="tabular text-sm">
                {usdSmart(b.spend_usd)}
                <span className="ml-2 text-xs text-slate-400">{pct(b.share_pct)}</span>
              </span>
            </div>
            <div className="mt-1">
              <MiniBar value={b.share_pct} tone={b.key === 'rework' ? 'fail' : 'accent'} />
            </div>
            <div className="mt-1 text-[11px] leading-snug text-slate-500">{b.note}</div>
            {i < attribution.buckets.length - 1 && <div className="mt-3 border-t border-slate-100" />}
          </div>
        ))}
      </div>
    </Card>
  )
}

function CacheCard({ attribution }: { attribution: Attribution }) {
  const c = attribution.cached_vs_fresh
  const data = [
    { name: 'Fresh input', value: c.fresh_usd },
    { name: 'Cached input', value: c.cached_usd },
  ]
  return (
    <Card>
      <SectionTitle hint="prompt cache reads vs fresh reads">Cached vs fresh input</SectionTitle>
      <div className="grid gap-4 sm:grid-cols-[1fr_1.1fr] sm:items-center">
        <ResponsiveContainer width="100%" height={170}>
          <PieChart>
            <Pie data={data} dataKey="value" nameKey="name" innerRadius={44} outerRadius={68}
              paddingAngle={2} stroke="none">
              {data.map((_, i) => <Cell key={i} fill={PALETTE[i]} />)}
            </Pie>
            <Tooltip formatter={(v) => usd(Number(v))}
              contentStyle={{ borderRadius: 12, border: '1px solid #e6e8f4', fontSize: 12, boxShadow: '0 14px 34px -22px rgb(27 31 54 / 0.4)' }} />
            <Legend verticalAlign="bottom" height={24} iconSize={8}
              formatter={(v) => <span className="text-[11px] text-slate-500">{v}</span>} />
          </PieChart>
        </ResponsiveContainer>
        <div className="space-y-2 text-sm">
          <Row label="Fresh tokens" value={compactTokens(c.fresh_tokens)} />
          <Row label="Cached tokens" value={compactTokens(c.cached_tokens)} />
          <Row label="Cache hit rate" value={pct(c.cache_hit_rate * 100, 1)} />
          <Row label="Cached reads cost" value={usdSmart(c.cached_usd)} />
          <Row label="…at the fresh rate" value={usdSmart(c.counterfactual_usd_without_cache)} />
          <div className="flex items-baseline justify-between border-t border-slate-100 pt-2">
            <span className="text-slate-600">Saved by caching</span>
            <span className="tabular font-semibold text-[var(--pass)]">{usdSmart(c.saved_usd)}</span>
          </div>
        </div>
      </div>
      <p className="mt-3 text-[11px] leading-relaxed text-slate-500">
        Counterfactual priced from the same table the CostMeter uses, per model — cached tokens
        re-costed at that model's fresh input rate.
      </p>
    </Card>
  )
}

function Row({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex items-baseline justify-between">
      <span className="text-slate-600">{label}</span>
      <span className="tabular">{value}</span>
    </div>
  )
}

function Rollups({ attribution }: { attribution: Attribution }) {
  const [dim, setDim] = useState<(typeof DIMENSIONS)[number]['key']>('by_stage')
  const rows = attribution[dim] as RollupRow[]
  return (
    <Card>
      <div className="mb-3 flex flex-wrap items-center justify-between gap-3">
        <SectionTitle hint={`${attribution.window.days} day window`}>Attribution</SectionTitle>
        <div className="flex flex-wrap gap-1">
          {DIMENSIONS.map((d) => (
            <button key={d.key} onClick={() => setDim(d.key)}
              className={`rounded-lg px-2.5 py-1 text-xs transition-colors ${
                dim === d.key ? 'bg-[var(--accent)] text-white shadow-[var(--shadow-accent)]' : 'bg-slate-100 text-slate-600 hover:bg-slate-200'
              }`}>
              {d.label}
            </button>
          ))}
        </div>
      </div>
      <div className="grid gap-5 lg:grid-cols-[1.1fr_1fr]">
        <ResponsiveContainer width="100%" height={Math.max(180, rows.length * 34)}>
          <BarChart data={rows} layout="vertical" margin={{ left: 8, right: 16, top: 4, bottom: 4 }}>
            <CartesianGrid horizontal={false} stroke="#f1f2fa" />
            <XAxis type="number" tick={{ fontSize: 10, fill: '#9ba2be' }} axisLine={false}
              tickLine={false} tickFormatter={(v) => usd(Number(v), 0)} />
            <YAxis type="category" dataKey="key" width={130} tick={{ fontSize: 11, fill: '#5a6079' }}
              axisLine={false} tickLine={false} />
            <Tooltip formatter={(v) => usd(Number(v))} cursor={{ fill: '#5546e80f' }}
              contentStyle={{ borderRadius: 12, border: '1px solid #e6e8f4', fontSize: 12, boxShadow: '0 14px 34px -22px rgb(27 31 54 / 0.4)' }} />
            <Bar dataKey="spend_usd" radius={[0, 5, 5, 0]} maxBarSize={22}>
              {rows.map((_, i) => <Cell key={i} fill={PALETTE[i % PALETTE.length]} />)}
            </Bar>
          </BarChart>
        </ResponsiveContainer>
        <Table head={[DIMENSIONS.find((d) => d.key === dim)!.label, 'Spend', 'Share', 'Spans', '$/doc']}>
          {rows.map((r) => (
            <tr key={r.key} className="border-b border-slate-100">
              <td className="py-2 text-slate-700">{r.key}</td>
              <td className="py-2 text-right tabular">{usdSmart(r.spend_usd)}</td>
              <td className="py-2 text-right tabular text-slate-500">{pct(r.share_pct)}</td>
              <td className="py-2 text-right tabular text-slate-500">{r.spans.toLocaleString()}</td>
              <td className="py-2 text-right tabular text-slate-500">
                {r.cost_per_document_usd ? usd(r.cost_per_document_usd, 3) : '—'}
              </td>
            </tr>
          ))}
        </Table>
      </div>
    </Card>
  )
}

function StageEconomicsCard({ data }: { data: StageEconomics }) {
  return (
    <Card>
      <SectionTitle hint="from recorded ablation runs">
        Stage economics — is this agent worth what it costs?
      </SectionTitle>
      <div className="space-y-3">
        {data.stages.map((s) => (
          <div key={s.stage} className="rounded-xl border border-slate-200/80 bg-white/50 p-4">
            <div className="flex flex-wrap items-center justify-between gap-3">
              <div className="flex items-center gap-3">
                <span className="font-medium">{s.stage}</span>
                <Pill tone={s.verdict === 'worth_it' ? 'pass'
                  : s.verdict === 'not_worth_it' ? 'fail' : 'neutral'}>
                  {s.verdict.replace(/_/g, ' ')}
                </Pill>
              </div>
              <div className="flex items-center gap-6 text-sm">
                <span className="tabular">{usdSmart(s.spend_usd)}<span className="ml-1 text-xs text-slate-400">{pct(s.share_pct)}</span></span>
                {s.cost_per_document_usd !== null && (
                  <span className="tabular text-slate-500">{usd(s.cost_per_document_usd, 3)}/doc</span>
                )}
              </div>
            </div>
            <div className="mt-2"><MiniBar value={s.share_pct}
              tone={s.verdict === 'not_worth_it' ? 'fail' : 'pass'} /></div>
            <p className="mt-2 text-[12px] leading-relaxed text-slate-600">{s.note}</p>
            {s.quality_delta && (
              <div className="mt-2 flex flex-wrap gap-x-5 gap-y-1 text-[11px] text-slate-500">
                {Object.entries(s.quality_delta).map(([m, d]) => (
                  <span key={m} className="tabular">
                    {m} <span style={{ color: d > 0 ? 'var(--pass)' : d < 0 ? 'var(--fail)' : undefined }}>
                      {d >= 0 ? '+' : ''}{num(d, 4)}
                    </span>
                  </span>
                ))}
              </div>
            )}
          </div>
        ))}
      </div>
      <p className="mt-3 text-[11px] leading-relaxed text-slate-500">
        Quality deltas are baseline minus ablated, so positive means the stage improves the metric.
        The verdict is settled on cost per successful outcome, not on model spend: a stage that
        shaves the invoice and adds analyst hours is not a saving.
      </p>
    </Card>
  )
}

function HeavyTailCard({ data }: { data: HeavyTail }) {
  // `overflow` is deliberately not a field on the chart data: Recharts forwards
  // data keys onto the rendered element, and `overflow` is a real SVG attribute.
  const overflowIndex = data.histogram.findIndex((h) => h.overflow)
  const bars = data.histogram.map((h) => ({
    label: h.overflow ? `> ${usd(h.bucket_usd_lo, 2)}` : usd(h.bucket_usd_lo, 2),
    documents: h.documents,
  }))
  return (
    <Card>
      <SectionTitle hint={`${data.n_documents.toLocaleString()} production documents`}>
        Heavy tail — the average is the wrong number
      </SectionTitle>
      <div className="grid gap-6 lg:grid-cols-[1.2fr_1fr]">
        <div>
          <ResponsiveContainer width="100%" height={220}>
            <BarChart data={bars} margin={{ top: 4, right: 8, bottom: 0, left: -18 }}>
              <CartesianGrid vertical={false} stroke="#f1f2fa" />
              <XAxis dataKey="label" tick={{ fontSize: 9, fill: '#9ba2be' }} axisLine={false}
                tickLine={false} interval={2} />
              <YAxis tick={{ fontSize: 10, fill: '#9ba2be' }} axisLine={false} tickLine={false} />
              <Tooltip cursor={{ fill: '#5546e80f' }}
                contentStyle={{ borderRadius: 12, border: '1px solid #e6e8f4', fontSize: 12, boxShadow: '0 14px 34px -22px rgb(27 31 54 / 0.4)' }} />
              <Bar dataKey="documents" radius={[4, 4, 0, 0]}>
                {bars.map((_, i) => (
                  <Cell key={i} fill={i === overflowIndex ? 'var(--fail)' : 'var(--accent)'} />
                ))}
              </Bar>
            </BarChart>
          </ResponsiveContainer>
          <div className="mt-1 text-[11px] text-slate-500">
            Bins run to p99; everything above is the red overflow bucket, kept separate so the tail
            is visible instead of flattened into the axis.
          </div>
        </div>
        <div>
          <div className="grid grid-cols-3 gap-3">
            {(['p50', 'p95', 'p99'] as const).map((p) => (
              <div key={p}>
                <div className="text-[11px] uppercase tracking-[0.08em] text-slate-500">{p}</div>
                <div className="text-xl font-semibold tabular">{usd(data.percentiles_usd[p], 3)}</div>
              </div>
            ))}
          </div>
          <div className="mt-4 space-y-2 text-sm">
            <Row label="Mean (what dashboards show)" value={usd(data.percentiles_usd.mean, 3)} />
            <Row label="Max" value={usd(data.percentiles_usd.max, 2)} />
            <Row label="p99 / p50" value={`${data.ratio_p99_p50}×`} />
            <div className="flex items-baseline justify-between border-t border-slate-100 pt-2">
              <span className="text-slate-600">Top 5% of documents</span>
              <span className="tabular font-semibold text-[var(--fail)]">
                {pct(data.top_5pct_share_of_spend)} of spend
              </span>
            </div>
            <Row label="Top 1% of documents" value={`${pct(data.top_1pct_share_of_spend)} of spend`} />
          </div>
          <div className="mt-4">
            <div className="mb-1.5 text-[11px] uppercase tracking-[0.08em] text-slate-500">
              Most expensive documents
            </div>
            <Table head={['Document', 'Tier', 'Cost']}>
              {data.worst.slice(0, 5).map((w) => (
                <tr key={w.doc_id} className="border-b border-slate-100">
                  <td className="py-1.5 font-mono text-[11px] text-slate-700">{w.doc_id}</td>
                  <td className="py-1.5 text-right text-xs text-slate-500">{w.doc_tier ?? '—'}</td>
                  <td className="py-1.5 text-right tabular">{usdSmart(w.cost_usd)}</td>
                </tr>
              ))}
            </Table>
          </div>
        </div>
      </div>
      <div className="mt-4 grid gap-3 sm:grid-cols-3">
        {data.by_tier.map((t) => (
          <div key={t.tier} className="rounded-xl border border-slate-200/80 bg-white/50 p-3">
            <div className="text-sm font-medium">{t.tier.replace('_', ' ')}</div>
            <div className="mt-1 flex items-baseline justify-between text-xs text-slate-500">
              <span>{t.documents} docs</span><span className="tabular">{pct(t.share_pct)} of spend</span>
            </div>
            <div className="mt-1.5 flex items-baseline justify-between text-sm">
              <span className="tabular">mean {usd(t.mean_usd, 3)}</span>
              <span className="tabular text-slate-500">p95 {usd(t.p95_usd, 3)}</span>
            </div>
          </div>
        ))}
      </div>
    </Card>
  )
}
