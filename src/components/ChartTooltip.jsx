import { fmtNumber } from '../lib/format.js'

// Shared Recharts tooltip. Reads a `unit` and `decimals` off the payload's
// chart config passed through via the `labelFormatter`/`formatter` props.
export default function ChartTooltip({ active, payload, label, unit, decimals = 1, xLabel }) {
  if (!active || !payload || payload.length === 0) return null
  return (
    <div className="tooltip" role="status">
      <div className="tooltip__label">
        {xLabel ? `${xLabel}: ` : ''}
        {label}
      </div>
      {payload.map((p) => (
        <div className="tooltip__row" key={p.dataKey}>
          <span className="tooltip__key">
            <span
              className="legend__swatch"
              style={{ background: p.color || p.stroke || p.fill }}
            />
            {p.name}
          </span>
          <span className="tooltip__val">
            {fmtNumber(p.value, decimals)}
            {unit ? ` ${unit}` : ''}
          </span>
        </div>
      ))}
    </div>
  )
}
