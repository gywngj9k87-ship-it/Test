"use client";

import Link from "next/link";
import Card from "@/components/Card";
import { FilterNote } from "@/components/GlobalFilters";
import DataTable, { type Column } from "@/components/DataTable";
import EventTape from "@/components/EventTape";
import Legend from "@/components/Legend";
import LineChart from "@/components/LineChart";
import ScoreBar from "@/components/ScoreBar";
import StatTile from "@/components/StatTile";
import StatusChip from "@/components/StatusChip";
import TableView from "@/components/TableView";
import { arrow, cls, fmt, pct } from "@/lib/format";
import { sourceBadge, type DataSource } from "@/lib/api";
import type {
  DriverRow,
  MarketEvent,
  MarketOverview,
  ThemeRow,
} from "@/lib/types";

export interface OverviewViewProps {
  overview: MarketOverview;
  events: MarketEvent[];
  /** Weekly axis labels ("Feb 9"), one per point on the indexed chart. */
  weekLabels: string[];
  /** Third series on the broad-vs-narrow chart. */
  semisSeries: number[];
  overviewSource: DataSource;
  eventsSource: DataSource;
}

export default function OverviewView({
  overview,
  events,
  weekLabels,
  semisSeries,
  overviewSource,
  eventsSource,
}: OverviewViewProps) {
  const b = overview.breadth;
  const spx = overview.tiles[0];
  const { badge, label: badgeLabel } = sourceBadge(overviewSource);
  // The tape's feed (Finnhub) has never been attached — always a placeholder.
  const tape = sourceBadge(eventsSource, true);

  const themeCols: Array<Column<ThemeRow>> = [
    {
      key: "theme",
      header: "Theme",
      align: "left",
      sortValue: (r) => r.theme,
      render: (r) => <span className="tk">{r.theme}</span>,
    },
    {
      key: "n",
      header: "n",
      sortValue: (r) => r.count,
      render: (r) => <span style={{ color: "var(--muted)" }}>{r.count}</span>,
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
      key: "w13",
      header: "13w",
      sortValue: (r) => r.return_13w,
      render: (r) => (
        <span className={cls(r.return_13w)}>{pct(r.return_13w)}</span>
      ),
    },
    {
      key: "rs13",
      header: "RS vs S&P",
      sortValue: (r) => r.rs_vs_index_13w,
      render: (r) => (
        <StatusChip
          tone={
            r.rs_vs_index_13w > 2
              ? "good"
              : r.rs_vs_index_13w < -5
                ? "crit"
                : "neutral"
          }
          icon={arrow(r.rs_vs_index_13w)}
          label={pct(r.rs_vs_index_13w)}
        />
      ),
    },
  ];

  const driverCols: Array<Column<DriverRow>> = [
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
      <FilterNote honours={[]} />
      <div className="grid g4" style={{ marginBottom: 14 }}>
        <StatTile
          label="S&P 500"
          badge={badge}
          badgeLabel={badgeLabel}
          value={fmt(spx.last)}
          detail={
            <>
              <span className={cls(spx.return_1w)}>{pct(spx.return_1w)}</span>{" "}
              1w ·{" "}
              <span className={cls(spx.return_13w)}>{pct(spx.return_13w)}</span>{" "}
              13w ·{" "}
              {spx.at_new_high
                ? "at a 26-week high"
                : `${pct(spx.pct_from_high)} from high`}
            </>
          }
        />
        <StatTile
          label="Above 10-week average"
          value={`${b.above_50dma_pct}%`}
          detail={`${b.above_50dma} of ${b.universe_size} large caps · ${b.new_highs_52w} at new 26w highs`}
        />
        <StatTile
          label="This week"
          value={`${b.advancers} / ${b.decliners}`}
          detail={`advancing / declining — ${b.decliners === 0 ? "a clean sweep" : "mixed"}`}
        />
        <StatTile
          label="Breadth spread · 13w"
          value={pct(b.spread_13w)}
          valueClass={cls(b.spread_13w)}
          detail={`equal-weight minus index — ${
            b.spread_13w < 0
              ? "narrow, few names carrying"
              : "broad participation"
          }`}
        />
      </div>

      <Card
        title="Is the market broad or narrow?"
        badge={badge}
        badgeLabel={badgeLabel}
        caption="S&P 500, an equal-weighted basket of 16 large caps, and semiconductors — all indexed to 100 twenty-six weeks ago, one axis. When the index line pulls away from the equal-weighted line, a handful of names are doing the work."
      >
        <Legend
          items={[
            { color: "var(--s1)", label: "S&P 500" },
            { color: "var(--s2)", label: "Equal-weight 16" },
            { color: "var(--s3)", label: "Semis" },
          ]}
        />
        <TableView
          chart={
            <LineChart
              ariaLabel="S&P 500, an equal-weighted basket of sixteen large caps, and semiconductors, all indexed to 100 twenty-six weeks ago."
              dates={weekLabels}
              padRight={64}
              height={300}
              formatValue={(v) => fmt(v, 1)}
              formatAxis={(v) => String(Math.round(v))}
              series={[
                { d: overview.index_series, c: "var(--s1)", lab: "S&P" },
                {
                  d: overview.equal_weight_series,
                  c: "var(--s2)",
                  lab: "Eq-wt",
                },
                { d: semisSeries, c: "var(--s3)", lab: "Semis" },
              ]}
            />
          }
          table={
            <table>
              <thead>
                <tr>
                  <th>Week</th>
                  <th>S&P</th>
                  <th>Equal-weight</th>
                  <th>Semis</th>
                </tr>
              </thead>
              <tbody>
                {weekLabels
                  .map((d, i) => (
                    <tr key={d}>
                      <td>{d}</td>
                      <td>{fmt(overview.index_series[i], 1)}</td>
                      <td>{fmt(overview.equal_weight_series[i], 1)}</td>
                      <td>{fmt(semisSeries[i], 1)}</td>
                    </tr>
                  ))
                  .reverse()}
              </tbody>
            </table>
          }
        />
        <p className="cap" style={{ margin: "12px 0 0" }}>
          <b style={{ color: "var(--ink)" }}>Read:</b> the S&P is up{" "}
          {pct(b.index_return_13w)} over thirteen weeks while the equal-weighted
          basket is {pct(b.equal_weight_return_13w)} — a{" "}
          {fmt(Math.abs(b.spread_13w), 1)} point gap. {b.above_50dma_pct}% of
          names sit above their 10-week average and the median 4-week return is{" "}
          {pct(b.median_return_4w)} against the index&rsquo;s{" "}
          {pct(spx.return_4w)}. Participation is thinner than the headline
          suggests.
        </p>
      </Card>

      <div className="grid g2">
        <Card
          title="Breadth"
          badge={badge}
          badgeLabel={badgeLabel}
          caption="Computed across the 16 large caps below. On the full build this runs over all ~520 index names."
        >
          <ScoreBar
            label="Above 10-week average"
            value={b.above_50dma_pct}
            display={`${b.above_50dma} / ${b.universe_size}`}
          />
          <ScoreBar
            label="Advancing this week"
            value={(b.advancers / b.universe_size) * 100}
            display={`${b.advancers} / ${b.universe_size}`}
          />
          <ScoreBar
            label="At new 26-week highs"
            value={(b.new_highs_52w / b.universe_size) * 100}
            display={`${b.new_highs_52w} / ${b.universe_size}`}
          />
          <ScoreBar
            label="Median 4-week return"
            value={50 + b.median_return_4w * 5}
            display={pct(b.median_return_4w)}
          />
          <div className="kv" style={{ marginTop: 10 }}>
            <span className="k">Index 13w</span>
            <span className={`v ${cls(b.index_return_13w)}`}>
              {pct(b.index_return_13w)}
            </span>
          </div>
          <div className="kv">
            <span className="k">Equal-weight 13w</span>
            <span className={`v ${cls(b.equal_weight_return_13w)}`}>
              {pct(b.equal_weight_return_13w)}
            </span>
          </div>
          <div className="kv">
            <span className="k">Spread</span>
            <span className={`v ${cls(b.spread_13w)}`}>
              {pct(b.spread_13w)}{" "}
              <StatusChip
                tone={
                  b.verdict === "narrow"
                    ? "warn"
                    : b.verdict === "broad"
                      ? "good"
                      : "neutral"
                }
                label={
                  b.verdict === "narrow"
                    ? "Narrow"
                    : b.verdict === "broad"
                      ? "Broad"
                      : "Mixed"
                }
              />
            </span>
          </div>
        </Card>

        <Card
          title="Theme rotation · 13 weeks"
          badge={badge}
          badgeLabel={badgeLabel}
          caption="Ranked by relative strength against the S&P, not by absolute move — the number that matters for choosing what to trade."
        >
          <DataTable
            columns={themeCols}
            rows={overview.themes}
            getRowKey={(r) => r.theme}
            initialSortKey="rs13"
          />
          <p className="cap" style={{ margin: "12px 0 0" }}>
            Themes built from names in your own watchlists — the full build maps
            to GICS sectors across the whole index.
          </p>
        </Card>
      </div>

      <Card
        title="Index drivers & relative strength"
        badge={badge}
        badgeLabel={badgeLabel}
        caption="Every row real, sorted by 13-week relative strength. Green above / red below the 10-week average — and the chip says which, so the colour is never carrying the message alone."
      >
        <DataTable
          columns={driverCols}
          rows={overview.drivers}
          getRowKey={(r) => String(r.conid)}
          initialSortKey="rs13"
        />
      </Card>

      <Card
        title="Today's tape"
        badge={tape.badge}
        badgeLabel={tape.label}
        caption="Every event paired with its price reaction. Placeholder until the Finnhub headline feed is attached."
      >
        <EventTape events={events} />
      </Card>
    </>
  );
}
