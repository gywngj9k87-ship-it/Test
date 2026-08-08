'use client';

import { usePathname, useRouter, useSearchParams } from 'next/navigation';
import { createContext, Suspense, useContext, useMemo, type ReactNode } from 'react';
import type { Watchlist } from '@/lib/types';

/**
 * The global filter row — one row, above everything it scopes.
 *
 * Scope (All / Portfolio / Watchlists), watchlist, and range. The state lives
 * in the URL query string, not React state: that makes a scoped view
 * bookmarkable and the back button meaningful (the same principle TabNav
 * follows), and — crucially — lets the server components read the current
 * scope from their `searchParams` prop and re-fetch, which is the whole point
 * of the row. `useFilters()` reads the same query string for any client that
 * needs it. Pages that do not yet honour a filter say so via <FilterNote>
 * rather than silently ignoring it.
 */

export type Scope = 'all' | 'portfolio' | 'watchlists';
export type Range = '1m' | '3m' | '6m' | '1y';

const SCOPE_IDS: Scope[] = ['all', 'portfolio', 'watchlists'];
const RANGE_IDS: Range[] = ['1m', '3m', '6m', '1y'];

const DEFAULT_SCOPE: Scope = 'all';
const DEFAULT_RANGE: Range = '6m';

export interface FilterState {
  scope: Scope;
  watchlistId: string;
  range: Range;
}

interface FilterCtx extends FilterState {
  /** The watchlist id used when none is pinned in the URL. */
  defaultWatchlistId: string;
  setScope: (s: Scope) => void;
  setWatchlistId: (id: string) => void;
  setRange: (r: Range) => void;
}

const Ctx = createContext<FilterCtx>({
  scope: DEFAULT_SCOPE,
  watchlistId: 'all',
  range: DEFAULT_RANGE,
  defaultWatchlistId: 'all',
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

function one<T extends string>(v: string | null, allowed: T[], fallback: T): T {
  return v && (allowed as string[]).includes(v) ? (v as T) : fallback;
}

/**
 * Reads the filter state from the URL and writes changes back to it. Split out
 * from FilterProvider because useSearchParams() must sit inside a Suspense
 * boundary, or the static pages stop prerendering.
 */
function FilterRow({
  watchlists,
  children,
}: {
  watchlists: Watchlist[];
  children: ReactNode;
}) {
  const router = useRouter();
  const pathname = usePathname() ?? '/';
  const params = useSearchParams();

  const defaultWatchlistId = watchlists[0]?.id ?? 'all';
  const watchlistIds = watchlists.map((w) => w.id);

  const scope = one<Scope>(params.get('scope'), SCOPE_IDS, DEFAULT_SCOPE);
  const range = one<Range>(params.get('range'), RANGE_IDS, DEFAULT_RANGE);
  const watchlistId = one<string>(
    params.get('watchlist'),
    watchlistIds.length ? watchlistIds : [defaultWatchlistId],
    defaultWatchlistId,
  );

  function setParam(key: string, value: string, fallback: string) {
    const next = new URLSearchParams(Array.from(params.entries()));
    if (value === fallback) next.delete(key);
    else next.set(key, value);
    const qs = next.toString();
    router.push(qs ? `${pathname}?${qs}` : pathname, { scroll: false });
  }

  const value = useMemo<FilterCtx>(
    () => ({
      scope,
      watchlistId,
      range,
      defaultWatchlistId,
      setScope: (s) => setParam('scope', s, DEFAULT_SCOPE),
      setWatchlistId: (id) => setParam('watchlist', id, defaultWatchlistId),
      setRange: (r) => setParam('range', r, DEFAULT_RANGE),
    }),
    // params identity changes on every navigation, which is exactly when the
    // derived state and the setters must be rebuilt.
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [scope, watchlistId, range, defaultWatchlistId, params, pathname],
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
              onClick={() => value.setScope(s.id)}
            >
              {s.label}
            </button>
          ))}
        </div>

        <select
          aria-label="Watchlist"
          value={watchlistId}
          disabled={scope !== 'watchlists'}
          title={scope === 'watchlists' ? undefined : 'Select the Watchlists scope to choose one'}
          onChange={(e) => value.setWatchlistId(e.target.value)}
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
          onChange={(e) => value.setRange(e.target.value as Range)}
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

export function FilterProvider({
  watchlists,
  children,
}: {
  watchlists: Watchlist[];
  children: ReactNode;
}) {
  return (
    <Suspense fallback={<div className="filters" aria-hidden />}>
      <FilterRow watchlists={watchlists}>{children}</FilterRow>
    </Suspense>
  );
}

/**
 * The honesty affordance. A scoped view renders this to state, in words, which
 * filters it applies and which it does not — so a filter that a page ignores is
 * declared, never silently dropped. `honours` lists the filters this view acts
 * on; anything not listed is reported as not-yet-applied here.
 */
export function FilterNote({
  honours,
  active = true,
}: {
  honours: Array<'scope' | 'watchlist' | 'range'>;
  /** False when the honoured filters can't actually apply to what's shown —
   *  e.g. an offline snapshot the backend never scoped. Kept honest, not hidden. */
  active?: boolean;
}) {
  const { scope, watchlistId, range } = useFilters();
  const set = new Set(honours);

  const applied: string[] = [];
  if (set.has('scope')) applied.push(`scope = ${scope}`);
  if (set.has('watchlist') && scope === 'watchlists') applied.push(`watchlist = ${watchlistId}`);
  if (set.has('range')) applied.push(`range = ${range}`);

  const ignored: string[] = [];
  if (!set.has('scope')) ignored.push('scope');
  if (!set.has('range')) ignored.push('range');

  if (!applied.length && !ignored.length) return null;

  return (
    <p className="cap" style={{ margin: '0 0 10px' }}>
      {applied.length ? (
        active ? (
          <>
            Filtered by <b>{applied.join(', ')}</b>.{' '}
          </>
        ) : (
          <span style={{ color: 'var(--muted)' }}>
            {applied.join(', ')} selected, but this offline snapshot is unscoped —
            start the backend to apply it.{' '}
          </span>
        )
      ) : null}
      {ignored.length ? (
        <span style={{ color: 'var(--muted)' }}>
          This view does not scope by {ignored.join(' or ')} yet — the control still
          moves, but the numbers here are unaffected by it.
        </span>
      ) : null}
    </p>
  );
}
