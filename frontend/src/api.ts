/**
 * API client. Every number rendered by this app comes from one of these calls —
 * there is no client-side arithmetic on money or quality anywhere in the UI.
 */

const BASE = '/api/v1'

export class ApiError extends Error {
  constructor(public status: number, message: string) {
    super(message)
  }
}

async function req<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    headers: { 'Content-Type': 'application/json' },
    ...init,
  })
  if (!res.ok) {
    let detail = res.statusText
    try {
      detail = (await res.json()).detail ?? detail
    } catch {
      /* keep statusText */
    }
    throw new ApiError(res.status, detail)
  }
  return res.json() as Promise<T>
}

export const api = {
  spine: () => req<Spine>('/spine'),
  configs: (useCase?: string) =>
    req<ConfigRow[]>(`/configs${useCase ? `?use_case=${useCase}` : ''}`),
  board: (useCase = 'contract_analysis') =>
    req<Board>(`/measurement/board?use_case=${useCase}`),
  attribution: (useCase = 'contract_analysis') =>
    req<Attribution>(`/attribution/rollup?use_case=${useCase}`),
  stageEconomics: (useCase = 'contract_analysis') =>
    req<StageEconomics>(`/attribution/stage-economics?use_case=${useCase}`),
  heavyTail: (useCase = 'contract_analysis') =>
    req<HeavyTail>(`/attribution/heavy-tail?use_case=${useCase}`),
  forecast: (useCase = 'contract_analysis') =>
    req<Forecast>(`/forecast?use_case=${useCase}`),
  governor: (useCase = 'contract_analysis') =>
    req<Governor>(`/forecast/governor?use_case=${useCase}`),
  levers: () => req<LeverCatalogue>('/simulate/levers'),
  simulate: (body: SimulateRequest) =>
    req<Simulation>('/simulate', { method: 'POST', body: JSON.stringify(body) }),
  breakerReplay: (useCase = 'contract_analysis') =>
    req<BreakerReplay>(`/breakers/replay?use_case=${useCase}`),
  executive: () => req<Executive>('/executive'),
  reset: () => req<{ status: string; rows: Record<string, number> }>(
    '/admin/reset', { method: 'POST' }),
}

// --- shapes -----------------------------------------------------------------
export interface Spine {
  trace_columns: string[]
  otel_genai_mapping: Record<string, string>
  extensions: Record<string, string>
  adapters: Record<string, { cost_meter: string; scorer: string; metrics: string[] }>
  policy: PolicyDoc
}

export interface PolicyDoc {
  metrics: Record<string, { direction: string; label: string }>
  economics: { human_rework_hourly_rate_usd: number; currency: string }
  significance: { bootstrap_iterations: number; confidence: number; seed: number }
  use_cases: Record<string, UseCasePolicy>
}

export interface UseCasePolicy {
  label: string
  quality_floor: Record<string, number>
  latency_ceiling_ms: number
  monthly_budget_usd: number
  degradation_ladder: { at_pct: number; action: string }[]
  circuit_breakers: Record<string, number>
}

export interface ConfigRow {
  config_id: string
  use_case: string
  label: string
  role: string
  ablated_stage: string | null
  levers: Record<string, unknown>
  recorded_at: string
}

export interface Cpso {
  model_spend_usd: number
  rework_minutes: number
  rework_usd: number
  hourly_rate_usd: number
  numerator_usd: number
  successes: number
  attempts: number
  success_rate: number
  value_usd: number | null
  undefined_reason: string | null
}

export interface Measured {
  config_id: string
  label: string
  n_documents: number
  n_spans: number
  total_spend_usd: number
  cost_per_document_usd: number
  cost_percentiles_usd: { p50: number; p95: number; p99: number }
  latency_ms: { p50: number; p95: number; p99: number }
  quality: Record<string, number>
  quality_n: Record<string, number>
  cost_per_successful_outcome: Cpso
  spend_by_stage_usd: Record<string, number>
  spend_by_bucket_usd: Record<string, number>
  tokens: Record<string, number>
  per_document: Record<string, { cost_usd: number; latency_ms: number }>
}

export interface FloorRecord {
  metric: string
  label: string
  direction: string
  floor: number
  candidate_value: number
  baseline_value: number | null
  shortfall: number | null
  n: number | null
}

export interface Decision {
  decision: 'PROMOTE' | 'REJECT'
  baseline_config_id: string
  candidate_config_id: string
  headline: string
  reasons: { code: string; metric: string; detail: string; magnitude: number | null }[]
  warnings: { code: string; metric: string; detail: string }[]
  failed_floors: FloorRecord[]
  passed_floors: FloorRecord[]
  latency_breach: { p95_ms: number; ceiling_ms: number; over_by_ms: number } | null
  cost_delta_pct: number
  cost_saving_usd: number
  n_paired_documents: number
}

export interface Bootstrap {
  observed_mean_delta: number
  ci_low: number
  ci_high: number
  confidence: number
  iterations: number
  n_pairs: number
  significant: boolean
}

export interface Comparison {
  baseline_config_id: string
  candidate_config_id: string
  n_paired_documents: number
  cost: {
    baseline_total_usd: number
    candidate_total_usd: number
    delta_usd: number
    pct_change: number
    baseline_per_document_usd: number
    candidate_per_document_usd: number
    bootstrap: Bootstrap
    sign_test: { n_effective: number; positive: number; negative: number; p_value: number; significant: boolean }
    cheaper: boolean
    saving_is_significant: boolean
  }
  latency: { baseline_p95_ms: number; candidate_p95_ms: number; delta_ms: number }
  quality: Record<string, {
    label: string
    direction: string
    baseline: number
    candidate: number
    delta: number
    improved: boolean
    bootstrap: Bootstrap
    sign_test: { p_value: number; significant: boolean }
  }>
  cost_per_successful_outcome: {
    baseline_usd: number | null
    candidate_usd: number | null
    pct_change: number | null
    candidate_undefined_reason: string | null
  }
}

export interface Board {
  use_case: string
  environment: string
  policy: UseCasePolicy
  baseline: { config: ConfigRow; measured: Measured }
  candidates: { config: ConfigRow; measured: Measured; comparison: Comparison; decision: Decision }[]
  generated_from: Record<string, unknown>
}

export interface RollupRow {
  key: string
  spend_usd: number
  spans: number
  share_pct: number
  documents?: number
  cost_per_document_usd?: number
}

export interface Attribution {
  use_case: string
  window: { from: string; to: string; days: number }
  total_spend_usd: number
  model_spend_usd: number
  rework_usd: number
  rework_hours: number
  grand_total_usd: number
  rework_multiple_of_model_spend: number | null
  by_team: RollupRow[]
  by_use_case: RollupRow[]
  by_stage: RollupRow[]
  by_prompt_version: RollupRow[]
  by_model: RollupRow[]
  buckets: {
    key: string
    label: string
    spend_usd: number
    share_pct: number
    note: string
    measured: boolean
  }[]
  cached_vs_fresh: {
    fresh_tokens: number
    cached_tokens: number
    fresh_usd: number
    cached_usd: number
    cache_hit_rate: number
    counterfactual_usd_without_cache: number
    saved_usd: number
  }
}

export interface StageEconomics {
  use_case: string
  baseline_config_id: string
  baseline_cost_per_successful_outcome_usd: number | null
  stages: {
    stage: string
    spend_usd: number
    share_pct: number
    cost_per_document_usd: number
    ablation_config_id: string | null
    ablation_available: boolean
    quality_delta: Record<string, number> | null
    marginal_quality_per_usd: number | null
    verdict: string
    note: string
  }[]
  primary_metric: string
}

export interface HeavyTail {
  use_case: string
  n_documents: number
  percentiles_usd: Record<'p50' | 'p75' | 'p90' | 'p95' | 'p99' | 'max' | 'mean', number>
  top_5pct_share_of_spend: number
  top_1pct_share_of_spend: number
  ratio_p99_p50: number
  histogram: { bucket_usd_lo: number; bucket_usd_hi: number; documents: number; overflow: boolean }[]
  worst: { doc_id: string; cost_usd: number; doc_tier: string | null; succeeded: boolean | null }[]
  by_tier: { tier: string; documents: number; mean_usd: number; p95_usd: number; share_pct: number }[]
}

export interface Forecast {
  use_case: string
  drivers: {
    name: string
    label: string
    unit: string
    current: number
    mean: number
    p50: number
    p95: number
    sigma: number
    n: number
    method: string
    note: string
  }[]
  history: {
    date: string
    spend_usd: number
    documents: number
    calls: number
    retries: number
    tokens_per_call: number
    retry_factor: number
    fan_out: number
    cost_per_document_usd: number
    prompt_version: string
  }[]
  change_points: { date: string; prompt_version: string; day_index: number; spend_before: number; spend_after: number; pct_change: number | null }[]
  projection: { date: string; p50_usd: number; p95_usd: number; cumulative_p50_usd: number; cumulative_p95_usd: number }[]
  month: {
    month: string
    spend_to_date_usd: number
    ongoing_spend_usd: number
    incident_spend_usd: number
    includes_incidents: boolean
    days_elapsed: number
    days_remaining: number
    projected_p50_usd: number
    projected_p95_usd: number
    budget_usd: number
    tail_reserve_usd: number
    p50_pct_of_budget: number
    p95_pct_of_budget: number
  }
  regime: { since: string; prompt_version: string; days_in_regime: number; note: string }
  horizon: { days: number; p50_usd: number; p95_usd: number; tail_reserve_usd: number }
  incidents: {
    n_traces: number
    trace_ids: string[]
    spend_usd: number
    threshold_usd: number
    note: string
  }
  excluded_from_drivers: { batch_spend_usd: number; note: string }
  today: string
  simulations: number
}

export interface Governor {
  use_case: string
  budget_usd: number
  spend_to_date_usd: number
  pct_of_budget: number
  active_rung: { at_pct: number; action: string; description: string } | null
  next_rung: {
    at_pct: number
    action: string
    description: string
    threshold_usd: number
    usd_until: number
    projected_date: string | null
  } | null
  ladder: { at_pct: number; action: string; description: string; threshold_usd: number; state: string }[]
  projected_end_of_month: { p50_usd: number; p95_usd: number; p50_rung: number | null; p95_rung: number | null }
}

export interface LeverCatalogue {
  levers: {
    id: string
    label: string
    kind: string
    options?: (string | number)[]
    default: string | number | boolean
    description: string
    affects: string[]
  }[]
  base_config_id: string
  measured_configs: Record<string, Record<string, unknown>>
}

export interface SimulateRequest {
  use_case: string
  levers: Record<string, string | number | boolean>
}

export interface Simulation {
  use_case: string
  basis: { config_id: string; measured_cost_per_document_usd: number; n_documents: number }
  projected: {
    cost_per_document_usd: number
    monthly_spend_usd: number
    pct_change: number
    latency_p95_ms: number
    quality_estimate: Record<string, number>
    is_projection: true
  }
  lever_effects: {
    id: string
    label: string
    value: string | number | boolean
    cost_multiplier: number
    latency_multiplier: number
    quality_effect: Record<string, number>
    rationale: string
  }[]
  floor_risk: {
    metric: string
    label: string
    floor: number
    projected_value: number
    breaches: boolean
    margin: number
  }[]
  latency_risk: { projected_p95_ms: number; ceiling_ms: number; breaches: boolean }
  preflight: { blocked: boolean; reasons: string[] }
  measured_match: {
    config_id: string
    measured_cost_per_document_usd: number
    measured_quality: Record<string, number>
    decision: string
    projection_error_pct: number
  } | null
  disclaimer: string
}

export interface BreakerReplay {
  use_case: string
  trace_id: string
  breakers: Record<string, number>
  trailing_baseline_usd_per_min: number
  frames: {
    index: number
    span_id: string
    stage: string
    model: string
    agent_depth: number
    input_tokens: number
    cost_usd: number
    cumulative_usd: number
    elapsed_s: number
    velocity_usd_per_min: number
    velocity_multiplier: number
    identical_calls: number
    tripped: string | null
  }[]
  trip: {
    index: number
    breaker: string
    detail: string
    spent_usd: number
    elapsed_s: number
  } | null
  counterfactual: {
    spent_usd: number
    prevented_usd: number
    total_if_unchecked_usd: number
    spans_executed: number
    spans_prevented: number
    monthly_cap_usd: number
    monthly_cap_comment: string
    minutes_to_burn_monthly_cap: number | null
  }
}

export interface Executive {
  generated_at: string
  use_case: string
  window: { from: string; to: string; days: number }
  kpis: {
    cost_per_successful_outcome_usd: number | null
    cost_per_call_usd: number
    total_spend_usd: number
    savings_realised_usd: number
    savings_rejected_usd: number
    success_rate: number
    rework_hours: number
    rework_usd: number
  }
  active_rung: { at_pct: number; action: string } | null
  budget: { budget_usd: number; spend_to_date_usd: number; pct_of_budget: number }
  decisions: { config_id: string; label: string; decision: string; headline: string; cost_delta_pct: number; annualised_usd: number }[]
  provenance: Record<string, unknown>
}
