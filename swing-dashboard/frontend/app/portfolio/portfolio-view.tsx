"use client";

import Link from "next/link";
import Card from "@/components/Card";
import DataTable, { type Column } from "@/components/DataTable";
import { FlagTape } from "@/components/EventTape";
import LeverageBadge from "@/components/LeverageBadge";
import ReconciliationBadge from "@/components/ReconciliationBadge";
import StatTile from "@/components/StatTile";
import StatusChip from "@/components/StatusChip";
import { cls, fmt, pct, usd } from "@/lib/format";
import { sourceBadge, type DataSource } from "@/lib/api";
import type { PortfolioSnapshot, Position } from "@/lib/types";

export default function PortfolioView({
  snapshot,
  source,
}: {
  snapshot: PortfolioSnapshot;
  source: DataSource;
}) {
  const { badge, label: badgeLabel } = sourceBadge(source);

  const cols: Array<Column<Position>> = [
    {
      key: "symbol",
      header: "Ticker",
      align: "left",
      sortValue: (p) => p.instrument.symbol,
      render: (p) => (
        <Link
          href={`/deep-dive/${p.instrument.conid}`}
          style={{ color: "var(--ink)", textDecoration: "none" }}
        >
          <LeverageBadge
            symbol={p.instrument.symbol}
            exchange={p.instrument.exchange}
            leverage={p.instrument.leverage}
            conid={p.instrument.conid}
          />
        </Link>
      ),
    },
    {
      key: "qty",
      header: "Qty",
      sortValue: (p) => p.quantity,
      render: (p) => fmt(p.quantity, p.quantity % 1 ? 4 : 0),
    },
    {
      key: "avg",
      header: "Avg cost",
      sortValue: (p) => p.avg_cost,
      render: (p) => fmt(p.avg_cost),
    },
    {
      key: "last",
      header: "Last",
      sortValue: (p) => p.last,
      render: (p) => fmt(p.last),
    },
    {
      key: "mv",
      header: "Value",
      sortValue: (p) => p.market_value,
      render: (p) => usd(p.market_value),
    },
    {
      key: "upl",
      header: "Unrealised",
      sortValue: (p) => p.unrealized_pnl,
      render: (p) => (
        <span className={cls(p.unrealized_pnl)}>{usd(p.unrealized_pnl)}</span>
      ),
    },
    {
      key: "uplpct",
      header: "%",
      sortValue: (p) => p.unrealized_pct,
      render: (p) => (
        <span className={cls(p.unrealized_pct)}>{pct(p.unrealized_pct)}</span>
      ),
    },
    {
      key: "weight",
      header: "Weight",
      sortValue: (p) => p.weight_pct,
      render: (p) => `${fmt(p.weight_pct, 1)}%`,
    },
    {
      key: "basis",
      header: "Cost basis",
      sortValue: (p) => p.cost_basis_status,
      render: (p) =>
        p.cost_basis_status === "ok" ? (
          <StatusChip tone="good" label="Verified" />
        ) : (
          <StatusChip
            tone={p.cost_basis_status === "unverified" ? "warn" : "crit"}
            label={
              p.cost_basis_status === "unverified"
                ? "Unverified"
                : "Corp action?"
            }
            title={p.cost_basis_note ?? undefined}
          />
        ),
    },
  ];

  const footer = (
    <tr style={{ borderTop: "1px solid var(--axis)" }}>
      <td>
        <b>Total</b>
      </td>
      <td />
      <td />
      <td />
      <td>
        <b>{usd(snapshot.total_market_value)}</b>
      </td>
      <td className={cls(snapshot.total_unrealized_pnl)}>
        <b>{usd(snapshot.total_unrealized_pnl)}</b>
      </td>
      <td className="down">
        <b>−53.50%</b>
      </td>
      <td>100.0%</td>
      <td />
    </tr>
  );

  // The biggest position by weight — not simply the first row.
  const largest = snapshot.positions.reduce<Position | null>(
    (best, p) => (best == null || p.weight_pct > best.weight_pct ? p : best),
    null,
  );

  const shape: Array<[string, string]> = [
    ["Gross position value", usd(snapshot.gross_position_value)],
    ["Cash", usd(snapshot.cash)],
    ["Deployed", `${fmt(snapshot.deployed_pct, 1)}%`],
    [
      "Largest position",
      `${largest?.instrument.symbol ?? "—"} · ${fmt(snapshot.largest_position_pct, 1)}% of deployed`,
    ],
    ["Positions", String(snapshot.positions.length)],
    ["Portfolio beta vs SPY", `${fmt(snapshot.beta_vs_index)} (est.)`],
    ["Unrealised P&L", usd(snapshot.total_unrealized_pnl)],
    ["Account leverage", `${fmt(snapshot.leverage)}×`],
  ];

  return (
    <>
      <div className="grid g4" style={{ marginBottom: 14 }}>
        <StatTile
          label="Net liquidation"
          badge={badge}
          badgeLabel={badgeLabel}
          value={usd(snapshot.net_liquidation)}
          detail={`${fmt(snapshot.deployed_pct, 1)}% deployed · ${usd(snapshot.cash)} cash`}
        />
        <StatTile
          label="Gross position value"
          value={usd(snapshot.gross_position_value)}
          detail="As reported by IBKR — see the cross-check below"
        />
        <StatTile
          label="Unrealised P&L"
          value={usd(snapshot.total_unrealized_pnl)}
          valueClass={cls(snapshot.total_unrealized_pnl)}
          detail="One position's cost basis is unverified — this number is provisional"
        />
        <StatTile
          label="Largest position"
          value={`${fmt(snapshot.largest_position_pct, 1)}%`}
          detail={`${largest?.instrument.symbol ?? "—"} — of deployed capital, above the 25% single-name guideline`}
        />
      </div>

      <Card
        title="Positions"
        badge={badge}
        badgeLabel={badgeLabel}
        caption="Synced from your account. Cost basis reconciled against corporate actions before P&L is trusted."
      >
        <p className="cap" style={{ margin: "-8px 0 14px" }}>
          <ReconciliationBadge recs={snapshot.reconciliation} />
        </p>
        <DataTable
          columns={cols}
          rows={snapshot.positions}
          getRowKey={(p) => String(p.instrument.conid)}
          initialSortKey="mv"
          footer={footer}
        />
      </Card>

      <div className="grid g2">
        <Card
          title="Risk flags"
          badge={badge}
          badgeLabel={badgeLabel}
          caption="Each flag carries an icon and a label — never colour alone."
        >
          <FlagTape flags={snapshot.flags} />
        </Card>

        <Card
          title="Book shape"
          badge={badge}
          badgeLabel={badgeLabel}
          caption="Concentration and cash drag at a glance."
        >
          {shape.map(([k, v]) => (
            <div className="kv" key={k}>
              <span className="k">{k}</span>
              <span className="v">{v}</span>
            </div>
          ))}
          <div style={{ marginTop: 14 }}>
            <p className="cap" style={{ margin: "0 0 6px" }}>
              Exposure by theme
            </p>
            {Object.entries(snapshot.sector_exposure).map(([k, v]) => (
              <div className="kv" key={k}>
                <span className="k">{k}</span>
                <span className="v">{fmt(v, 1)}%</span>
              </div>
            ))}
          </div>
        </Card>
      </div>
    </>
  );
}
