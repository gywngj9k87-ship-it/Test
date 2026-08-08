'use client';

import { useMemo, useState, type ReactNode } from 'react';

/**
 * The one table in the system. Sortable, tabular-nums, right-aligned numerics,
 * left-aligned first column — the rules the mockup's CSS already encodes.
 *
 * Sorting is opt-in per column: give the column a `sortValue`. Columns without
 * one are not clickable, which is deliberate — a chip column that sorts by its
 * rendered glyph is worse than no sort at all.
 */

export interface Column<T> {
  key: string;
  header: ReactNode;
  /** Defaults to 'right' for every column but the first. */
  align?: 'left' | 'right';
  /** Providing this makes the column sortable. */
  sortValue?: (row: T) => number | string;
  render: (row: T) => ReactNode;
  width?: string;
  /** Screen-reader-only longer header, when the visible one is abbreviated. */
  title?: string;
}

export interface DataTableProps<T> {
  columns: Array<Column<T>>;
  rows: T[];
  getRowKey: (row: T, i: number) => string;
  /** Column key to sort by on first render. */
  initialSortKey?: string;
  initialSortDir?: 'asc' | 'desc';
  /** A totals row, rendered after the body with a rule above it. */
  footer?: ReactNode;
  caption?: string;
  emptyMessage?: string;
}

export default function DataTable<T>({
  columns,
  rows,
  getRowKey,
  initialSortKey,
  initialSortDir = 'desc',
  footer,
  caption,
  emptyMessage = 'No rows match this filter.',
}: DataTableProps<T>) {
  const [sortKey, setSortKey] = useState<string | null>(initialSortKey ?? null);
  const [sortDir, setSortDir] = useState<'asc' | 'desc'>(initialSortDir);

  const sorted = useMemo(() => {
    if (!sortKey) return rows;
    const col = columns.find((c) => c.key === sortKey);
    if (!col?.sortValue) return rows;
    const dir = sortDir === 'asc' ? 1 : -1;
    return [...rows].sort((a, b) => {
      const av = col.sortValue!(a);
      const bv = col.sortValue!(b);
      if (typeof av === 'number' && typeof bv === 'number') return (av - bv) * dir;
      return String(av).localeCompare(String(bv)) * dir;
    });
  }, [rows, columns, sortKey, sortDir]);

  function toggle(col: Column<T>) {
    if (!col.sortValue) return;
    if (sortKey === col.key) {
      setSortDir((d) => (d === 'asc' ? 'desc' : 'asc'));
    } else {
      setSortKey(col.key);
      setSortDir('desc');
    }
  }

  if (!rows.length) {
    return <p className="cap" style={{ margin: '4px 0 0' }}>{emptyMessage}</p>;
  }

  return (
    <table>
      {caption ? <caption className="sr-only" style={{ display: 'none' }}>{caption}</caption> : null}
      <thead>
        <tr>
          {columns.map((c, i) => {
            const sortable = Boolean(c.sortValue);
            const active = sortKey === c.key;
            return (
              <th
                key={c.key}
                className={sortable ? 'sortable' : undefined}
                style={{
                  width: c.width,
                  textAlign: c.align ?? (i === 0 ? 'left' : 'right'),
                }}
                title={c.title}
                onClick={() => toggle(c)}
                aria-sort={active ? (sortDir === 'asc' ? 'ascending' : 'descending') : undefined}
              >
                {c.header}
                {sortable ? (
                  <span className="sortmark" aria-hidden>
                    {active ? (sortDir === 'asc' ? '▲' : '▼') : '↕'}
                  </span>
                ) : null}
              </th>
            );
          })}
        </tr>
      </thead>
      <tbody>
        {sorted.map((row, i) => (
          <tr key={getRowKey(row, i)}>
            {columns.map((c, ci) => (
              <td
                key={c.key}
                style={{ textAlign: c.align ?? (ci === 0 ? 'left' : 'right') }}
              >
                {c.render(row)}
              </td>
            ))}
          </tr>
        ))}
        {footer ? footer : null}
      </tbody>
    </table>
  );
}
