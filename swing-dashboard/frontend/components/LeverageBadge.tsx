import type { Instrument } from '@/lib/types';

/**
 * Ticker + exchange + leverage factor, together, everywhere.
 *
 * The reason is in spec v0.3 §2c: `SOXL` is a 4× LSE ETP *and* a 3× US ETF,
 * and `MAGS` is a 1× US ETF *and* a −3× LSE inverse. Anyone typing a symbol
 * instead of selecting a contract could end up 3× short the position they
 * meant to buy 1× long. So a bare symbol is never rendered on its own — the
 * exchange badge is not decoration, it is half the identity.
 */

export interface LeverageBadgeProps {
  symbol: string;
  exchange: string;
  /** 5, 4, 3, -3 … null for an ordinary instrument. */
  leverage?: number | null;
  /** Show the conid too — used in the collision table. */
  conid?: number | null;
}

export default function LeverageBadge({
  symbol,
  exchange,
  leverage,
  conid,
}: LeverageBadgeProps) {
  const inverse = leverage != null && leverage < 0;
  return (
    <span style={{ whiteSpace: 'nowrap' }}>
      <span className="tk">{symbol}</span>
      <span className="ex" title={conid ? `Contract ${conid} · ${exchange}` : exchange}>
        {exchange}
      </span>
      {leverage != null ? (
        <span className="lv" style={inverse ? { color: 'var(--crit)' } : undefined}>
          {inverse ? `${Math.abs(leverage)}× SHORT` : `${leverage}×`}
        </span>
      ) : null}
    </span>
  );
}

/** Convenience wrapper when you already hold an Instrument. */
export function InstrumentBadge({ instrument }: { instrument: Instrument }) {
  return (
    <LeverageBadge
      symbol={instrument.symbol}
      exchange={instrument.exchange}
      leverage={instrument.leverage}
      conid={instrument.conid}
    />
  );
}
