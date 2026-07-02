/*
 * Live data fetchers — best-effort, per-dataset, with graceful fallback.
 *
 * Each fetcher pulls from a public, key-free source and normalises the result
 * into the same { year, value } (or multi-key) shape the snapshots use. Every
 * fetch is wrapped in a timeout and try/catch: on ANY failure (network, CORS,
 * empty payload, unexpected shape) the caller keeps the bundled snapshot and
 * marks the dataset "cached". Datasets with no fetcher are "reference" —
 * the snapshot IS the source.
 *
 * Live availability depends on the browser being able to reach each host and
 * on that host's CORS policy; the platform is fully functional either way.
 */

import { parseCsv, toNumber } from './csv.js'

const DEFAULT_TIMEOUT = 12000

async function fetchText(url, timeout = DEFAULT_TIMEOUT) {
  const ctrl = new AbortController()
  const t = setTimeout(() => ctrl.abort(), timeout)
  try {
    const res = await fetch(url, { signal: ctrl.signal, mode: 'cors' })
    if (!res.ok) throw new Error(`HTTP ${res.status}`)
    return await res.text()
  } finally {
    clearTimeout(t)
  }
}

async function fetchJson(url, timeout = DEFAULT_TIMEOUT) {
  const ctrl = new AbortController()
  const t = setTimeout(() => ctrl.abort(), timeout)
  try {
    const res = await fetch(url, { signal: ctrl.signal, mode: 'cors' })
    if (!res.ok) throw new Error(`HTTP ${res.status}`)
    return await res.json()
  } finally {
    clearTimeout(t)
  }
}

function ensureNonEmpty(series) {
  if (!Array.isArray(series) || series.length < 3) {
    throw new Error('insufficient data returned')
  }
  return series
}

/* ---------- NOAA Global Monitoring Laboratory (CO₂, CH₄) ---------- *
 * These CSVs carry a block of '#'-prefixed comment lines and then bare
 * numeric rows: `year,mean,unc`. We parse positionally.               */

function parseNoaaAnnual(text) {
  const rows = text
    .split(/\r?\n/)
    .map((l) => l.trim())
    .filter((l) => l !== '' && !l.startsWith('#') && !/^[a-zA-Z]/.test(l))
  return rows
    .map((line) => {
      const cells = line.split(/[,\s]+/)
      const year = toNumber(cells[0])
      const value = toNumber(cells[1])
      return year && value ? { year, value } : null
    })
    .filter(Boolean)
}

async function fetchCo2Concentration() {
  const text = await fetchText(
    'https://gml.noaa.gov/webdata/ccgg/trends/co2/co2_annmean_mlo.csv',
  )
  return ensureNonEmpty(parseNoaaAnnual(text))
}

async function fetchMethane() {
  const text = await fetchText(
    'https://gml.noaa.gov/webdata/ccgg/trends/ch4/ch4_annmean_gl.csv',
  )
  return ensureNonEmpty(parseNoaaAnnual(text))
}

/* ---------- World Bank Open Data (emissions, renewables) ---------- *
 * JSON API, CORS-enabled, no key. Response is [meta, [ {date,value}… ]]. */

async function fetchWorldBank(indicator, { transform = (v) => v } = {}) {
  const url = `https://api.worldbank.org/v2/country/WLD/indicator/${indicator}?format=json&per_page=200`
  const json = await fetchJson(url)
  if (!Array.isArray(json) || !Array.isArray(json[1])) throw new Error('bad shape')
  const series = json[1]
    .map((row) => {
      const year = toNumber(row.date)
      const raw = row.value === null ? null : toNumber(row.value)
      return year && raw !== null ? { year, value: transform(raw) } : null
    })
    .filter(Boolean)
    .sort((a, b) => a.year - b.year)
  return ensureNonEmpty(series)
}

// EDGAR-based total CO₂ (Mt) → Gt.
async function fetchCo2Emissions() {
  return fetchWorldBank('EN.GHG.CO2.MT.CE.AR5', { transform: (v) => v / 1000 })
}

/* ---------- Our World in Data grapher CSV ---------- *
 * `https://ourworldindata.org/grapher/<slug>.csv` returns focused, CORS-
 * enabled CSV with columns Entity,Code,Year,<value>. We keep one entity.   */

async function fetchOwidGrapher(slug, { entity = 'World' } = {}) {
  const url = `https://ourworldindata.org/grapher/${slug}.csv?csvType=filtered&useColumnShortNames=true`
  const text = await fetchText(url)
  const rows = parseCsv(text)
  if (rows.length === 0) throw new Error('empty grapher csv')
  const headers = Object.keys(rows[0])
  const valueKey = headers[headers.length - 1] // last column is the metric
  const series = rows
    .filter((r) => r.Entity === entity || r.entity === entity)
    .map((r) => {
      const year = toNumber(r.Year || r.year)
      const value = toNumber(r[valueKey])
      return year && value !== null ? { year, value } : null
    })
    .filter(Boolean)
    .sort((a, b) => a.year - b.year)
  return ensureNonEmpty(series)
}

async function fetchGlobalTemperature() {
  // Global average temperature anomaly relative to 1961–1990.
  return fetchOwidGrapher('temperature-anomaly', { entity: 'Global' })
}

/* ---------- Registry ---------- *
 * Only datasets listed here attempt a live pull. Everything else is
 * treated as a stable "reference" snapshot.                           */

export const FETCHERS = {
  'global-temperature': fetchGlobalTemperature,
  'co2-concentration': fetchCo2Concentration,
  'methane-concentration': fetchMethane,
  'co2-emissions': fetchCo2Emissions,
}

export function hasLiveSource(id) {
  return Boolean(FETCHERS[id])
}

// Attempt a live pull for one dataset. Never throws.
export async function refreshDataset(id) {
  const fetcher = FETCHERS[id]
  if (!fetcher) return { status: 'reference', series: null, error: null }
  try {
    const series = await fetcher()
    return { status: 'live', series, error: null }
  } catch (err) {
    return { status: 'cached', series: null, error: err?.message || String(err) }
  }
}
