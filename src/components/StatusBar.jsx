import { timeAgo } from '../lib/format.js'

/*
 * Summarises data provenance: how many panels are live vs cached/reference,
 * and when the last refresh completed.
 */
export default function StatusBar({ datasets, lastUpdated, isRefreshing, snapshotAsOf }) {
  const all = Object.values(datasets)
  const live = all.filter((d) => d.status === 'live').length
  const cached = all.filter((d) => d.status === 'cached').length
  const reference = all.filter((d) => d.status === 'reference' || d.status === 'idle').length

  return (
    <div className="statusbar">
      {isRefreshing ? (
        <span className="statuspill">
          <span className="dot dot--loading" /> Fetching live data…
        </span>
      ) : (
        <span className="statuspill">
          <span className="dot dot--live" /> {live} live
        </span>
      )}
      {cached > 0 && (
        <span className="statuspill">
          <span className="dot dot--cached" /> {cached} cached
        </span>
      )}
      {reference > 0 && (
        <span className="statuspill">
          <span className="dot dot--cached" /> {reference} reference
        </span>
      )}
      <span style={{ marginLeft: 'auto' }}>
        {isRefreshing
          ? 'Updating…'
          : lastUpdated
            ? `Updated ${timeAgo(lastUpdated)}`
            : 'Loading…'}
        {' · '}
        <span title="Bundled snapshot date">snapshot {snapshotAsOf}</span>
      </span>
    </div>
  )
}
