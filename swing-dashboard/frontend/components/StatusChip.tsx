import type { ReactNode } from 'react';
import type { Severity } from '@/lib/types';

/**
 * Status, always as icon + label. NEVER colour alone.
 *
 * The four reserved status colours (good / warn / serious / crit) mean status
 * and only status. If you need a fifth encoding, it is not a status — use a
 * series colour or an ink token.
 */

export type ChipTone = 'good' | 'warn' | 'serious' | 'crit' | 'neutral';

/** Maps the API's Severity enum onto the chip tones the CSS declares. */
export function toneFromSeverity(s: Severity): ChipTone {
  switch (s) {
    case 'good':
      return 'good';
    case 'warning':
      return 'warn';
    case 'serious':
      return 'serious';
    case 'critical':
      return 'crit';
    default:
      return 'neutral';
  }
}

/** The default glyph for a tone, used when the caller has nothing better. */
export const TONE_ICON: Record<ChipTone, string> = {
  good: '✓',
  warn: '◆',
  serious: '⚠',
  crit: '⛔',
  neutral: '—',
};

export interface StatusChipProps {
  tone: ChipTone;
  /** Overrides TONE_ICON. Keep it a single glyph. */
  icon?: string;
  /** Required — a chip with no label is a colour, and a colour is not a message. */
  label: ReactNode;
  title?: string;
}

export default function StatusChip({ tone, icon, label, title }: StatusChipProps) {
  return (
    <span className={`chip ${tone}`} title={title}>
      <span aria-hidden>{icon ?? TONE_ICON[tone]}</span>
      <span>{label}</span>
    </span>
  );
}
