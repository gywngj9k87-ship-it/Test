import { fmtNumber, fmtSigned, deltaMeta } from '../lib/format.js'

/*
 * Headline number for one dataset. Shows the latest value, the change vs the
 * previous data point (coloured by whether "up" is good or bad for that
 * metric), and a small status marker (live / cached / reference).
 */
export default function StatTile({ dataset, upIsGood = false, decimals = 1, deriveKey }) {
  const { series, unit, title, status } = dataset

  let latestPoint = null
  let prevPoint = null
  const valueKey = deriveKey || 'value'

  if (series && series.length) {
    const withValue = series.filter((d) => d[valueKey] !== undefined && d[valueKey] !== null)
    if (withValue.length) {
      latestPoint = withValue[withValue.length - 1]
      prevPoint = withValue.length > 1 ? withValue[withValue.length - 2] : null
    }
  }

  const latest = latestPoint ? latestPoint[valueKey] : null
  const prev = prevPoint ? prevPoint[valueKey] : null
  const delta = latest !== null && prev !== null ? latest - prev : null
  const dm = deltaMeta(delta, { upIsGood })

  const statusInfo = {
    live: { cls: 'dot--live', label: 'Live' },
    cached: { cls: 'dot--cached', label: 'Cached' },
    reference: { cls: 'dot--cached', label: 'Reference' },
    idle: { cls: 'dot--loading', label: 'Loading' },
  }[status] || { cls: 'dot--cached', label: 'Reference' }

  const label = deriveKey
    ? `${title} — ${dataset.keys?.find((k) => k.key === deriveKey)?.label || deriveKey}`
    : title

  return (
    <div className="stat">
      <div className="stat__label">
        <span className={`dot ${statusInfo.cls}`} title={statusInfo.label} />
        {label}
      </div>
      <div className="stat__value">
        {fmtNumber(latest, decimals)}
        <span className="stat__unit">{unit}</span>
      </div>
      {delta !== null ? (
        <span className={`stat__delta ${dm.cls}`}>
          {dm.arrow} {fmtSigned(delta, decimals)} vs {prevPoint.year ?? 'prev'}
        </span>
      ) : (
        <span className="stat__delta stat__delta--neutral">—</span>
      )}
      {latestPoint?.year && <div className="stat__foot">Latest: {latestPoint.year}</div>}
    </div>
  )
}
