import { motion, useMotionValue, useTransform, animate } from 'framer-motion'
import { useEffect, type ReactNode } from 'react'
import { ApiError } from '../api'

export function Card({ children, className = '' }: { children: ReactNode; className?: string }) {
  return <div className={`glass p-5 ${className}`}>{children}</div>
}

export function SectionTitle({ children, hint }: { children: ReactNode; hint?: ReactNode }) {
  return (
    <div className="mb-3.5 flex items-baseline justify-between gap-4">
      <h2 className="flex items-center gap-2 text-[12px] font-bold uppercase tracking-[0.1em] text-slate-500">
        <span className="h-3.5 w-1 rounded-full bg-[var(--accent)]" aria-hidden />
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

const TONE: Record<string, string> = {
  default: 'var(--ink)',
  pass: 'var(--pass)',
  fail: 'var(--fail)',
  warn: 'var(--warn)',
  projected: 'var(--projected)',
  accent: 'var(--accent)',
}

export function Kpi({ label, children, sub, tone = 'default' }: {
  label: string
  children: ReactNode
  sub?: ReactNode
  tone?: 'default' | 'pass' | 'fail' | 'warn' | 'projected' | 'accent'
}) {
  return (
    <div>
      <div className="text-[11px] font-semibold uppercase tracking-[0.09em] text-slate-500">{label}</div>
      <div className="mt-1.5 text-3xl font-bold tabular tracking-tight" style={{ color: TONE[tone] }}>
        {children}
      </div>
      {sub && <div className="mt-1 text-xs text-slate-500">{sub}</div>}
    </div>
  )
}

/**
 * Status badges: pastel fill, saturated text, a dot to carry the state for
 * anyone reading the shape rather than the hue.
 */
export function Pill({ tone, children }: {
  tone: 'pass' | 'fail' | 'warn' | 'neutral' | 'projected'
  children: ReactNode
}) {
  const styles: Record<string, string> = {
    pass: 'bg-[var(--pass-bg)] text-[var(--pass)]',
    fail: 'bg-[var(--fail-bg)] text-[var(--fail)]',
    warn: 'bg-[var(--warn-bg)] text-[var(--warn)]',
    neutral: 'bg-slate-100 text-slate-600',
    projected: 'bg-[var(--projected-bg)] text-[var(--projected)]',
  }
  return (
    <span className={`inline-flex items-center gap-1.5 rounded-full px-2.5 py-1 text-[11px] font-bold uppercase tracking-wide ${styles[tone]}`}>
      <span className="h-1.5 w-1.5 rounded-full bg-current opacity-70" aria-hidden />
      {children}
    </span>
  )
}

export function Loading({ what }: { what: string }) {
  return (
    <div className="flex h-64 flex-col items-center justify-center gap-3 text-sm text-slate-400">
      <motion.span
        className="h-7 w-7 rounded-full border-2 border-slate-200 border-t-[var(--accent)]"
        animate={{ rotate: 360 }}
        transition={{ repeat: Infinity, duration: 0.9, ease: 'linear' }}
      />
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
    <div className="glass border-red-200 bg-[var(--fail-bg)] p-5">
      <div className="flex items-center gap-2 text-sm font-bold text-[var(--fail)]">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"
          strokeLinecap="round" className="h-4 w-4">
          <circle cx="12" cy="12" r="9" /><path d="M12 8v5M12 16.5v.01" />
        </svg>
        The store could not answer that.
      </div>
      <div className="mt-2 rounded-xl bg-white/70 p-3 font-mono text-xs leading-relaxed text-red-900/80">{msg}</div>
      <div className="mt-3 text-xs text-slate-500">
        No placeholder was substituted. Run <code className="rounded bg-white/80 px-1 py-0.5">python -m harness.record_runs</code> if fixtures are missing.
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
              <th key={i} className={`pb-2.5 text-[11px] font-bold uppercase tracking-[0.07em] text-slate-400 ${i === 0 ? 'text-left' : 'text-right'}`}>
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

export function Bar({ value, tone = 'accent' }: { value: number; tone?: 'accent' | 'fail' | 'pass' | 'warn' }) {
  const color = {
    accent: 'linear-gradient(90deg,#6a5cf0,#5546e8)',
    fail: 'linear-gradient(90deg,#f0656f,#dc3545)',
    pass: 'linear-gradient(90deg,#2fc196,#0d9d76)',
    warn: 'linear-gradient(90deg,#f5b53f,#d9820a)',
  }[tone]
  return (
    <div className="h-2 w-full overflow-hidden rounded-full bg-slate-100">
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
