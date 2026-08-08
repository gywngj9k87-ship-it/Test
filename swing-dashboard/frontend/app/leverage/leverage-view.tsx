"use client";

import Card from "@/components/Card";
import { FilterNote } from "@/components/GlobalFilters";
import DataTable, { type Column } from "@/components/DataTable";
import Legend from "@/components/Legend";
import LineChart from "@/components/LineChart";
import StatTile from "@/components/StatTile";
import StatusChip from "@/components/StatusChip";
import TableView from "@/components/TableView";
import LeverageBadge from "@/components/LeverageBadge";
import { barWidth, cls, fmt, pct, pp } from "@/lib/format";
import { sourceBadge, type DataSource } from "@/lib/api";
import type {
  LeverageView as LeverageViewModel,
  RoundTripRow,
  TickerCollision,
} from "@/lib/types";

export default function LeverageView({
  views,
  roundTrip,
  collisions,
  source,
}: {
  views: LeverageViewModel[];
  roundTrip: RoundTripRow[];
  collisions: TickerCollision[];
  source: DataSource;
}) {
  const { badge, label: badgeLabel } = sourceBadge(source);

  const rtCols: Array<Column<RoundTripRow>> = [
    {
      key: "lev",
      header: "Leverage",
      align: "left",
      sortValue: (r) => r.leverage,
      render: (r) => (
        <>
          <span className="tk">{r.leverage}×</span>
          {r.note ? <span className="lv">{r.note}</span> : null}
        </>
      ),
    },
    {
      key: "und",
      header: "Underlying",
      sortValue: (r) => r.underlying_pct,
      render: (r) => pct(r.underlying_pct, 1),
    },
    {
      key: "lev_out",
      header: "Levered outcome",
      sortValue: (r) => r.levered_pct,
      render: (r) => <span className="down">{pct(r.levered_pct, 1)}</span>,
    },
    {
      key: "bar",
      header: "",
      width: "45%",
      render: (r) => (
        <span className="track" style={{ display: "block" }}>
          <span
            className="fill"
            style={{
              width: `${barWidth(Math.abs(r.levered_pct))}%`,
              background: "var(--s2)",
            }}
          />
        </span>
      ),
    },
  ];

  const colCols: Array<Column<TickerCollision>> = [
    {
      key: "symbol",
      header: "Symbol",
      align: "left",
      sortValue: (r) => r.symbol,
      render: (r) => <span className="tk">{r.symbol}</span>,
    },
    {
      key: "conid",
      header: "Contract",
      align: "left",
      sortValue: (r) => r.conid,
      render: (r) => <span style={{ color: "var(--muted)" }}>{r.conid}</span>,
    },
    {
      key: "exchange",
      header: "Exchange",
      align: "left",
      sortValue: (r) => r.exchange,
      render: (r) => `${r.exchange} · ${r.country}`,
    },
    {
      key: "what",
      header: "What it actually is",
      align: "left",
      sortValue: (r) => r.description,
      render: (r) => (
        <>
          {r.description}
          {r.inverse ? (
            <span style={{ marginLeft: 8 }}>
              <StatusChip tone="crit" label="Inverse" />
            </span>
          ) : null}
        </>
      ),
    },
  ];

  return (
    <>
      <FilterNote honours={[]} />
      <div className="note" style={{ marginTop: 0 }}>
        <b>Why this tab exists.</b> Leverage rewards trend and punishes chop,
        and no momentum oscillator tells you which regime you&rsquo;re in. Every
        chart here is indexed to 100 at the start so three series share one axis
        — never two scales — on a log scale, because a 17× range and a flat line
        have to stay legible together.
      </div>

      {views.map((v, i) => {
        const a = v.analysis;
        const L = a.stated_leverage;
        return (
          <Card
            key={a.instrument.conid}
            badge={badge}
            badgeLabel={badgeLabel}
            title={
              <>
                <LeverageBadge
                  symbol={a.instrument.symbol}
                  exchange={a.instrument.exchange}
                  leverage={L}
                  conid={a.instrument.conid}
                />{" "}
                long
              </>
            }
            caption={`Against ${a.underlying.symbol} (${a.underlying.name}). All three series indexed to 100 twelve months ago — one axis, log scale.`}
          >
            <div className="grid g4" style={{ marginBottom: 14 }}>
              <StatTile
                label="Underlying"
                value={pct(a.underlying_return_pct)}
                valueClass={cls(a.underlying_return_pct)}
                detail={`annualised vol ${fmt(a.underlying_vol_annual, 1)}%`}
              />
              <StatTile
                label={`Naive ${L}× expectation`}
                value={pct(a.naive_expected_pct)}
                detail="what most people assume"
              />
              <StatTile
                label="Actual product"
                value={pct(a.actual_return_pct)}
                valueClass={cls(a.actual_return_pct)}
                detail={`gap ${pp(a.gap_pp)} · realised beta ${fmt(a.realized_beta, 2)}×`}
              />
              <StatTile
                label="Max drawdown"
                value={pct(a.max_drawdown_pct)}
                valueClass="down"
                detail={`underlying only ${pct(a.underlying_max_drawdown_pct)}`}
              />
            </div>

            <Legend
              items={[
                {
                  color: "var(--s1)",
                  label: `${a.underlying.symbol} · unlevered`,
                },
                { color: "var(--s3)", label: `Naive ${L}×` },
                { color: "var(--s2)", label: `Actual ${L}× product` },
              ]}
            />

            <TableView
              chart={
                <LineChart
                  ariaLabel={`${a.instrument.symbol}: unlevered underlying, naive ${L}× expectation, and the actual product, indexed to 100 twelve months ago on a log scale.`}
                  dates={v.series.weeks}
                  height={300}
                  padRight={70}
                  log
                  ticks={4}
                  formatValue={(x) => fmt(x, 1)}
                  series={[
                    { d: v.series.underlying, c: "var(--s1)", lab: "1×" },
                    { d: v.series.naive, c: "var(--s3)", lab: "naive" },
                    { d: v.series.actual, c: "var(--s2)", lab: "actual" },
                  ]}
                />
              }
              table={
                <table>
                  <thead>
                    <tr>
                      <th>Week</th>
                      <th>Unlevered</th>
                      <th>Naive {L}×</th>
                      <th>Actual</th>
                    </tr>
                  </thead>
                  <tbody>
                    {v.series.actual
                      .map((x, j) => (
                        <tr key={j}>
                          <td>{j + 1}</td>
                          <td>{fmt(v.series.underlying[j], 1)}</td>
                          <td>{fmt(v.series.naive[j], 1)}</td>
                          <td>{fmt(x, 1)}</td>
                        </tr>
                      ))
                      .reverse()}
                  </tbody>
                </table>
              }
            />

            <div className="grid g3" style={{ marginTop: 14 }}>
              <div className="kv">
                <span className="k">Volatility drag / yr</span>
                <span className="v down">
                  −{fmt(a.volatility_drag_annual_pct, 1)}%
                </span>
              </div>
              <div className="kv">
                <span className="k">Below 1y high</span>
                <span className="v down">{pct(a.pct_from_high)}</span>
              </div>
              <div className="kv">
                <span className="k">Needed to regain it</span>
                <span className="v">+{fmt(a.recovery_needed_pct, 1)}%</span>
              </div>
            </div>

            <div className="grid g3" style={{ marginTop: 0 }}>
              <div className="kv">
                <span className="k">Carry cost / yr</span>
                <span className="v down">
                  −{fmt(a.carry_cost_annual_pct, 2)}%
                </span>
              </div>
              <div className="kv">
                <span className="k">Beta drift vs stated</span>
                <span className="v">{pp(a.beta_drift, 2)}</span>
              </div>
              <div className="kv">
                <span className="k">Single-day wipeout</span>
                <span className="v down">
                  {fmt(a.single_day_wipeout_pct, 1)}%
                </span>
              </div>
            </div>

            <p className="cap" style={{ margin: "14px 0 0" }}>
              <StatusChip
                tone={a.regime === "trending" ? "good" : "warn"}
                label={a.regime === "trending" ? "Trending" : "Choppy"}
              />{" "}
              {a.regime_note}
              {a.holding_period_warning ? ` ${a.holding_period_warning}` : ""}
            </p>
            {i === views.length - 1 ? null : null}
          </Card>
        );
      })}

      <Card
        title="What a round trip costs"
        caption="Twenty alternating ±10% moves. The underlying ends −9.6%; the levered product does not."
      >
        <DataTable
          columns={rtCols}
          rows={roundTrip}
          getRowKey={(r) => String(r.leverage)}
        />
      </Card>

      <Card
        title="Ticker collisions in your lists"
        badge={badge}
        badgeLabel={badgeLabel}
        caption="Resolved through IBKR contract search. This is why the build keys on contract id, never on symbol — and why every ticker on this dashboard ships with its exchange and leverage factor."
      >
        <DataTable
          columns={colCols}
          rows={collisions}
          getRowKey={(r) => String(r.conid)}
          initialSortKey="symbol"
          initialSortDir="asc"
        />
      </Card>
    </>
  );
}
