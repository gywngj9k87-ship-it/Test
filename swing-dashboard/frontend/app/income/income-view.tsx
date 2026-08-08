"use client";

import Card from "@/components/Card";
import DataTable, { type Column } from "@/components/DataTable";
import LeverageBadge from "@/components/LeverageBadge";
import StatusChip from "@/components/StatusChip";
import { fmt, pct, shortDate } from "@/lib/format";
import { sourceBadge, type DataSource } from "@/lib/api";
import type { IncomeRow } from "@/lib/types";

/**
 * §2b — the income sleeve.
 *
 * Running RSI and MACD across thinly traded preferreds and small-cap shipping
 * ADRs would mostly measure the bid-ask spread. So the sleeve swaps momentum
 * out for yield, coverage, call risk, liquidity and rate sensitivity.
 */
export default function IncomeView({
  rows,
  source,
}: {
  rows: IncomeRow[];
  source: DataSource;
}) {
  // The Yahoo fundamentals feed has never been attached — always a placeholder.
  const { badge, label: badgeLabel } = sourceBadge(source, true);

  const cols: Array<Column<IncomeRow>> = [
    {
      key: "symbol",
      header: "Ticker",
      align: "left",
      sortValue: (r) => r.instrument.symbol,
      render: (r) => (
        <LeverageBadge
          symbol={r.instrument.symbol}
          exchange={r.instrument.exchange}
          conid={r.instrument.conid}
        />
      ),
    },
    {
      key: "price",
      header: "Price",
      sortValue: (r) => r.price,
      render: (r) => `$${fmt(r.price)}`,
    },
    {
      key: "yield",
      header: "Yield",
      sortValue: (r) => r.current_yield ?? -1,
      render: (r) => `${fmt(r.current_yield, 1)}%`,
    },
    {
      key: "exdiv",
      header: "Ex-div",
      sortValue: (r) => r.ex_div_date ?? "",
      render: (r) => (r.ex_div_date ? shortDate(r.ex_div_date) : "—"),
    },
    {
      key: "cover",
      header: "Cover",
      sortValue: (r) => r.cash_flow_coverage ?? -1,
      render: (r) =>
        r.cash_flow_coverage == null ? "—" : `${fmt(r.cash_flow_coverage, 1)}×`,
    },
    {
      key: "ytc",
      header: "YTC",
      sortValue: (r) => r.yield_to_call ?? -1,
      render: (r) =>
        r.yield_to_call == null ? "—" : `${fmt(r.yield_to_call, 1)}%`,
    },
    {
      key: "call",
      header: "Call",
      sortValue: (r) => r.call_date ?? "",
      render: (r) => (r.call_date ? shortDate(r.call_date) : "—"),
    },
    {
      key: "rate",
      header: "Rate beta",
      sortValue: (r) => r.rate_beta_tnx ?? 0,
      render: (r) => fmt(r.rate_beta_tnx, 2),
      title:
        "Correlation to the 10-year yield — what actually drives preferred prices",
    },
    {
      key: "from52",
      header: "From 52w high",
      sortValue: (r) => r.pct_from_52w_high ?? 0,
      render: (r) => pct(r.pct_from_52w_high, 1),
    },
    {
      key: "trend",
      header: "200 DMA",
      sortValue: (r) => (r.above_200dma ? 1 : 0),
      render: (r) => (
        <StatusChip
          tone={r.above_200dma ? "good" : "warn"}
          icon={r.above_200dma ? "▲" : "▼"}
          label={r.above_200dma ? "Above" : "Below"}
        />
      ),
    },
    {
      key: "liquidity",
      header: "Liquidity",
      sortValue: (r) =>
        r.liquidity === "good" ? 2 : r.liquidity === "moderate" ? 1 : 0,
      render: (r) => (
        <StatusChip
          tone={
            r.liquidity === "good"
              ? "good"
              : r.liquidity === "thin"
                ? "warn"
                : "neutral"
          }
          label={
            r.liquidity
              ? `${r.liquidity[0].toUpperCase()}${r.liquidity.slice(1)}${
                  r.days_to_exit != null
                    ? ` · ${fmt(r.days_to_exit, 1)}d out`
                    : ""
                }`
              : "Unknown"
          }
          title={
            r.adv_usd_20d
              ? `20-day average dollar volume $${fmt(r.adv_usd_20d, 0)}`
              : undefined
          }
        />
      ),
    },
  ];

  return (
    <>
      <div className="note" style={{ marginTop: 0 }}>
        <b>The &ldquo;track&rdquo; list, 100 names.</b> Shipping, preferreds and
        small-cap ADRs. Running RSI and MACD across these would mostly measure
        the bid-ask spread, so the sleeve swaps in yield, coverage, call risk
        and liquidity. <span className="pill mock">Placeholder</span> — needs
        the Yahoo fundamentals feed. Tickers are real names from your list; the
        metrics are illustrative and are labelled as such rather than passed off
        as live.
      </div>

      <Card
        title="Income sleeve"
        badge={badge}
        badgeLabel={badgeLabel}
        caption="Sorted on yield by default. Liquidity and call risk are first-class columns here — a 7.8% yield you cannot exit in a day is not a 7.8% yield."
      >
        <DataTable
          columns={cols}
          rows={rows}
          getRowKey={(r) => String(r.instrument.conid)}
          initialSortKey="yield"
        />
      </Card>

      <div className="grid g2">
        <Card
          title="Forward income"
          caption="Annual distribution per share × position size, once positions exist. Empty until the sleeve is funded."
        >
          {rows.map((r) => (
            <div className="kv" key={r.instrument.conid}>
              <span className="k">
                {r.instrument.symbol}
                {r.consecutive_years
                  ? ` · ${r.consecutive_years}y consecutive`
                  : ""}
              </span>
              <span className="v">
                ${fmt(r.annual_distribution)} / sh
                {r.dividend_growth_5y != null
                  ? ` · ${pct(r.dividend_growth_5y, 1)} 5y growth`
                  : ""}
              </span>
            </div>
          ))}
        </Card>

        <Card
          title="Call risk"
          caption="For the preferreds: current yield versus yield-to-call. When YTC is well below the current yield, the coupon is borrowed time."
        >
          {rows
            .filter((r) => r.yield_to_call != null)
            .map((r) => (
              <div className="kv" key={r.instrument.conid}>
                <span className="k">
                  {r.instrument.symbol} · par ${fmt(r.par_value, 0)} ·{" "}
                  {r.cumulative ? "cumulative" : "non-cumulative"}
                </span>
                <span className="v">
                  {fmt(r.current_yield, 1)}% → {fmt(r.yield_to_call, 1)}%{" "}
                  <StatusChip
                    tone={
                      (r.current_yield ?? 0) - (r.yield_to_call ?? 0) > 1
                        ? "warn"
                        : "neutral"
                    }
                    label={
                      (r.current_yield ?? 0) - (r.yield_to_call ?? 0) > 1
                        ? "Call risk"
                        : "Low call risk"
                    }
                  />
                </span>
              </div>
            ))}
        </Card>
      </div>
    </>
  );
}
