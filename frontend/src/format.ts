export const usd = (v: number | null | undefined, dp = 2): string =>
  v === null || v === undefined ? '—' : `$${v.toLocaleString('en-US', {
    minimumFractionDigits: dp, maximumFractionDigits: dp,
  })}`

export const usdSmart = (v: number | null | undefined): string => {
  if (v === null || v === undefined) return '—'
  if (Math.abs(v) >= 100) return usd(v, 0)
  if (Math.abs(v) >= 1) return usd(v, 2)
  return usd(v, 3)
}

export const pct = (v: number | null | undefined, dp = 1): string =>
  v === null || v === undefined ? '—' : `${v.toFixed(dp)}%`

export const signedPct = (v: number | null | undefined, dp = 1): string =>
  v === null || v === undefined ? '—' : `${v > 0 ? '+' : ''}${v.toFixed(dp)}%`

export const num = (v: number | null | undefined, dp = 3): string =>
  v === null || v === undefined ? '—' : v.toFixed(dp)

export const ms = (v: number | null | undefined): string => {
  if (v === null || v === undefined) return '—'
  return v >= 1000 ? `${(v / 1000).toFixed(1)}s` : `${Math.round(v)}ms`
}

export const compactTokens = (v: number): string =>
  v >= 1e9 ? `${(v / 1e9).toFixed(2)}B` : v >= 1e6 ? `${(v / 1e6).toFixed(1)}M`
    : v >= 1e3 ? `${(v / 1e3).toFixed(0)}k` : `${v}`

export const shortDate = (iso: string): string =>
  new Date(iso).toLocaleDateString('en-US', { month: 'short', day: 'numeric' })
