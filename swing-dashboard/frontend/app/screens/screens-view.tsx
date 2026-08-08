"use client";

import Link from "next/link";
import Card from "@/components/Card";
import DataTable, { type Column } from "@/components/DataTable";
import StatusChip from "@/components/StatusChip";
import { cls, fmt, pct } from "@/lib/format";
import { sourceBadge, type DataSource } from "@/lib/api";
import type { DriverRow, ScreenName, ScreenResult } from "@/lib/types";

export interface ScreensViewProps {
  screens: Array<{ id: ScreenName; label: string; blurb: string }>;
  active: ScreenName;
  result: ScreenResult;
  source: DataSource;
}

export default function ScreensView({
  screens,
  active,
  result,
  source,
}: ScreensViewProps) {
  const { badge, label: badgeLabel } = sourceBadge(source);
  const meta = screens.find((s) => s.id === active)!;

  const cols: Array<Column<DriverRow>> = [
    {
      key: "symbol",
      header: "Ticker",
      align: "left",
      sortValue: (r) => r.symbol,
      render: (r) => (
        <Link
          href={`/deep-dive/${r.conid}`}
          style={{ color: "var(--ink)", textDecoration: "none" }}
        >
          <span className="tk">{r.symbol}</span>
          <span className="ex">{r.exchange}</span>
        </Link>
      ),
    },
    {
      key: "theme",
      header: "Theme",
      align: "left",
      sortValue: (r) => r.theme ?? "",
      render: (r) => (
        <span style={{ color: "var(--ink-2)" }}>{r.theme ?? "—"}</span>
      ),
    },
    {
      key: "last",
      header: "Last",
      sortValue: (r) => r.last,
      render: (r) => fmt(r.last),
    },
    {
      key: "w1",
      header: "1w",
      sortValue: (r) => r.return_1w,
      render: (r) => (
        <span className={cls(r.return_1w)}>{pct(r.return_1w)}</span>
      ),
    },
    {
      key: "w4",
      header: "4w",
      sortValue: (r) => r.return_4w,
      render: (r) => (
        <span className={cls(r.return_4w)}>{pct(r.return_4w)}</span>
      ),
    },
    {
      key: "w13",
      header: "13w",
      sortValue: (r) => r.return_13w,
      render: (r) => (
        <span className={cls(r.return_13w)}>{pct(r.return_13w)}</span>
      ),
    },
    {
      key: "rs13",
      header: "RS 13w",
      sortValue: (r) => r.rs_vs_index_13w,
      render: (r) => (
        <span className={cls(r.rs_vs_index_13w)}>
          <b>{pct(r.rs_vs_index_13w)}</b>
        </span>
      ),
    },
    {
      key: "above",
      header: "vs 10w avg",
      sortValue: (r) => (r.above_50dma ? 1 : 0),
      render: (r) => (
        <StatusChip
          tone={r.above_50dma ? "good" : "crit"}
          icon={r.above_50dma ? "▲" : "▼"}
          label={r.above_50dma ? "Above" : "Below"}
        />
      ),
    },
    {
      key: "fromhi",
      header: "From high",
      sortValue: (r) => r.pct_from_high,
      render: (r) =>
        r.at_new_high ? (
          <StatusChip tone="good" label="New high" />
        ) : (
          pct(r.pct_from_high)
        ),
    },
  ];

  return (
    <>
      <div className="filters" style={{ marginBottom: 14 }}>
        <div
          className="seg"
          role="tablist"
          aria-label="Screen"
          style={{ flexWrap: "wrap" }}
        >
          {screens.map((s) => (
            <Link
              key={s.id}
              href={`/screens?screen=${s.id}`}
              role="tab"
              aria-selected={s.id === active}
              style={{
                border: 0,
                background: s.id === active ? "var(--wash)" : "transparent",
                color: s.id === active ? "var(--ink)" : "var(--ink-2)",
                fontWeight: s.id === active ? 600 : 400,
                fontSize: 12.5,
                padding: "6px 13px",
                borderRadius: 6,
                textDecoration: "none",
              }}
            >
              {s.label}
            </Link>
          ))}
        </div>
      </div>

      <Card
        title={meta.label}
        badge={badge}
        badgeLabel={badgeLabel}
        caption={meta.blurb}
        actions={
          <span className="pill">
            {result.rows.length} {result.rows.length === 1 ? "name" : "names"}
          </span>
        }
      >
        {result.truncated_at != null ? (
          <p className="cap" style={{ margin: "-8px 0 12px" }}>
            <StatusChip
              tone="neutral"
              label={`Capped at ${result.truncated_at}`}
            />{" "}
            This screen is truncated — there are more names behind it. Never a
            silent cut.
          </p>
        ) : null}
        <DataTable
          columns={cols}
          rows={result.rows}
          getRowKey={(r) => String(r.conid)}
          initialSortKey="rs13"
          emptyMessage="Nothing passes this screen right now. That is a result, not an error."
        />
      </Card>

      <div className="note">
        <b>Universe.</b> On the live build these eleven screens recompute daily
        over the ~520 unique S&amp;P 500 and Nasdaq 100 names. Without a backend
        attached they run over the sixteen large caps carried in the mockup, so
        several screens are legitimately short. Short is reported; it is never
        padded.
      </div>
    </>
  );
}
