import type { CSSProperties } from 'react';

export interface LegendItem {
  /** A series colour token: var(--s1) | var(--s2) | var(--s3). */
  color: string;
  label: string;
}

export interface LegendProps {
  items: LegendItem[];
  style?: CSSProperties;
}

/**
 * A legend is ALWAYS present for two or more series (rule 2 in LineChart.tsx).
 * The swatch carries the colour; the label carries the meaning. Never one
 * without the other.
 */
export default function Legend({ items, style }: LegendProps) {
  return (
    <div className="legend" style={style}>
      {items.map((it) => (
        <span key={it.label}>
          <i className="sw" style={{ background: it.color }} aria-hidden />
          {it.label}
        </span>
      ))}
    </div>
  );
}
