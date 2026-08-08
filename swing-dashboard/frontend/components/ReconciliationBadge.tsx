import type { Reconciliation } from '@/lib/types';
import StatusChip from './StatusChip';
import { fmt, pct } from '@/lib/format';

/**
 * Surfaces a source disagreement instead of hiding it.
 *
 * models.py: "Every numeric that came from more than one source carries a
 * Reconciliation. Nothing silently picks a winner when sources disagree."
 * So a breached tolerance gets a warning chip and the two numbers side by side;
 * an agreeing pair gets a quiet ✓ chip you can hover for the detail.
 */

export interface ReconciliationBadgeProps {
  recs: Reconciliation[];
  /** Hide the chip entirely when everything agrees. */
  hideWhenClean?: boolean;
  /** Render the explanatory sentence next to the chip. */
  showNote?: boolean;
}

export default function ReconciliationBadge({
  recs,
  hideWhenClean = false,
  showNote = true,
}: ReconciliationBadgeProps) {
  if (!recs.length) return null;
  const breached = recs.filter((r) => r.breached);

  if (!breached.length) {
    if (hideWhenClean) return null;
    const fields = recs.map((r) => r.field).join(', ');
    return (
      <StatusChip
        tone="good"
        label="Sources agree"
        title={`IBKR and Yahoo agree within tolerance on: ${fields}`}
      />
    );
  }

  const first = breached[0];
  return (
    <span style={{ display: 'inline-flex', gap: 8, alignItems: 'baseline', flexWrap: 'wrap' }}>
      <StatusChip
        tone="warn"
        label={breached.length > 1 ? `Cross-check · ${breached.length}` : 'Cross-check'}
        title={`${first.field}: IBKR ${fmt(first.ibkr)} vs Yahoo ${fmt(first.yahoo)}`}
      />
      {showNote ? (
        <span style={{ color: 'var(--ink-2)', fontSize: 12.5 }}>
          {first.note ?? (
            <>
              <b style={{ color: 'var(--ink)' }}>{first.field}</b> — IBKR {fmt(first.ibkr)} vs Yahoo{' '}
              {fmt(first.yahoo)} ({pct(first.diff_pct)} apart, tolerance{' '}
              {fmt(first.tolerance_pct)}%).
            </>
          )}
        </span>
      ) : null}
    </span>
  );
}
