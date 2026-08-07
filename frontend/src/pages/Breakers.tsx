/**
 * MODULE 5 — circuit breaker demo.
 *
 * Replays a recorded runaway trace span by span through the breakers declared in
 * policy.yaml, and shows the counterfactual: what was spent, and what was not.
 */
import { useEffect, useRef, useState } from 'react'
import { motion } from 'framer-motion'
import {
  Area, CartesianGrid, ComposedChart, Line, ReferenceLine, ResponsiveContainer,
  Tooltip, XAxis, YAxis,
} from 'recharts'
import { api, type BreakerReplay } from '../api'
import { useResource } from '../useResource'
import { useApp } from '../store'
import { Card, Counter, ErrorBox, Loading, Pill, SectionTitle } from '../components/ui'
import { compactTokens, usd } from '../format'

const FRAME_MS = 110

export function Breakers() {
  const useCase = useApp((s) => s.useCase)
  const { data, error, loading } = useResource<BreakerReplay>(
    () => api.breakerReplay(useCase), [useCase])

  const [cursor, setCursor] = useState(0)
  const [playing, setPlaying] = useState(true)
  const timer = useRef<number | null>(null)

  const total = data?.frames.length ?? 0
  const stopAt = data?.trip ? data.trip.index : total - 1

  useEffect(() => {
    if (!data || !playing) return
    if (cursor >= stopAt) { setPlaying(false); return }
    timer.current = window.setTimeout(() => setCursor((c) => c + 1), FRAME_MS)
    return () => { if (timer.current) window.clearTimeout(timer.current) }
  }, [cursor, playing, data, stopAt])

  if (loading) return <Loading what="the runaway trace" />
  if (error) return <ErrorBox error={error} />
  if (!data) return null

  const tripped = data.trip !== null && cursor >= data.trip.index
  const frames = data.frames
  const current = frames[Math.min(cursor, frames.length - 1)]
  const spentNow = current.cumulative_usd

  const chartRows = frames.map((f, i) => ({
    index: f.index,
    executed: i <= cursor ? f.cumulative_usd : null,
    unchecked: f.cumulative_usd,
    velocity: f.velocity_multiplier,
  }))

  const replay = () => { setCursor(0); setPlaying(true) }

  return (
    <div className="space-y-5">
      <motion.div
        animate={tripped ? { borderColor: '#fca5a5' } : {}}
        className={`glass p-6 ${tripped ? 'border-red-300' : ''}`}
      >
        <div className="flex flex-wrap items-start justify-between gap-5">
          <div>
            <div className="flex items-center gap-3">
              <Pill tone={tripped ? 'fail' : 'warn'}>
                {tripped ? 'Breaker tripped' : 'Replaying'}
              </Pill>
              <code className="text-[11px] text-slate-400">{data.trace_id}</code>
            </div>
            <h1 className="mt-3 max-w-2xl text-[24px] font-semibold leading-tight tracking-tight">
              {tripped && data.trip
                ? `Stopped after ${data.trip.index + 1} calls and ${data.trip.elapsed_s}s — ${usd(data.trip.spent_usd)} spent, ${usd(data.counterfactual.prevented_usd)} prevented.`
                : 'A recursive tool loop with a growing context window.'}
            </h1>
            {tripped && data.trip && (
              <p className="mt-2 max-w-2xl text-[15px] leading-relaxed text-slate-600">
                <span className="font-medium">{data.trip.label}:</span> {data.trip.detail}
              </p>
            )}
          </div>
          <div className="flex gap-2">
            <button onClick={() => setPlaying((p) => !p)}
              className="rounded-lg border border-slate-200 px-3 py-1.5 text-xs text-slate-600 hover:bg-slate-50">
              {playing ? 'Pause' : 'Play'}
            </button>
            <button onClick={replay}
              className="rounded-lg bg-slate-900 px-3 py-1.5 text-xs text-white hover:bg-slate-800">
              Replay
            </button>
          </div>
        </div>

        <div className="mt-5 grid gap-6 sm:grid-cols-4">
          <Metric label="Spent" value={spentNow} tone="fail" fmt={(v) => usd(v, 2)} />
          <Metric label="Prevented"
            value={tripped ? data.counterfactual.prevented_usd : 0} tone="pass"
            fmt={(v) => usd(v, 2)} />
          <Metric label="If unchecked" value={data.counterfactual.total_if_unchecked_usd}
            fmt={(v) => usd(v, 2)} />
          <Metric label="Burn rate" value={data.counterfactual.burn_rate_usd_per_min}
            tone="warn" fmt={(v) => `${usd(v, 0)}/min`} />
        </div>
      </motion.div>

      <div className="glass border-amber-200 bg-amber-50/50 p-4">
        <div className="text-sm font-medium text-amber-900">
          Why a monthly cap would not have caught this
        </div>
        <p className="mt-1 text-[13px] leading-relaxed text-amber-900/80">
          {data.counterfactual.monthly_cap_comment} This trace ran for{' '}
          {data.counterfactual.trace_duration_s}s. A monthly budget check would have run once, the
          next morning, against money that was already gone.
        </p>
      </div>

      <div className="grid gap-4 lg:grid-cols-[1.35fr_1fr]">
        <Card>
          <SectionTitle hint={`span ${current.index + 1} of ${total}`}>
            Cumulative spend, span by span
          </SectionTitle>
          <ResponsiveContainer width="100%" height={260}>
            <ComposedChart data={chartRows} margin={{ top: 6, right: 10, bottom: 0, left: -12 }}>
              <defs>
                <linearGradient id="burn" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="0%" stopColor="#b91c1c" stopOpacity={0.22} />
                  <stop offset="100%" stopColor="#b91c1c" stopOpacity={0.02} />
                </linearGradient>
              </defs>
              <CartesianGrid vertical={false} stroke="#eef1f5" />
              <XAxis dataKey="index" tick={{ fontSize: 10, fill: '#94a3b8' }} axisLine={false}
                tickLine={false} />
              <YAxis tick={{ fontSize: 10, fill: '#94a3b8' }} axisLine={false} tickLine={false}
                tickFormatter={(v) => usd(Number(v), 0)} width={58} />
              <Tooltip formatter={(v) => usd(Number(v), 2)}
                labelFormatter={(l) => `span ${l}`}
                contentStyle={{ borderRadius: 10, border: '1px solid #e2e8f0', fontSize: 12 }} />
              <Area type="monotone" dataKey="unchecked" stroke="#b91c1c" strokeWidth={1}
                strokeDasharray="4 3" fill="url(#burn)" name="if unchecked" />
              <Line type="monotone" dataKey="executed" stroke="#0f172a" strokeWidth={2.4}
                dot={false} name="executed" />
              {data.trip && (
                <ReferenceLine x={data.trip.index} stroke="#b91c1c" strokeWidth={1.5}
                  label={{ value: 'breaker', position: 'top', fontSize: 10, fill: '#b91c1c' }} />
              )}
            </ComposedChart>
          </ResponsiveContainer>
          <div className="mt-2 grid grid-cols-2 gap-4 text-xs text-slate-500 sm:grid-cols-4">
            <span>depth <span className="tabular font-medium text-slate-700">{current.agent_depth}</span></span>
            <span>context <span className="tabular font-medium text-slate-700">{compactTokens(current.input_tokens)}</span></span>
            <span>velocity <span className="tabular font-medium text-slate-700">{current.velocity_multiplier}×</span></span>
            <span>identical <span className="tabular font-medium text-slate-700">{current.identical_calls}</span></span>
          </div>
        </Card>

        <Card>
          <SectionTitle hint="all four evaluated on every span">Breakers</SectionTitle>
          <div className="space-y-2.5">
            {data.breaker_summary.map((b) => (
              <div key={b.breaker}
                className={`rounded-xl border p-3 ${
                  b.fired ? 'border-red-300 bg-red-50/70'
                    : b.breached ? 'border-amber-200 bg-amber-50/40'
                      : 'border-slate-200 bg-white/40'
                }`}>
                <div className="flex items-center justify-between gap-3">
                  <span className="text-sm font-medium">{b.label}</span>
                  {b.fired ? <Pill tone="fail">fired</Pill>
                    : b.breached ? <Pill tone="warn">would have caught</Pill>
                      : <Pill tone="neutral">not breached</Pill>}
                </div>
                <div className="mt-1 text-[11px] text-slate-500 tabular">
                  limit {String(b.limit)}
                  {b.breached && b.index !== undefined && (
                    <> · span {b.index + 1} · {usd(b.spent_usd ?? 0, 2)} spent ·{' '}
                      {usd(b.prevented_usd ?? 0, 2)} prevented</>
                  )}
                </div>
                {b.detail && (
                  <div className="mt-1 text-[11px] leading-snug text-slate-600">{b.detail}</div>
                )}
              </div>
            ))}
          </div>
          <p className="mt-3 text-[11px] leading-relaxed text-slate-500">
            The loop detector caught this by structure, not by cost — six calls in, before the
            spend limit had anything to notice. Catching it on the per-trace limit instead would
            have cost {usd((data.breaker_summary.find((b) => b.breaker === 'max_usd_per_trace')?.spent_usd) ?? 0, 2)}.
          </p>
        </Card>
      </div>

      <Card>
        <SectionTitle hint="executed spans are solid; the rest never ran">Replay detail</SectionTitle>
        <div className="max-h-72 overflow-y-auto">
          <table className="w-full border-collapse text-sm">
            <thead className="sticky top-0 bg-white/90 backdrop-blur">
              <tr className="border-b hairline">
                {['#', 'Stage', 'Depth', 'Context', 'Cost', 'Cumulative', 't', 'Velocity', 'Same call']
                  .map((h, i) => (
                    <th key={h} className={`pb-2 text-[11px] font-semibold uppercase tracking-[0.07em] text-slate-500 ${i < 2 ? 'text-left' : 'text-right'}`}>
                      {h}
                    </th>
                  ))}
              </tr>
            </thead>
            <tbody>
              {frames.map((f) => {
                const executed = f.index <= cursor
                const isTrip = data.trip?.index === f.index
                return (
                  <tr key={f.span_id}
                    className={`border-b border-slate-100 ${executed ? '' : 'opacity-35'} ${
                      isTrip ? 'bg-red-50/70' : ''}`}>
                    <td className="py-1.5 tabular text-slate-400">{f.index + 1}</td>
                    <td className="py-1.5 text-slate-700">{f.stage}</td>
                    <td className="py-1.5 text-right tabular">{f.agent_depth}</td>
                    <td className="py-1.5 text-right tabular text-slate-500">{compactTokens(f.input_tokens)}</td>
                    <td className="py-1.5 text-right tabular">{usd(f.cost_usd, 3)}</td>
                    <td className="py-1.5 text-right tabular font-medium">{usd(f.cumulative_usd, 2)}</td>
                    <td className="py-1.5 text-right tabular text-slate-500">{f.elapsed_s}s</td>
                    <td className="py-1.5 text-right tabular"
                      style={{ color: f.velocity_multiplier > 3 ? 'var(--fail)' : undefined }}>
                      {f.velocity_multiplier}×
                    </td>
                    <td className="py-1.5 text-right tabular"
                      style={{ color: f.identical_calls > 3 ? 'var(--fail)' : undefined }}>
                      {f.identical_calls}
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
      </Card>
    </div>
  )
}

function Metric({ label, value, tone = 'default', fmt }: {
  label: string
  value: number
  tone?: 'default' | 'fail' | 'pass' | 'warn'
  fmt: (v: number) => string
}) {
  const color = { default: 'var(--ink)', fail: 'var(--fail)', pass: 'var(--pass)', warn: 'var(--warn)' }[tone]
  return (
    <div>
      <div className="text-[11px] font-medium uppercase tracking-[0.08em] text-slate-500">{label}</div>
      <div className="mt-0.5 text-3xl font-semibold" style={{ color }}>
        <Counter value={value} format={fmt} />
      </div>
    </div>
  )
}
