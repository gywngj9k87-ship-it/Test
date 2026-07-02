import ThemeToggle from './ThemeToggle.jsx'

const INTERVALS = [
  { label: 'Off', value: 0 },
  { label: 'Every 1 min', value: 60 },
  { label: 'Every 5 min', value: 300 },
  { label: 'Every 15 min', value: 900 },
  { label: 'Every 30 min', value: 1800 },
]

export default function RefreshControls({
  onRefresh,
  isRefreshing,
  autoOn,
  intervalSeconds,
  onIntervalChange,
}) {
  return (
    <div className="controls">
      <label className="toggle" title="Automatically refresh on an interval">
        <input
          type="checkbox"
          checked={autoOn}
          onChange={(e) => onIntervalChange(e.target.checked ? intervalSeconds || 300 : 0)}
        />
        Auto
      </label>

      <select
        className="select"
        value={autoOn ? intervalSeconds : 0}
        onChange={(e) => onIntervalChange(Number(e.target.value))}
        aria-label="Auto-refresh interval"
      >
        {INTERVALS.map((i) => (
          <option key={i.value} value={i.value}>
            {i.label}
          </option>
        ))}
      </select>

      <ThemeToggle />

      <button className="btn btn--primary" onClick={onRefresh} disabled={isRefreshing}>
        {isRefreshing ? <span className="btn__spin" /> : '↻'}
        {isRefreshing ? 'Refreshing…' : 'Refresh'}
      </button>
    </div>
  )
}
