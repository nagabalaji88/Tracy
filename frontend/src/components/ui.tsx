import { motion, useMotionValue, useTransform, animate } from 'framer-motion'
import { useEffect, type ReactNode } from 'react'
import { ApiError } from '../api'

export function Card({ children, className = '' }: { children: ReactNode; className?: string }) {
  return <div className={`glass p-5 ${className}`}>{children}</div>
}

export function SectionTitle({ children, hint }: { children: ReactNode; hint?: ReactNode }) {
  return (
    <div className="mb-3 flex items-baseline justify-between gap-4">
      <h2 className="text-[13px] font-semibold uppercase tracking-[0.09em] text-slate-500">
        {children}
      </h2>
      {hint && <span className="text-xs text-slate-400">{hint}</span>}
    </div>
  )
}

/** Metric counters animate. Nothing else does. */
export function Counter({ value, format, className = '' }: {
  value: number
  format: (v: number) => string
  className?: string
}) {
  const mv = useMotionValue(0)
  const text = useTransform(mv, (v) => format(v))
  useEffect(() => {
    const controls = animate(mv, value, { duration: 0.65, ease: [0.22, 1, 0.36, 1] })
    return () => controls.stop()
  }, [value, mv])
  return <motion.span className={`tabular ${className}`}>{text}</motion.span>
}

export function Kpi({ label, children, sub, tone = 'default' }: {
  label: string
  children: ReactNode
  sub?: ReactNode
  tone?: 'default' | 'pass' | 'fail' | 'warn' | 'projected'
}) {
  const toneColor = {
    default: 'var(--ink)',
    pass: 'var(--pass)',
    fail: 'var(--fail)',
    warn: 'var(--warn)',
    projected: 'var(--projected)',
  }[tone]
  return (
    <div>
      <div className="text-[11px] font-medium uppercase tracking-[0.08em] text-slate-500">{label}</div>
      <div className="mt-1 text-3xl font-semibold tabular" style={{ color: toneColor }}>{children}</div>
      {sub && <div className="mt-1 text-xs text-slate-500">{sub}</div>}
    </div>
  )
}

export function Pill({ tone, children }: {
  tone: 'pass' | 'fail' | 'warn' | 'neutral' | 'projected'
  children: ReactNode
}) {
  const styles: Record<string, string> = {
    pass: 'bg-[var(--pass-bg)] text-[var(--pass)] border-emerald-200',
    fail: 'bg-[var(--fail-bg)] text-[var(--fail)] border-red-200',
    warn: 'bg-[var(--warn-bg)] text-[var(--warn)] border-amber-200',
    neutral: 'bg-slate-50 text-slate-600 border-slate-200',
    projected: 'bg-violet-50 text-[var(--projected)] border-violet-200',
  }
  return (
    <span className={`inline-flex items-center gap-1.5 rounded-full border px-2.5 py-1 text-[11px] font-semibold uppercase tracking-wide ${styles[tone]}`}>
      {children}
    </span>
  )
}

export function Loading({ what }: { what: string }) {
  return (
    <div className="flex h-64 items-center justify-center text-sm text-slate-400">
      <motion.span
        animate={{ opacity: [0.35, 1, 0.35] }}
        transition={{ repeat: Infinity, duration: 1.4 }}
      >
        Reading {what} from the store…
      </motion.span>
    </div>
  )
}

/**
 * Errors are shown, not swallowed. "Fail loudly on missing data" has to be true
 * in the UI too, or the rule only holds where nobody is looking.
 */
export function ErrorBox({ error }: { error: unknown }) {
  const msg = error instanceof ApiError ? error.message
    : error instanceof Error ? error.message : String(error)
  return (
    <div className="glass border-red-200 bg-red-50/70 p-5">
      <div className="text-sm font-semibold text-[var(--fail)]">The store could not answer that.</div>
      <div className="mt-1.5 font-mono text-xs leading-relaxed text-red-900/80">{msg}</div>
      <div className="mt-3 text-xs text-slate-500">
        No placeholder was substituted. Run <code className="rounded bg-white/70 px-1 py-0.5">python -m harness.record_runs</code> if fixtures are missing.
      </div>
    </div>
  )
}

export function Table({ head, children }: { head: ReactNode[]; children: ReactNode }) {
  return (
    <div className="overflow-x-auto">
      <table className="w-full border-collapse text-sm">
        <thead>
          <tr className="border-b hairline">
            {head.map((h, i) => (
              <th key={i} className={`pb-2 text-[11px] font-semibold uppercase tracking-[0.07em] text-slate-500 ${i === 0 ? 'text-left' : 'text-right'}`}>
                {h}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>{children}</tbody>
      </table>
    </div>
  )
}

export function Bar({ value, tone = 'accent' }: { value: number; tone?: 'accent' | 'fail' | 'pass' }) {
  const color = { accent: 'var(--accent)', fail: 'var(--fail)', pass: 'var(--pass)' }[tone]
  return (
    <div className="h-1.5 w-full overflow-hidden rounded-full bg-slate-100">
      <motion.div
        className="h-full rounded-full"
        style={{ background: color }}
        initial={{ width: 0 }}
        animate={{ width: `${Math.max(0, Math.min(100, value))}%` }}
        transition={{ duration: 0.6, ease: [0.22, 1, 0.36, 1] }}
      />
    </div>
  )
}
