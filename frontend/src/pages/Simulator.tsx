/**
 * MODULE 4 — the optimisation simulator.
 *
 * Everything on this screen is projected, and it says so everywhere. Where the
 * chosen levers match a configuration that was actually recorded, the measured
 * result appears beside the projection with the projection's own error.
 */
import { useEffect, useMemo, useState } from 'react'
import { motion } from 'framer-motion'
import { api, type LeverCatalogue, type Simulation } from '../api'
import { useResource } from '../useResource'
import { useApp } from '../store'
import { Card, ErrorBox, Loading, Pill, SectionTitle } from '../components/ui'
import { ms, num, signedPct, usd } from '../format'

type LeverValue = string | number | boolean

export function Simulator() {
  const useCase = useApp((s) => s.useCase)
  const cat = useResource<LeverCatalogue>(() => api.levers(useCase), [useCase])
  const [chosen, setChosen] = useState<Record<string, LeverValue>>({})
  const [sim, setSim] = useState<Simulation | null>(null)
  const [simError, setSimError] = useState<unknown>(null)

  useEffect(() => {
    if (cat.data && Object.keys(chosen).length === 0) setChosen(cat.data.baseline_levers)
  }, [cat.data, chosen])

  useEffect(() => {
    if (!Object.keys(chosen).length) return
    let live = true
    api.simulate({ use_case: useCase, levers: chosen })
      .then((s) => live && (setSim(s), setSimError(null)))
      .catch((e) => live && setSimError(e))
    return () => { live = false }
  }, [chosen, useCase])

  const dirty = useMemo(() => {
    if (!cat.data) return false
    return Object.entries(chosen).some(
      ([k, v]) => String(v) !== String(cat.data!.baseline_levers[k]))
  }, [chosen, cat.data])

  if (cat.loading) return <Loading what="the calibrated lever table" />
  if (cat.error) return <ErrorBox error={cat.error} />
  if (!cat.data) return null

  return (
    <div className="space-y-5">
      <div className="glass border-violet-200 bg-violet-50/40 p-4">
        <div className="flex flex-wrap items-center gap-3">
          <Pill tone="projected">Projected</Pill>
          <span className="text-sm text-violet-950/80">
            Single-lever effects were measured on {cat.data.calibration.golden_set_size} golden
            documents. Composing them assumes an independence they do not have — so nothing here is
            a measurement, and nothing here can promote a configuration.
          </span>
        </div>
      </div>

      <div className="grid gap-4 lg:grid-cols-[340px_1fr]">
        <Card>
          <SectionTitle hint={dirty ? 'modified' : 'at baseline'}>Levers</SectionTitle>
          <div className="space-y-4">
            {cat.data.levers.map((lever) => (
              <div key={lever.id}>
                <div className="flex items-baseline justify-between gap-2">
                  <label className="text-sm font-medium text-slate-700">{lever.label}</label>
                  {String(chosen[lever.id]) !== String(lever.default) && (
                    <span className="text-[10px] font-semibold uppercase text-[var(--projected)]">changed</span>
                  )}
                </div>
                <div className="mt-1.5 flex flex-wrap gap-1">
                  {(lever.kind === 'toggle' ? [true, false] : lever.options ?? []).map((opt) => {
                    const active = String(chosen[lever.id]) === String(opt)
                    return (
                      <button key={String(opt)}
                        onClick={() => setChosen((c) => ({ ...c, [lever.id]: opt as LeverValue }))}
                        className={`rounded-lg px-2.5 py-1 text-xs transition-colors ${
                          active ? 'bg-[var(--accent)] text-white shadow-[var(--shadow-accent)]'
                            : 'bg-slate-100 text-slate-600 hover:bg-slate-200'
                        }`}>
                        {lever.kind === 'toggle' ? (opt ? 'on' : 'off') : String(opt)}
                      </button>
                    )
                  })}
                </div>
                <p className="mt-1.5 text-[11px] leading-snug text-slate-500">{lever.description}</p>
              </div>
            ))}
          </div>
          <button onClick={() => setChosen(cat.data!.baseline_levers)}
            className="mt-4 w-full rounded-lg border border-slate-200 py-1.5 text-xs text-slate-600 hover:bg-slate-50">
            Reset to baseline
          </button>
        </Card>

        <div className="space-y-4">
          {simError ? <ErrorBox error={simError} />
            : sim ? <Projection sim={sim} /> : <Loading what="the projection" />}
        </div>
      </div>
    </div>
  )
}

function Projection({ sim }: { sim: Simulation }) {
  const blocked = sim.preflight.blocked
  return (
    <>
      <Card className={blocked ? 'border-red-200' : ''}>
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div>
            <div className="text-[11px] uppercase tracking-[0.08em] text-slate-500">
              Projected cost per document
            </div>
            <div className="mt-1 flex items-baseline gap-3">
              <motion.span key={sim.projected.cost_per_document_usd}
                initial={{ opacity: 0.4, y: 4 }} animate={{ opacity: 1, y: 0 }}
                className="text-4xl font-semibold tabular text-[var(--projected)]">
                {usd(sim.projected.cost_per_document_usd, 3)}
              </motion.span>
              <span className="tabular text-sm font-medium"
                style={{ color: sim.projected.pct_change < 0 ? 'var(--pass)' : 'var(--fail)' }}>
                {signedPct(sim.projected.pct_change)}
              </span>
            </div>
            <div className="mt-1 text-xs text-slate-500">
              vs measured baseline {usd(sim.basis.measured_cost_per_document_usd, 3)} ·{' '}
              {usd(sim.projected.monthly_spend_usd, 0)}/month at current volume
            </div>
          </div>
          <div className="text-right">
            <div className="text-[11px] uppercase tracking-[0.08em] text-slate-500">Projected p95</div>
            <div className="mt-1 text-2xl font-semibold tabular"
              style={{ color: sim.latency_risk.breaches ? 'var(--fail)' : 'var(--ink)' }}>
              {ms(sim.projected.latency_p95_ms)}
            </div>
            <div className="text-xs text-slate-500">ceiling {ms(sim.latency_risk.ceiling_ms)}</div>
          </div>
        </div>

        <div className={`mt-4 rounded-xl border p-3 ${
          blocked ? 'border-red-200 bg-red-50/60' : 'border-emerald-200 bg-emerald-50/50'
        }`}>
          <div className="flex items-center gap-2">
            <Pill tone={blocked ? 'fail' : 'pass'}>
              {blocked ? 'Pre-flight blocked' : 'Pre-flight clear'}
            </Pill>
            <span className="text-sm" style={{ color: blocked ? 'var(--fail)' : 'var(--pass)' }}>
              {blocked
                ? 'This combination would breach a declared constraint. It is flagged before it runs.'
                : 'No projected constraint breach. Record it and evaluate it before promoting.'}
            </span>
          </div>
          {sim.preflight.reasons.map((r) => (
            <div key={r} className="mt-1.5 text-[12px] text-red-900/85">— {r}</div>
          ))}
        </div>
      </Card>

      <div className="grid gap-4 lg:grid-cols-2">
        <Card>
          <SectionTitle hint="projected against declared floors">Floor risk</SectionTitle>
          <div className="space-y-2.5">
            {sim.floor_risk.map((f) => (
              <div key={f.metric} className="flex items-center justify-between gap-3">
                <span className="text-sm text-slate-700">{f.label}</span>
                <div className="flex items-center gap-3 text-sm">
                  <span className="text-xs text-slate-400 tabular">floor {num(f.floor, 2)}</span>
                  <span className="tabular font-medium"
                    style={{ color: f.breaches ? 'var(--fail)' : 'var(--ink)' }}>
                    {num(f.projected_value, 3)}
                  </span>
                  <Pill tone={f.breaches ? 'fail' : 'pass'}>
                    {f.breaches ? `breach ${num(Math.abs(f.margin), 3)}` : `margin ${num(f.margin, 3)}`}
                  </Pill>
                </div>
              </div>
            ))}
          </div>
          <p className="mt-3 text-[11px] leading-relaxed text-slate-500">
            Projected quality is the measured baseline plus the measured single-lever deltas. It is
            an estimate — the floor it is compared against is not.
          </p>
        </Card>

        <Card className={sim.measured_match ? 'border-emerald-200' : ''}>
          <SectionTitle hint={sim.measured_match ? 'this configuration was actually run' : 'no matching recording'}>
            Projected vs measured
          </SectionTitle>
          {sim.measured_match ? (
            <div className="space-y-3">
              <div className="flex items-center justify-between">
                <span className="text-sm text-slate-600">{sim.measured_match.label ?? sim.measured_match.config_id}</span>
                <Pill tone={sim.measured_match.decision === 'PROMOTE' ? 'pass'
                  : sim.measured_match.decision === 'REJECT' ? 'fail' : 'neutral'}>
                  {sim.measured_match.decision}
                </Pill>
              </div>
              <div className="grid grid-cols-2 gap-4">
                <div>
                  <div className="text-[11px] uppercase tracking-[0.08em] text-[var(--projected)]">Projected</div>
                  <div className="text-2xl font-semibold tabular text-[var(--projected)]">
                    {usd(sim.projected.cost_per_document_usd, 3)}
                  </div>
                </div>
                <div>
                  <div className="text-[11px] uppercase tracking-[0.08em] text-slate-500">Measured</div>
                  <div className="text-2xl font-semibold tabular">
                    {usd(sim.measured_match.measured_cost_per_document_usd, 3)}
                  </div>
                </div>
              </div>
              <div className="rounded-lg bg-slate-50 px-3 py-2 text-xs text-slate-600">
                Projection error{' '}
                <span className="tabular font-semibold">
                  {signedPct(sim.measured_match.projection_error_pct, 1)}
                </span>{' '}
                — the cost of assuming levers compose independently. This is why the projection
                cannot promote anything.
              </div>
              <div className="space-y-1.5 border-t border-slate-100 pt-2">
                {Object.entries(sim.measured_match.measured_quality).map(([m, v]) => (
                  <div key={m} className="flex justify-between text-xs">
                    <span className="text-slate-500">{m}</span>
                    <span className="tabular">
                      <span className="text-[var(--projected)]">
                        {num(sim.projected.quality_estimate[m], 3)}
                      </span>
                      <span className="mx-1.5 text-slate-300">→</span>
                      <span className="font-medium">{num(v, 3)}</span>
                    </span>
                  </div>
                ))}
              </div>
            </div>
          ) : (
            <p className="text-sm leading-relaxed text-slate-500">
              No recorded configuration matches this exact lever set, so there is nothing measured
              to put beside the projection. Record it with the harness and evaluate it on the
              promotion board — that is the only path from this screen to a decision.
            </p>
          )}
        </Card>
      </div>

      <Card>
        <SectionTitle hint="measured one lever at a time, on the golden set">
          Where the projection comes from
        </SectionTitle>
        <div className="overflow-x-auto">
          <table className="w-full border-collapse text-sm">
            <thead>
              <tr className="border-b hairline">
                {['Lever', 'Value', 'Cost ×', 'Latency ×', 'Quality effect'].map((h, i) => (
                  <th key={h} className={`pb-2 text-[11px] font-semibold uppercase tracking-[0.07em] text-slate-500 ${i < 2 ? 'text-left' : 'text-right'}`}>
                    {h}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {sim.lever_effects.map((e) => (
                <tr key={e.id} className={`border-b border-slate-100 ${e.is_baseline ? 'opacity-45' : ''}`}>
                  <td className="py-2 text-slate-700">{e.label}</td>
                  <td className="py-2 text-slate-600">
                    {typeof e.value === 'boolean' ? (e.value ? 'on' : 'off') : String(e.value)}
                  </td>
                  <td className="py-2 text-right tabular">{e.cost_multiplier.toFixed(3)}</td>
                  <td className="py-2 text-right tabular">{e.latency_multiplier.toFixed(3)}</td>
                  <td className="py-2 text-right tabular text-xs">
                    {Object.keys(e.quality_effect).length === 0 ? (
                      <span className="text-slate-400">none measured</span>
                    ) : Object.entries(e.quality_effect).map(([m, d]) => (
                      <span key={m} className="ml-3"
                        style={{ color: d > 0 ? 'var(--pass)' : 'var(--fail)' }}>
                        {m} {d >= 0 ? '+' : ''}{num(d, 3)}
                      </span>
                    ))}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <p className="mt-3 text-[11px] leading-relaxed text-slate-500">{sim.disclaimer}</p>
      </Card>
    </>
  )
}
