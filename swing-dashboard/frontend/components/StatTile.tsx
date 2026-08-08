import type { ReactNode } from 'react';

export interface StatTileProps {
  label: ReactNode;
  value: ReactNode;
  /** The line under the number: what it means, what it's measured against. */
  detail?: ReactNode;
  /** 'up' | 'down' | '' — direction, from lib/format's cls(). Not status. */
  valueClass?: string;
  badge?: 'live' | 'mock' | null;
  /** Overrides the default pill text — see sourceBadge() in lib/api.ts. */
  badgeLabel?: string;
}

export default function StatTile({
  label,
  value,
  detail,
  valueClass,
  badge = null,
  badgeLabel,
}: StatTileProps) {
  return (
    <div className="tile">
      <div className="lbl">
        {label}
        {badge ? <span className={`pill ${badge}`} style={{ marginLeft: 6 }}>
          {badgeLabel ?? (badge === 'live' ? '● IBKR' : 'Placeholder')}
        </span> : null}
      </div>
      <div className={valueClass ? `val ${valueClass}` : 'val'}>{value}</div>
      {detail ? <div className="del">{detail}</div> : null}
    </div>
  );
}
