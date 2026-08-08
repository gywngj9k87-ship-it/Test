'use client';

import { useState, type ReactNode } from 'react';

/**
 * The table-view twin. Rule 4: every chart has one.
 *
 * Usage:
 *   <TableView chart={<LineChart .../>} table={<table>...</table>} />
 *
 * The toggle button is rendered by `renderToggle` so it can sit in the card
 * header next to the title, where the mockup puts it. If you don't need that,
 * `<TableView>` renders its own inline toggle above the chart.
 */

export interface TableViewProps {
  chart: ReactNode;
  table: ReactNode;
  /** Start with the table open — used where the numbers are the point. */
  defaultOpen?: boolean;
  /** Render the toggle inline above the chart instead of expecting a header slot. */
  inlineToggle?: boolean;
  labelClosed?: string;
  labelOpen?: string;
}

export default function TableView({
  chart,
  table,
  defaultOpen = false,
  inlineToggle = true,
  labelClosed = 'Table view',
  labelOpen = 'Hide table',
}: TableViewProps) {
  const [open, setOpen] = useState(defaultOpen);
  return (
    <>
      {inlineToggle ? (
        <div style={{ display: 'flex', justifyContent: 'flex-end', marginBottom: 6 }}>
          <button className="link" onClick={() => setOpen((o) => !o)} aria-expanded={open}>
            {open ? labelOpen : labelClosed}
          </button>
        </div>
      ) : null}
      {chart}
      <div className={open ? 'tblview on' : 'tblview'}>{table}</div>
    </>
  );
}

/**
 * Controlled variant, for when the toggle lives in the card header.
 * Pair it with `useTableToggle()`.
 */
export function useTableToggle(defaultOpen = false) {
  const [open, setOpen] = useState(defaultOpen);
  const toggle = (
    <button className="link" onClick={() => setOpen((o) => !o)} aria-expanded={open}>
      {open ? 'Hide table' : 'Table view'}
    </button>
  );
  return { open, toggle, setOpen };
}
