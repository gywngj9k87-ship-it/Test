import type { ReactNode } from 'react';
import { barWidth } from '@/lib/format';

export interface ScoreBarProps {
  label: ReactNode;
  /** Right-hand annotation, typically the weight ("30%"). */
  sublabel?: ReactNode;
  /** 0-100. */
  value: number;
  /** Printed at the right. Defaults to the rounded value. */
  display?: ReactNode;
  /** Bar fill; defaults to --s1. Use a series colour, never a status colour. */
  color?: string;
  emphasis?: boolean;
  style?: React.CSSProperties;
}

/**
 * One row of a score breakdown. The composite is never shown without these —
 * "Never a black box" is a contract-level rule (see SetupScore in models.py).
 */
export default function ScoreBar({
  label,
  sublabel,
  value,
  display,
  color,
  emphasis = false,
  style,
}: ScoreBarProps) {
  return (
    <div
      className="scorerow"
      style={emphasis ? { borderTop: '1px solid var(--axis)', marginTop: 6, ...style } : style}
    >
      <span>
        {emphasis ? <b>{label}</b> : label}
        {sublabel ? <span style={{ color: 'var(--muted)' }}> {sublabel}</span> : null}
      </span>
      <span className="track">
        <span
          className="fill"
          style={{ width: `${barWidth(value)}%`, background: color ?? 'var(--s1)' }}
        />
      </span>
      <span className="n">{emphasis ? <b>{display ?? Math.round(value)}</b> : display ?? Math.round(value)}</span>
    </div>
  );
}
