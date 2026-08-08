'use client';

import { createContext, useContext, useMemo, useState, type ReactNode } from 'react';
import type { Watchlist } from '@/lib/types';

/**
 * The global filter row — one row, above everything it scopes.
 *
 * Scope (All / Portfolio / Watchlists), watchlist, and range. Kept in context
 * so pages can read the current scope without prop-drilling through the layout.
 * The mockup's filter row is decorative; this one is wired, and pages that do
 * not yet honour a filter say so rather than silently ignoring it.
 */

export type Scope = 'all' | 'portfolio' | 'watchlists';
export type Range = '1m' | '3m' | '6m' | '1y';

export interface FilterState {
  scope: Scope;
  watchlistId: string;
  range: Range;
}

interface FilterCtx extends FilterState {
  setScope: (s: Scope) => void;
  setWatchlistId: (id: string) => void;
  setRange: (r: Range) => void;
}

const Ctx = createContext<FilterCtx>({
  scope: 'all',
  watchlistId: 'all',
  range: '6m',
  setScope: () => {},
  setWatchlistId: () => {},
  setRange: () => {},
});

export function useFilters() {
  return useContext(Ctx);
}

const SCOPES: Array<{ id: Scope; label: string }> = [
  { id: 'all', label: 'All' },
  { id: 'portfolio', label: 'Portfolio' },
  { id: 'watchlists', label: 'Watchlists' },
];

const RANGES: Array<{ id: Range; label: string }> = [
  { id: '6m', label: '6 months' },
  { id: '1m', label: '1 month' },
  { id: '3m', label: '3 months' },
  { id: '1y', label: '1 year' },
];

export function FilterProvider({
  watchlists,
  children,
}: {
  watchlists: Watchlist[];
  children: ReactNode;
}) {
  const [scope, setScope] = useState<Scope>('all');
  const [watchlistId, setWatchlistId] = useState<string>(watchlists[0]?.id ?? 'all');
  const [range, setRange] = useState<Range>('6m');

  const value = useMemo(
    () => ({ scope, watchlistId, range, setScope, setWatchlistId, setRange }),
    [scope, watchlistId, range],
  );

  return (
    <Ctx.Provider value={value}>
      <div className="filters">
        <div className="seg" role="tablist" aria-label="Scope">
          {SCOPES.map((s) => (
            <button
              key={s.id}
              role="tab"
              aria-selected={scope === s.id}
              onClick={() => setScope(s.id)}
            >
              {s.label}
            </button>
          ))}
        </div>

        <select
          aria-label="Watchlist"
          value={watchlistId}
          onChange={(e) => setWatchlistId(e.target.value)}
        >
          {watchlists.map((w) => (
            <option key={w.id} value={w.id}>
              {w.name} ({w.count})
            </option>
          ))}
        </select>

        <select
          aria-label="Range"
          value={range}
          onChange={(e) => setRange(e.target.value as Range)}
        >
          {RANGES.map((r) => (
            <option key={r.id} value={r.id}>
              {r.label}
            </option>
          ))}
        </select>
      </div>
      {children}
    </Ctx.Provider>
  );
}
