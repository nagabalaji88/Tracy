/**
 * ATLAS — research desk terminal.
 *
 * The important design decision on this screen is what it does NOT show. When a
 * run finishes the operator gets four numbers and a green COMPLETE: elapsed,
 * total tokens, an estimated cost, and a call count. No per-stage cost, no
 * per-desk attribution, no quality, no notion of whether the memo was usable.
 *
 * That is not laziness in the mock. It is the actual reporting surface of the
 * system, and it is the reason the flaws below survive in production.
 */
import { useEffect, useRef, useState } from 'react'

type Issuer = {
  ticker: string; name: string; sector: string; filing_pages: number
  figures: number; disclosures: number; complexity: number
  peers: string[]; peer_graph_cyclic: boolean
}
type Profile = {
  id: string; label: string; note: string
  model_by_stage: Record<string, string>
  filing_extract_pages: number; max_peers: number
  peer_depth_limit: number | null; memo_max_tokens: number; reasoning: boolean
}
type Flaw = {
  id: string; title: string; severity: string; atlas_does: string
  why_realistic: string; consequence: string; detected_by: string
  control_plane_screen: string
}
type RunRow = {
  run_id: string; ticker: string; issuer: string; profile_label: string
  started_at: string; elapsed_s: number; status: string
  total_tokens: number; estimated_cost_usd: number; llm_calls: number
}
type CostReport = {
  month: string; runs_this_month: number; estimated_spend_usd: number
  monthly_budget_usd: number; pct_of_budget: number; status: string
  rate_note: string; generated: string; known_gaps: string[]
}
type Line = { text: string; cls: string }

const j = <T,>(p: string): Promise<T> => fetch(p).then((r) => r.json())
const clock = () => new Date().toISOString().slice(11, 23)

export default function App() {
  const [universe, setUniverse] = useState<Issuer[]>([])
  const [profiles, setProfiles] = useState<Profile[]>([])
  const [flaws, setFlaws] = useState<Flaw[]>([])
  const [ticker, setTicker] = useState('NRTH')
  const [profile, setProfile] = useState('standard')
  const [lines, setLines] = useState<Line[]>([])
  const [running, setRunning] = useState(false)
  const [summary, setSummary] = useState<Record<string, unknown> | null>(null)
  const [tab, setTab] = useState<'history' | 'cost' | 'gaps'>('history')
  const [history, setHistory] = useState<RunRow[]>([])
  const [cost, setCost] = useState<CostReport | null>(null)
  const [handoff, setHandoff] = useState<string | null>(null)
  const consoleRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    j<Issuer[]>('/atlas/universe').then(setUniverse)
    j<Profile[]>('/atlas/profiles').then(setProfiles)
    j<{ flaws: Flaw[] }>('/atlas/flaws').then((d) => setFlaws(d.flaws))
    refresh()
  }, [])

  useEffect(() => {
    if (consoleRef.current) consoleRef.current.scrollTop = consoleRef.current.scrollHeight
  }, [lines])

  const refresh = () => {
    j<RunRow[]>('/atlas/runs').then(setHistory)
    j<CostReport>('/atlas/cost-report').then(setCost)
  }

  const push = (text: string, cls = '') => setLines((l) => [...l, { text, cls }])

  const run = () => {
    setLines([]); setSummary(null); setRunning(true); setHandoff(null)
    const src = new EventSource(`/atlas/run/stream?ticker=${ticker}&profile=${profile}`)
    src.onmessage = (ev) => {
      const e = JSON.parse(ev.data)
      const t = clock()
      switch (e.kind) {
        case 'run_start':
          push(`${t}  ATLAS v3.2.1  run ${e.run_id}`, 't-cyan')
          push(`${t}  subject   ${e.ticker} · ${e.issuer} · ${e.sector}`)
          push(`${t}  profile   ${e.profile}  —  ${e.profile_note}`, 't-dim')
          push(`${t}  routing   desk=${e.desk} mandate=${e.mandate} analyst=${e.analyst}`, 't-dim')
          push(`${t}  filing    ${e.filing_pages} pages, extracting ${e.extract_pages}`, 't-dim')
          push('')
          break
        case 'stage_start':
          push(`${t}  [${e.n}/7] ${e.stage.toUpperCase()} …`, 't-amber')
          break
        case 'stage_end':
          push(`${t}        ok   ${e.detail}`, 't-green')
          break
        case 'tool_call':
          push(`${t}        ->   peer_lookup(${e.target})  depth=${e.depth}  call #${e.call}`,
            e.depth > 2 ? 't-red' : 't-dim')
          break
        case 'debug_retry':
          // Emitted at DEBUG. In production nobody has this level enabled, which
          // is the point of flaw F04 — it is rendered dim on purpose.
          push(`${t}        dbg  ${e.stage}: ${e.note}`, 't-dim')
          break
        case 'hard_stop':
          push('')
          push(`${t}  !!    ${e.note}`, 't-red')
          push(`${t}  !!    ${e.peer_calls} peer lookups executed before the stop`, 't-red')
          push('')
          break
        case 'run_end':
          push('')
          push(`${t}  STATUS  ${e.status}`, 't-green')
          setSummary(e)
          setRunning(false)
          src.close()
          break
        case 'saved':
          refresh()
          break
        case 'error':
          push(`${t}  ERROR  ${e.detail}`, 't-red'); setRunning(false); src.close()
          break
      }
    }
    src.onerror = () => { setRunning(false); src.close() }
  }

  const sendToControlPlane = async () => {
    setHandoff('sending…')
    try {
      const res = await fetch('/atlas/handoff', { method: 'POST' })
      const body = await res.json()
      setHandoff(res.ok
        ? `sent ${body.sent} runs → ${body.result.ingested.traces} spans mapped, `
          + `${body.result.ingested.outcomes} outcomes scored`
        : `FAILED: ${body.detail}`)
    } catch (e) {
      setHandoff(`FAILED: ${e}`)
    }
  }

  const iss = universe.find((u) => u.ticker === ticker)
  const prof = profiles.find((p) => p.id === profile)

  return (
    <div style={{ display: 'flex', flexDirection: 'column', height: '100%' }}>
      <Header />
      <Tape universe={universe} />

      <div style={{ display: 'grid', gridTemplateColumns: '250px 1fr 260px', gap: 1,
        flex: 1, minHeight: 0, background: 'var(--line)' }}>
        {/* ---- request ---- */}
        <div className="panel" style={{ padding: 12, overflowY: 'auto' }}>
          <div className="lbl" style={{ marginBottom: 8 }}>New request</div>
          <div className="lbl" style={{ marginBottom: 3 }}>Issuer</div>
          <select value={ticker} onChange={(e) => setTicker(e.target.value)} disabled={running}>
            {universe.map((u) => (
              <option key={u.ticker} value={u.ticker}>{u.ticker} — {u.name}</option>
            ))}
          </select>
          {iss && (
            <div style={{ marginTop: 8, fontSize: 11, color: 'var(--fg-dim)' }}>
              <Kv k="sector" v={iss.sector} />
              <Kv k="filing" v={`${iss.filing_pages} pp`} />
              <Kv k="tagged figures" v={String(iss.figures)} />
              <Kv k="disclosures" v={String(iss.disclosures)} />
              <Kv k="peers" v={iss.peers.join(' ') || '—'} />
              {iss.peer_graph_cyclic && (
                <div className="t-red" style={{ marginTop: 6, lineHeight: 1.35 }}>
                  ⚠ peer graph contains cycles
                  <div className="t-dim" style={{ fontSize: 10 }}>
                    peer_comparison has no visited set and no depth cap (F06)
                  </div>
                </div>
              )}
            </div>
          )}

          <div className="lbl" style={{ margin: '14px 0 3px' }}>Profile</div>
          <select value={profile} onChange={(e) => setProfile(e.target.value)} disabled={running}>
            {profiles.map((p) => <option key={p.id} value={p.id}>{p.label}</option>)}
          </select>
          {prof && (
            <div style={{ marginTop: 8, fontSize: 11, color: 'var(--fg-dim)' }}>
              <div className="t-dim" style={{ marginBottom: 6, lineHeight: 1.35 }}>{prof.note}</div>
              <Kv k="extract" v={`${prof.filing_extract_pages} pp`} />
              <Kv k="max peers" v={String(prof.max_peers)} />
              <Kv k="depth cap" v={prof.peer_depth_limit === null ? 'none' : String(prof.peer_depth_limit)}
                warn={prof.peer_depth_limit === null} />
              <Kv k="memo cap" v={`${prof.memo_max_tokens} tok`} />
              {Object.entries(prof.model_by_stage).map(([s, m]) => (
                <Kv key={s} k={s} v={m} />
              ))}
            </div>
          )}

          <button className="primary" onClick={run} disabled={running}
            style={{ width: '100%', marginTop: 14, padding: '9px 0' }}>
            {running ? 'running…' : '▶ execute'}
          </button>
        </div>

        {/* ---- console ---- */}
        <div style={{ display: 'flex', flexDirection: 'column', minWidth: 0, background: 'var(--panel)' }}>
          <div style={{ padding: '6px 10px', borderBottom: '1px solid var(--line)',
            display: 'flex', justifyContent: 'space-between' }}>
            <span className="lbl">Execution log</span>
            <span className="lbl">{lines.length} lines</span>
          </div>
          <div className="console" ref={consoleRef} style={{ flex: 1, border: 'none' }}>
            {lines.length === 0 && (
              <div className="t-dim">
                ATLAS research terminal ready.{'\n'}
                Select an issuer and press EXECUTE.{'\n\n'}
                <span className="t-amber">Try NRTH or HRBR</span> — financials-sector peer graphs
                are cyclic.{'\n'}
                <span className="cursor" />
              </div>
            )}
            {lines.map((l, i) => (
              <div key={i} className={`row ${l.cls}`}>{l.text || ' '}</div>
            ))}
            {running && <div className="cursor" />}
          </div>
        </div>

        {/* ---- what ATLAS reports ---- */}
        <div className="panel" style={{ padding: 12, overflowY: 'auto' }}>
          <div className="lbl" style={{ marginBottom: 8 }}>Run summary</div>
          {!summary ? (
            <div className="t-faint" style={{ color: 'var(--fg-faint)' }}>— no completed run —</div>
          ) : (
            <>
              <div className="t-green" style={{ fontSize: 22, letterSpacing: '0.05em' }}>
                ✓ {String(summary.status)}
              </div>
              <div className="t-dim" style={{ fontSize: 10, marginBottom: 12 }}>
                {String(summary.run_id)}
              </div>
              <Big label="Elapsed" value={`${Number(summary.elapsed_s).toFixed(1)}s`} />
              <Big label="Total tokens" value={Number(summary.total_tokens).toLocaleString()} />
              <Big label="Estimated cost" value={`$${Number(summary.estimated_cost_usd).toFixed(2)}`} />
              <Big label="LLM calls" value={String(summary.llm_calls)} />
              <div style={{ marginTop: 14, paddingTop: 10, borderTop: '1px solid var(--line)',
                fontSize: 10.5, lineHeight: 1.5, color: 'var(--fg-faint)' }}>
                This is the entire reporting surface. No per-stage cost, no attribution to
                desk or mandate, no quality signal, and no record of whether the memo was
                usable — COMPLETE means nothing raised.
              </div>
            </>
          )}

          <div style={{ marginTop: 16, paddingTop: 12, borderTop: '1px solid var(--line)' }}>
            <div className="lbl" style={{ marginBottom: 6 }}>Control plane</div>
            <button onClick={sendToControlPlane} disabled={running}
              style={{ width: '100%' }}>↗ send runs</button>
            {handoff && (
              <div style={{ marginTop: 6, fontSize: 10, lineHeight: 1.45 }}
                className={handoff.startsWith('FAILED') ? 't-red' : 't-green'}>
                {handoff}
              </div>
            )}
            <div className="t-dim" style={{ fontSize: 10, marginTop: 6, lineHeight: 1.45 }}>
              POSTs the debug records to :8000. ATLAS knows one thing about the control
              plane — a URL.
            </div>
          </div>
        </div>
      </div>

      {/* ---- bottom drawer ---- */}
      <div className="panel" style={{ borderTop: '1px solid var(--line)', height: 236,
        display: 'flex', flexDirection: 'column' }}>
        <div style={{ display: 'flex', gap: 1, borderBottom: '1px solid var(--line)' }}>
          {([['history', `run history (${history.length})`],
             ['cost', 'monthly cost report'],
             ['gaps', `known gaps (${flaws.length})`]] as const).map(([k, label]) => (
            <button key={k} onClick={() => setTab(k)} className={tab === k ? 'on' : ''}
              style={{ border: 'none', borderRight: '1px solid var(--line)' }}>{label}</button>
          ))}
          <div style={{ flex: 1 }} />
          <button onClick={refresh} style={{ border: 'none' }}>refresh</button>
        </div>
        <div style={{ flex: 1, overflowY: 'auto', padding: tab === 'history' ? 0 : 12 }}>
          {tab === 'history' && <History rows={history} />}
          {tab === 'cost' && cost && <Cost report={cost} />}
          {tab === 'gaps' && <Gaps flaws={flaws} />}
        </div>
      </div>
    </div>
  )
}

function Header() {
  return (
    <div className="hdr" style={{ display: 'flex', alignItems: 'center', gap: 16, padding: '8px 12px' }}>
      <span style={{ color: 'var(--amber)', fontWeight: 700, letterSpacing: '0.16em' }}>ATLAS</span>
      <span className="t-dim" style={{ fontSize: 11 }}>
        Analyst Toolkit for Long-form Automated Screening · v3.2.1
      </span>
      <div style={{ flex: 1 }} />
      <span className="lbl">research desk</span>
      <span className="lbl" style={{ color: 'var(--green)' }}>● connected</span>
    </div>
  )
}

function Tape({ universe }: { universe: Issuer[] }) {
  const text = universe.map((u) =>
    `${u.ticker} ${u.sector.toUpperCase()} ${u.filing_pages}pp ${u.peer_graph_cyclic ? '⟲' : '·'}`
  ).join('     ')
  return (
    <div className="tape">
      <span className="t-dim" style={{ paddingLeft: 12, fontSize: 10.5, letterSpacing: '0.06em' }}>
        COVERAGE  {text || '—'}
      </span>
    </div>
  )
}

function Kv({ k, v, warn }: { k: string; v: string; warn?: boolean }) {
  return (
    <div style={{ display: 'flex', justifyContent: 'space-between', gap: 8 }}>
      <span style={{ color: 'var(--fg-faint)' }}>{k}</span>
      <span className={warn ? 't-red' : ''}>{v}</span>
    </div>
  )
}

function Big({ label, value }: { label: string; value: string }) {
  return (
    <div style={{ marginBottom: 10 }}>
      <div className="lbl">{label}</div>
      <div style={{ fontSize: 17, fontVariantNumeric: 'tabular-nums' }}>{value}</div>
    </div>
  )
}

function History({ rows }: { rows: RunRow[] }) {
  if (!rows.length) return <div className="t-dim" style={{ padding: 12 }}>no runs recorded</div>
  return (
    <table>
      <thead>
        <tr>
          <th>run</th><th>issuer</th><th>profile</th><th>started</th>
          <th className="num">elapsed</th><th className="num">calls</th>
          <th className="num">tokens</th><th className="num">est. cost</th><th>status</th>
        </tr>
      </thead>
      <tbody>
        {rows.slice(0, 60).map((r) => (
          <tr key={r.run_id}>
            <td className="t-dim">{r.run_id}</td>
            <td>{r.ticker}</td>
            <td className="t-dim">{r.profile_label}</td>
            <td className="t-dim">{r.started_at.slice(0, 16).replace('T', ' ')}</td>
            <td className="num">{r.elapsed_s.toFixed(1)}s</td>
            <td className="num">{r.llm_calls}</td>
            <td className="num">{r.total_tokens.toLocaleString()}</td>
            <td className="num">${r.estimated_cost_usd.toFixed(2)}</td>
            <td className="t-green">{r.status}</td>
          </tr>
        ))}
      </tbody>
    </table>
  )
}

function Cost({ report }: { report: CostReport }) {
  return (
    <div style={{ display: 'grid', gridTemplateColumns: '1fr 1.4fr', gap: 24 }}>
      <div>
        <div className="lbl">Month {report.month}</div>
        <div style={{ fontSize: 26, marginTop: 4, fontVariantNumeric: 'tabular-nums' }}>
          ${report.estimated_spend_usd.toLocaleString()}
        </div>
        <div className="t-dim">
          of ${report.monthly_budget_usd.toLocaleString()} budget · {report.pct_of_budget}%
        </div>
        <div className={report.status === 'OVER BUDGET' ? 't-red' : 't-green'}
          style={{ marginTop: 8, letterSpacing: '0.1em' }}>
          {report.status}
        </div>
        <div className="t-dim" style={{ marginTop: 10, fontSize: 10.5, lineHeight: 1.5 }}>
          {report.runs_this_month} runs · {report.rate_note}<br />{report.generated}
        </div>
      </div>
      <div>
        <div className="lbl" style={{ marginBottom: 6 }}>What this report cannot tell you</div>
        {report.known_gaps.map((g, i) => (
          <div key={i} style={{ display: 'flex', gap: 8, marginBottom: 3, lineHeight: 1.45 }}>
            <span className="t-red">✗</span>
            <span className="t-dim">{g}</span>
          </div>
        ))}
      </div>
    </div>
  )
}

function Gaps({ flaws }: { flaws: Flaw[] }) {
  return (
    <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(370px, 1fr))', gap: 10 }}>
      {flaws.map((f) => (
        <div key={f.id} className="panel-2" style={{ padding: 9 }}>
          <div style={{ display: 'flex', gap: 8, alignItems: 'baseline' }}>
            <span className="t-dim">{f.id}</span>
            <span style={{ flex: 1 }}>{f.title}</span>
            <span className={`sev-${f.severity} lbl`}>{f.severity}</span>
          </div>
          <div className="t-dim" style={{ marginTop: 5, lineHeight: 1.45, fontSize: 10.5 }}>
            {f.atlas_does}
          </div>
          <div style={{ marginTop: 5, lineHeight: 1.45, fontSize: 10.5, color: 'var(--fg-faint)' }}>
            <span className="t-amber">why it shipped: </span>{f.why_realistic}
          </div>
          <div style={{ marginTop: 5, lineHeight: 1.45, fontSize: 10.5 }} className="t-red">
            {f.consequence}
          </div>
          <div style={{ marginTop: 6, paddingTop: 5, borderTop: '1px solid var(--line)',
            fontSize: 10.5 }} className="t-cyan">
            caught by → {f.detected_by}
          </div>
        </div>
      ))}
    </div>
  )
}
