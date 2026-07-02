// Always present for multi-series charts (identity must never be colour-alone).
export default function Legend({ keys }) {
  if (!keys || keys.length < 2) return null
  return (
    <div className="legend">
      {keys.map((k) => (
        <span className="legend__item" key={k.key}>
          <span className="legend__swatch" style={{ background: `var(--${k.series})` }} />
          {k.label}
        </span>
      ))}
    </div>
  )
}
