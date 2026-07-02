// Formatting helpers shared across panels.

export function fmtNumber(value, digits = 1) {
  if (value === null || value === undefined || Number.isNaN(value)) return '—'
  return value.toLocaleString(undefined, {
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  })
}

export function fmtSigned(value, digits = 2) {
  if (value === null || value === undefined || Number.isNaN(value)) return '—'
  const s = fmtNumber(Math.abs(value), digits)
  return `${value >= 0 ? '+' : '−'}${s}`
}

// Compact currency-ish for large magnitudes ($bn / $tn).
export function fmtBig(value) {
  if (value === null || value === undefined || Number.isNaN(value)) return '—'
  if (Math.abs(value) >= 1000) return `${fmtNumber(value / 1000, 2)}T`
  return `${fmtNumber(value, 0)}B`
}

// Latest and previous points from a single-value series (keyed by `year`).
export function seriesEndpoints(series, valueKey = 'value') {
  if (!series || series.length === 0) return { latest: null, prev: null }
  const latest = series[series.length - 1]
  const prev = series.length > 1 ? series[series.length - 2] : null
  return {
    latest: { x: latest.year, y: latest[valueKey] },
    prev: prev ? { x: prev.year, y: prev[valueKey] } : null,
  }
}

// Direction/label for a delta, respecting whether "up" is good or bad.
export function deltaMeta(delta, { upIsGood = false } = {}) {
  if (delta === null || delta === undefined || Number.isNaN(delta) || delta === 0) {
    return { cls: 'stat__delta--neutral', arrow: '→' }
  }
  const up = delta > 0
  const good = up === upIsGood
  return {
    cls: good ? 'stat__delta--down' : 'stat__delta--up', // reuse good/bad color classes
    arrow: up ? '▲' : '▼',
  }
}

export function timeAgo(date) {
  if (!date) return 'never'
  const secs = Math.round((Date.now() - date.getTime()) / 1000)
  if (secs < 5) return 'just now'
  if (secs < 60) return `${secs}s ago`
  const mins = Math.round(secs / 60)
  if (mins < 60) return `${mins} min ago`
  const hrs = Math.round(mins / 60)
  if (hrs < 24) return `${hrs} h ago`
  return date.toLocaleDateString()
}

export function fmtClock(date) {
  if (!date) return '—'
  return date.toLocaleTimeString(undefined, { hour: '2-digit', minute: '2-digit' })
}
