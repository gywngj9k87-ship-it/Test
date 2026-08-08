import type { ReactNode } from 'react';

export type CardBadge = 'live' | 'mock' | 'mockup' | null;

export interface CardProps {
  title?: ReactNode;
  /** The one-line explanation under the title. Never optional in practice. */
  caption?: ReactNode;
  /** ● IBKR when the data is live, "Placeholder" when it is not. Never lie here. */
  badge?: CardBadge;
  badgeLabel?: string;
  /** Right-aligned controls in the card header, e.g. a TableView toggle. */
  actions?: ReactNode;
  className?: string;
  children?: ReactNode;
}

const BADGE_TEXT: Record<Exclude<CardBadge, null>, string> = {
  live: '● IBKR',
  mock: 'Placeholder',
  mockup: '◆ Mockup',
};

export default function Card({
  title,
  caption,
  badge = null,
  badgeLabel,
  actions,
  className,
  children,
}: CardProps) {
  return (
    <section className={className ? `card ${className}` : 'card'}>
      {(title || badge || actions) && (
        <div className="chead">
          {title ? <h2>{title}</h2> : null}
          {badge ? <span className={`pill ${badge}`}>{badgeLabel ?? BADGE_TEXT[badge]}</span> : null}
          {actions ? (
            <>
              <div className="spacer" />
              {actions}
            </>
          ) : null}
        </div>
      )}
      {caption ? <p className="cap">{caption}</p> : null}
      {children}
    </section>
  );
}
