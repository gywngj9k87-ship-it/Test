/**
 * Typed fetch client for the FastAPI service.
 *
 * Base URL comes from NEXT_PUBLIC_API_URL, default http://localhost:8000.
 *
 * Every call returns an `ApiResult<T>`, not a bare `T`. When the backend is
 * unreachable the client falls back to lib/mock.ts and says so in
 * `result.source`. It never throws at the page boundary and it never pretends
 * mock data is live — the caller renders a "Placeholder" pill off `source`.
 * That is the same rule the rest of the dashboard follows: nothing silently
 * picks a winner, nothing quietly degrades.
 */

import {
  DEFAULT_CONID,
  MOCK_COLLISIONS,
  MOCK_EVENTS,
  MOCK_INCOME,
  MOCK_LEVERAGE,
  MOCK_OVERVIEW,
  MOCK_PORTFOLIO,
  MOCK_ROUND_TRIP,
  MOCK_SCREENS,
  MOCK_WATCHLISTS,
  mockDetail,
} from './mock';
import type {
  IncomeRow,
  InstrumentDetail,
  LeverageView,
  MarketEvent,
  MarketOverview,
  PortfolioSnapshot,
  RoundTripRow,
  ScreenName,
  ScreenResult,
  TickerCollision,
  Watchlist,
} from './types';

export const API_BASE =
  process.env.NEXT_PUBLIC_API_URL?.replace(/\/+$/, '') || 'http://localhost:8000';

export type DataSource = 'live' | 'mock';

export interface ApiResult<T> {
  data: T;
  source: DataSource;
  /** Populated when we fell back — shown in the UI, not swallowed. */
  error: string | null;
  fetchedAt: string;
}

function ok<T>(data: T): ApiResult<T> {
  return { data, source: 'live', error: null, fetchedAt: new Date().toISOString() };
}

function fallback<T>(data: T, error: unknown): ApiResult<T> {
  return {
    data,
    source: 'mock',
    error: error instanceof Error ? error.message : String(error),
    fetchedAt: new Date().toISOString(),
  };
}

export interface FetchOptions {
  /** Seconds; passed through to the Next.js data cache. 0 = no store. */
  revalidate?: number;
  signal?: AbortSignal;
  query?: Record<string, string | number | boolean | undefined | null>;
}

function buildUrl(path: string, query?: FetchOptions['query']): string {
  const url = new URL(path.startsWith('/') ? path : `/${path}`, `${API_BASE}/`);
  if (query) {
    for (const [k, v] of Object.entries(query)) {
      if (v !== undefined && v !== null && v !== '') url.searchParams.set(k, String(v));
    }
  }
  return url.toString();
}

/**
 * Raw typed GET. Throws on a non-2xx or a network failure — the exported
 * endpoint helpers below catch and fall back.
 */
export async function getJson<T>(path: string, opts: FetchOptions = {}): Promise<T> {
  const res = await fetch(buildUrl(path, opts.query), {
    headers: { accept: 'application/json' },
    signal: opts.signal,
    next: opts.revalidate === undefined ? undefined : { revalidate: opts.revalidate },
    cache: opts.revalidate === 0 ? 'no-store' : undefined,
  });
  if (!res.ok) {
    throw new Error(`${path} → HTTP ${res.status} ${res.statusText}`);
  }
  return (await res.json()) as T;
}

async function withFallback<T>(
  path: string,
  mock: T,
  opts: FetchOptions = {},
): Promise<ApiResult<T>> {
  try {
    return ok(await getJson<T>(path, opts));
  } catch (err) {
    return fallback(mock, err);
  }
}

// ─────────────────── endpoints ───────────────────

/** GET /api/overview */
export function getOverview(opts?: FetchOptions): Promise<ApiResult<MarketOverview>> {
  return withFallback('/api/overview', MOCK_OVERVIEW, opts);
}

/** GET /api/screens/{screen} */
export function getScreen(
  screen: ScreenName,
  opts?: FetchOptions,
): Promise<ApiResult<ScreenResult>> {
  return withFallback(`/api/screens/${screen}`, MOCK_SCREENS[screen], opts);
}

/**
 * GET /api/instrument/{conid} — routed on CONID, never on symbol.
 *
 * Resolves to `null` when the fallback has no bars for that contract. The page
 * says so rather than rendering a different instrument under the right heading.
 */
export function getInstrument(
  conid: number,
  opts?: FetchOptions,
): Promise<ApiResult<InstrumentDetail | null>> {
  return withFallback(`/api/instrument/${conid}`, mockDetail(conid), opts);
}

/** GET /api/portfolio */
export function getPortfolio(opts?: FetchOptions): Promise<ApiResult<PortfolioSnapshot>> {
  return withFallback('/api/portfolio', MOCK_PORTFOLIO, opts);
}

/** GET /api/leverage — one entry per leveraged ETP held or watched. */
export function getLeverage(opts?: FetchOptions): Promise<ApiResult<LeverageView[]>> {
  return withFallback('/api/leverage', MOCK_LEVERAGE, opts);
}

/** GET /api/leverage/round-trip — the ±10% alternating-move table. */
export function getRoundTrip(opts?: FetchOptions): Promise<ApiResult<RoundTripRow[]>> {
  return withFallback('/api/leverage/round-trip', MOCK_ROUND_TRIP, opts);
}

/** GET /api/leverage/collisions — symbols that resolve to more than one contract. */
export function getCollisions(opts?: FetchOptions): Promise<ApiResult<TickerCollision[]>> {
  return withFallback('/api/leverage/collisions', MOCK_COLLISIONS, opts);
}

/** GET /api/income — the §2b sleeve. */
export function getIncome(opts?: FetchOptions): Promise<ApiResult<IncomeRow[]>> {
  return withFallback('/api/income', MOCK_INCOME, opts);
}

/** GET /api/events */
export function getEvents(opts?: FetchOptions): Promise<ApiResult<MarketEvent[]>> {
  return withFallback('/api/events', MOCK_EVENTS, opts);
}

/** GET /api/watchlists */
export function getWatchlists(opts?: FetchOptions): Promise<ApiResult<Watchlist[]>> {
  return withFallback('/api/watchlists', MOCK_WATCHLISTS, opts);
}

export { DEFAULT_CONID };

/**
 * How a panel should badge itself.
 *
 * When the API answers, the pill says ● IBKR. When it doesn't, the pill says
 * "IBKR · snapshot" — because the fallback IS real IBKR data (the 2026-08-06
 * close extracted from the approved mockup), it is simply frozen rather than
 * live. Calling it "Placeholder" would understate it; calling it "● IBKR"
 * would overstate it. Panels whose underlying feed never existed — the
 * headline tape, the income sleeve — pass `neverLive` and always read
 * "Placeholder".
 */
export function sourceBadge(
  source: DataSource,
  neverLive = false,
): { badge: 'live' | 'mock'; label: string } {
  if (neverLive) return { badge: 'mock', label: 'Placeholder' };
  return source === 'live'
    ? { badge: 'live', label: '● IBKR' }
    : { badge: 'mock', label: 'IBKR · snapshot' };
}
