/**
 * The framework page: the spine, the seam, and what a second workload costs.
 *
 * The claim is that onboarding a use case is a policy entry plus two adapters.
 * This page renders that from the live registry rather than asserting it.
 */
import { useResource } from '../useResource'
import { Card, ErrorBox, Loading, Pill, SectionTitle } from '../components/ui'
import { ms, num, usd } from '../format'

interface Framework {
  spine: {
    trace_columns: string[]
    otel_genai_mapping: Record<string, string>
    extensions: Record<string, string>
  }
  adapters: Record<string, { cost_meter: string; scorer: string; metrics: string[] }>
  use_cases: Record<string, {
    label: string
    quality_floor: Record<string, number>
    latency_ceiling_ms: number
    monthly_budget_usd: number
  }>
  metrics: Record<string, { direction: string; label: string }>
  economics: { human_rework_hourly_rate_usd: number; currency: string }
  models_priced: string[]
  onboarding: { steps: string[]; core_files_changed: number; proof: string }
  modules: { id: number; name: string; does: string }[]
}

export function Framework() {
  const { data, error, loading } = useResource<Framework>(
    () => fetch('/api/v1/framework').then((r) => r.json()), [])

  if (loading) return <Loading what="the framework contract" />
  if (error) return <ErrorBox error={error} />
  if (!data) return null

  return (
    <div className="space-y-5">
      <Card>
        <h1 className="text-2xl font-semibold tracking-tight">
          A control plane, not a cost dashboard
        </h1>
        <p className="mt-2 max-w-3xl text-[15px] leading-relaxed text-slate-600">
          Existing tools measure cost or quality. The metric that matters is cost per successful
          outcome, and computing it requires both in one place, joined on the business outcome the
          spend contributed to. That join is the whole design: one trace record carrying{' '}
          <code className="text-[13px]">outcome_id</code>, and one decision procedure willing to
          refuse a saving.
        </p>
        <div className="mt-4 rounded-xl bg-slate-900 px-4 py-3 font-mono text-[13px] text-slate-100">
          minimize cost &nbsp;subject to&nbsp; quality ≥ floor &nbsp;∧&nbsp; latency ≤ ceiling
        </div>
      </Card>

      <Card>
        <SectionTitle hint="rendered from the live adapter registry">
          Onboarding a second workload
        </SectionTitle>
        <div className="grid gap-5 lg:grid-cols-[1.1fr_1fr]">
          <div>
            <ol className="space-y-2">
              {data.onboarding.steps.map((s, i) => (
                <li key={i} className="flex gap-3 text-[13px] leading-relaxed text-slate-700">
                  <span className="mt-0.5 flex h-5 w-5 shrink-0 items-center justify-center rounded-full bg-[var(--accent)] text-[10px] font-semibold text-white">
                    {i + 1}
                  </span>
                  {s}
                </li>
              ))}
            </ol>
            <div className="mt-4 rounded-xl border border-emerald-200 bg-emerald-50/50 p-3">
              <div className="flex items-center gap-2">
                <Pill tone="pass">core files changed: {data.onboarding.core_files_changed}</Pill>
              </div>
              <p className="mt-2 text-[12px] leading-relaxed text-emerald-950/80">
                {data.onboarding.proof}
              </p>
            </div>
          </div>
          <div>
            <div className="mb-2 text-[11px] font-medium uppercase tracking-[0.08em] text-slate-500">
              Registered adapters
            </div>
            <div className="space-y-2">
              {Object.entries(data.adapters).map(([useCase, a]) => (
                <div key={useCase} className="rounded-xl border border-slate-200/80 bg-white/50 p-3">
                  <div className="font-medium">{useCase}</div>
                  <div className="mt-1 space-y-0.5 text-[11px] text-slate-500">
                    <div>CostMeter · <code>{a.cost_meter}</code></div>
                    <div>Scorer · <code>{a.scorer}</code></div>
                    <div>metrics · {a.metrics.join(', ')}</div>
                  </div>
                </div>
              ))}
            </div>
          </div>
        </div>
      </Card>

      <div className="grid gap-4 lg:grid-cols-2">
        <Card>
          <SectionTitle hint="policy.yaml — the public contract">Declared use cases</SectionTitle>
          <div className="space-y-3">
            {Object.entries(data.use_cases).map(([name, uc]) => (
              <div key={name} className="rounded-xl border border-slate-200/80 bg-white/50 p-3">
                <div className="flex items-baseline justify-between gap-3">
                  <span className="font-medium">{uc.label}</span>
                  <code className="text-[11px] text-slate-400">{name}</code>
                </div>
                <div className="mt-2 flex flex-wrap gap-x-5 gap-y-1 text-[12px] text-slate-600">
                  {Object.entries(uc.quality_floor).map(([m, v]) => (
                    <span key={m} className="tabular">
                      {m} {data.metrics[m]?.direction === 'lower_is_better' ? '≤' : '≥'} {num(v, 2)}
                    </span>
                  ))}
                  <span className="tabular">p95 ≤ {ms(uc.latency_ceiling_ms)}</span>
                  <span className="tabular">{usd(uc.monthly_budget_usd, 0)}/month</span>
                </div>
              </div>
            ))}
          </div>
          <p className="mt-3 text-[11px] leading-relaxed text-slate-500">
            Every metric declares its direction. The engine refuses to guess whether higher or
            lower is better — a control plane that guesses at that will eventually enforce a floor
            backwards.
          </p>
        </Card>

        <Card>
          <SectionTitle hint="OpenTelemetry GenAI semantic conventions">The spine</SectionTitle>
          <div className="max-h-[300px] overflow-y-auto">
            <table className="w-full border-collapse text-[12px]">
              <tbody>
                {Object.entries(data.spine.otel_genai_mapping).map(([col, otel]) => (
                  <tr key={col} className="border-b border-slate-100">
                    <td className="py-1 font-mono text-slate-700">{col}</td>
                    <td className="py-1 text-right font-mono text-slate-400">{otel}</td>
                  </tr>
                ))}
                {Object.entries(data.spine.extensions).map(([col, why]) => (
                  <tr key={col} className="border-b border-slate-100">
                    <td className="py-1 font-mono text-[var(--accent)]">{col}</td>
                    <td className="py-1 pl-4 text-right text-[11px] leading-snug text-slate-500">{why}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <p className="mt-3 text-[11px] leading-relaxed text-slate-500">
            Grey rows follow the OTel GenAI conventions. Blue rows are the extensions a cost-quality
            control plane needs and OTel does not yet define — chiefly{' '}
            <code>outcome_id</code>, which is what makes cost per successful outcome computable at
            all.
          </p>
        </Card>
      </div>

      <Card>
        <SectionTitle hint="built in this order, hero first">Modules</SectionTitle>
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
          {data.modules.map((m) => (
            <div key={m.id} className="rounded-xl border border-slate-200/80 bg-white/50 p-4">
              <div className="text-[10px] font-semibold uppercase tracking-[0.1em] text-slate-400">
                Module {m.id}
              </div>
              <div className="mt-1 text-sm font-semibold">{m.name}</div>
              <p className="mt-1.5 text-[12px] leading-relaxed text-slate-600">{m.does}</p>
            </div>
          ))}
        </div>
      </Card>

      <Card>
        <SectionTitle>Architecture</SectionTitle>
        <div className="overflow-x-auto">
          <pre className="min-w-[720px] font-mono text-[11.5px] leading-[1.5] text-slate-600">{`
  recording session                     the store                    the control plane
  ─────────────────                     ─────────                    ─────────────────
  LiveProvider ─┐                                              ┌─ M1 promotion engine
                ├─▶ pipeline runs ─▶ CostMeter ─┐              │    compute_baseline
  Deterministic ┘   (4 stages)                  ├─▶ traces ────┤    evaluate_candidate
  Provider                          Scorer ─────┘   outcomes   │    promotion_decision
                                      ▲            configs     │
                                      │                        ├─ M2 attribution
                              recorded artifacts               ├─ M3 forecast + governor
                              (never a guessed score)          ├─ M4 simulator (projected)
                                                               ├─ M5 circuit breakers
                                                               └─ M6 executive view
                                            ▲
                                            │
                                       policy.yaml
                            floors · ceiling · budget · ladder · breakers
`}</pre>
        </div>
        <p className="mt-2 text-[11px] leading-relaxed text-slate-500">
          Services are pure functions over plain dicts — no FastAPI import, no sqlite import — so
          the promotion engine is unit-testable in isolation, and it is. Pydantic appears only at
          the API boundary.
        </p>
      </Card>
    </div>
  )
}
