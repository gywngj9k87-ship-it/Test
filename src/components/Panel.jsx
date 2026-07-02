import TrendChart from './TrendChart.jsx'
import Legend from './Legend.jsx'
import { fmtNumber, fmtSigned, deltaMeta } from '../lib/format.js'

const STATUS_BADGE = {
  live: { cls: 'dot--live', label: 'Live' },
  cached: { cls: 'dot--cached', label: 'Cached' },
  reference: { cls: 'dot--cached', label: 'Reference' },
  idle: { cls: 'dot--loading', label: 'Loading…' },
}

// Compute a compact headline (latest value + change) for time-series panels.
function headline(dataset, decimals, upIsGood) {
  const s = dataset.series
  if (!s || !s.length || s[0].value === undefined) return null
  const latest = s[s.length - 1]
  const prev = s.length > 1 ? s[s.length - 2] : null
  const delta = prev ? latest.value - prev.value : null
  const dm = deltaMeta(delta, { upIsGood })
  return { latest, delta, dm }
}

export default function Panel({ dataset, config }) {
  const { form, decimals = 1, upIsGood = false, logY = false, span = 6 } = config
  const badge = STATUS_BADGE[dataset.status] || STATUS_BADGE.reference
  const isCategorical = form === 'hbar'
  const hl = isCategorical ? null : headline(dataset, decimals, upIsGood)

  return (
    <section className={`panel col-${span}`} aria-label={dataset.title}>
      <header className="panel__head">
        <div>
          <h3 className="panel__title">{dataset.title}</h3>
          <p className="panel__subtitle">{dataset.baseline}</p>
        </div>
        <span className="panel__badge" title={dataset.error || badge.label}>
          <span className={`dot ${badge.cls}`} />
          {badge.label}
        </span>
      </header>

      {hl && (
        <div style={{ display: 'flex', alignItems: 'baseline', gap: 12, marginBottom: 4 }}>
          <span style={{ fontSize: 26, fontWeight: 700, letterSpacing: '-0.03em' }}>
            {fmtNumber(hl.latest.value, decimals)}
            <span className="stat__unit">{dataset.unit}</span>
          </span>
          {hl.delta !== null && (
            <span className={`stat__delta ${hl.dm.cls}`}>
              {hl.dm.arrow} {fmtSigned(hl.delta, decimals)} vs {hl.latest.year ? hl.latest.year - yearGap(dataset) : 'prev'}
            </span>
          )}
        </div>
      )}

      <div className="chart-wrap">
        <TrendChart
          form={form}
          data={dataset.series}
          keys={dataset.keys}
          unit={dataset.unit}
          decimals={decimals}
          logY={logY}
        />
      </div>

      {dataset.keys && dataset.keys.length >= 2 && <Legend keys={dataset.keys} />}

      {dataset.note && <p className="note">{dataset.note}</p>}

      <p className="source-line">
        Source:{' '}
        <a href={dataset.sourceUrl} target="_blank" rel="noreferrer">
          {dataset.sourceName}
        </a>
        {dataset.status === 'cached' && ' · live fetch unavailable, showing cached'}
      </p>
    </section>
  )
}

// Gap between the last two x points (for a truthful "vs <year>" label).
function yearGap(dataset) {
  const s = dataset.series
  if (!s || s.length < 2 || !s[s.length - 1].year) return 1
  return s[s.length - 1].year - s[s.length - 2].year
}
