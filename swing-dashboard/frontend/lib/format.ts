/**
 * Formatting helpers — ported from the approved mockup.
 *
 * Rules that travel with these functions:
 *   * Negatives use a real minus sign (U+2212), not a hyphen. It aligns in
 *     tabular-nums and it reads as a sign, not as a dash.
 *   * `cls()` returns 'up' / 'down' / '' — the up/down ink tokens. These are
 *     direction, not status. Status is StatusChip, and status always carries an
 *     icon plus a label.
 *   * Everything numeric renders through `fmt` so column alignment holds.
 */

const MINUS = '−';

/** Fixed-decimal, thousands-separated. `fmt(1234.5)` → "1,234.50". */
export function fmt(n: number | null | undefined, d = 2): string {
  if (n == null || Number.isNaN(n)) return '—';
  return n.toLocaleString('en-US', {
    minimumFractionDigits: d,
    maximumFractionDigits: d,
  });
}

/** Currency. `usd(-12.3)` → "−$12.30". */
export function usd(n: number | null | undefined, d = 2): string {
  if (n == null || Number.isNaN(n)) return '—';
  return (n < 0 ? `${MINUS}$` : '$') + fmt(Math.abs(n), d);
}

/** Signed percent. `pct(4.1)` → "+4.10%". */
export function pct(n: number | null | undefined, d = 2): string {
  if (n == null || Number.isNaN(n)) return '—';
  const sign = n > 0 ? '+' : n < 0 ? MINUS : '';
  return sign + fmt(Math.abs(n), d) + '%';
}

/** Direction class for a number: 'up' | 'down' | ''. */
export function cls(n: number | null | undefined): string {
  if (n == null || Number.isNaN(n)) return '';
  return n > 0 ? 'up' : n < 0 ? 'down' : '';
}

/** ▲ / ▼ / — . Always paired with the number, never used alone. */
export function arrow(n: number | null | undefined): string {
  if (n == null || Number.isNaN(n)) return '—';
  return n > 0 ? '▲' : n < 0 ? '▼' : '—';
}

/** Compact large numbers for volume columns. `compact(4155945)` → "4.16M". */
export function compact(n: number | null | undefined, d = 2): string {
  if (n == null || Number.isNaN(n)) return '—';
  const a = Math.abs(n);
  const sign = n < 0 ? MINUS : '';
  if (a >= 1e12) return `${sign}${fmt(a / 1e12, d)}T`;
  if (a >= 1e9) return `${sign}${fmt(a / 1e9, d)}B`;
  if (a >= 1e6) return `${sign}${fmt(a / 1e6, d)}M`;
  if (a >= 1e3) return `${sign}${fmt(a / 1e3, d)}K`;
  return sign + fmt(a, 0);
}

const MONTHS = [
  'Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun',
  'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec',
];

/** "2026-08-05" → "Aug 5". The axis-label form used throughout the mockup. */
export function shortDate(iso: string): string {
  const parts = iso.split('-');
  if (parts.length < 3) return iso;
  const m = Number(parts[1]);
  const d = Number(parts[2]);
  if (!m || !d) return iso;
  return `${MONTHS[m - 1]} ${d}`;
}

/** "2026-08-05" → "5 Aug 2026". */
export function longDate(iso: string): string {
  const parts = iso.split('-');
  if (parts.length < 3) return iso;
  const m = Number(parts[1]);
  const d = Number(parts[2]);
  if (!m || !d) return iso;
  return `${d} ${MONTHS[m - 1]} ${parts[0]}`;
}

/** ISO datetime → "08:31". Used by the event tape. */
export function clockTime(iso: string): string {
  const t = iso.includes('T') ? iso.split('T')[1] : iso;
  return t.slice(0, 5);
}

/** Percentage-points, unsigned decimal + " pp". */
export function pp(n: number | null | undefined, d = 1): string {
  if (n == null || Number.isNaN(n)) return '—';
  const sign = n > 0 ? '+' : n < 0 ? MINUS : '';
  return `${sign}${fmt(Math.abs(n), d)} pp`;
}

/** Clamp to a 0-100 bar width. */
export function barWidth(n: number | null | undefined): number {
  if (n == null || Number.isNaN(n)) return 0;
  return Math.min(100, Math.max(0, n));
}
