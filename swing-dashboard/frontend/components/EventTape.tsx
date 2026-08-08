import type { MarketEvent } from '@/lib/types';
import StatusChip, { toneFromSeverity } from './StatusChip';
import { clockTime, pct } from '@/lib/format';

/**
 * The tape. Every event is paired with its price reaction — that pairing is
 * the whole point (see MarketEvent in models.py). An event with no reaction
 * carries a label instead ("Calendar", "Flagged") so the column is never blank
 * and never fabricated.
 */

export interface EventTapeProps {
  events: MarketEvent[];
}

export default function EventTape({ events }: EventTapeProps) {
  return (
    <ul className="tape">
      {events.map((e, i) => (
        <li key={`${e.ts}-${e.symbol ?? 'macro'}-${i}`}>
          <span className="ts">{clockTime(e.ts)}</span>
          <span>
            <span className="ttl">
              {e.symbol ? `${e.symbol} · ` : ''}
              {e.title}
            </span>
            <span className="why">{e.detail}</span>
          </span>
          <span className="rx">
            <StatusChip
              tone={toneFromSeverity(e.severity)}
              label={e.reaction_pct != null ? pct(e.reaction_pct, 1) : e.reaction_label ?? '—'}
              title={e.moved_price ? 'Moved the price' : 'No price reaction yet'}
            />
          </span>
        </li>
      ))}
    </ul>
  );
}

/** The risk-flag list reuses the tape grid — same shape, different payload. */
export function FlagTape({
  flags,
}: {
  flags: Array<{ severity: string; icon: string; title: string; detail: string }>;
}) {
  return (
    <ul className="tape">
      {flags.map((f) => (
        <li key={f.title}>
          {/* The glyph is the non-colour channel; the flag title beside it is
              the label. The severity word is there for screen readers. */}
          <span className="ts">
            <StatusChip
              tone={toneFromSeverity(f.severity as never)}
              icon={f.icon}
              label={<span className="sr-only">{f.severity}</span>}
              title={f.severity}
            />
          </span>
          <span>
            <span className="ttl">{f.title}</span>
            <span className="why">{f.detail}</span>
          </span>
          <span />
        </li>
      ))}
    </ul>
  );
}
