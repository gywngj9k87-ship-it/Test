"use client";

import Link from "next/link";
import Card from "@/components/Card";
import DataTable, { type Column } from "@/components/DataTable";
import HistChart from "@/components/HistChart";
import Legend from "@/components/Legend";
import LineChart from "@/components/LineChart";
import PriceChart from "@/components/PriceChart";
import ReconciliationBadge from "@/components/ReconciliationBadge";
import ScoreBar from "@/components/ScoreBar";
import StatTile from "@/components/StatTile";
import StatusChip, { toneFromSeverity } from "@/components/StatusChip";
import TableView from "@/components/TableView";
import { InstrumentBadge } from "@/components/LeverageBadge";
import { cls, compact, fmt, pct, shortDate } from "@/lib/format";
import { sourceBadge, type DataSource } from "@/lib/api";
import type { InstrumentDetail, PeerRow } from "@/lib/types";

export default function DeepDiveView({
  detail,
  source,
}: {
  detail: InstrumentDetail;
  source: DataSource;
}) {
  const { badge, label: badgeLabel } = sourceBadge(source);
  const ind = detail.indicators;
  const inst = detail.instrument;
  const labels = detail.dates.map(shortDate);
  const score = ind.score;
  const f = detail.fundamentals;

  const peerCols: Array<Column<PeerRow>> = [
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
      key: "last",
      header: "Last",
      sortValue: (r) => r.last,
      render: (r) => fmt(r.last),
    },
    {
      key: "r13",
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
        <span className={cls(r.rs_vs_index_13w)}>{pct(r.rs_vs_index_13w)}</span>
      ),
    },
    {
      key: "rsi",
      header: "RSI 14",
      sortValue: (r) => r.rsi14 ?? -1,
      render: (r) => fmt(r.rsi14, 1),
    },
    {
      key: "atr",
      header: "ATR %",
      sortValue: (r) => r.atr_pct ?? -1,
      render: (r) => fmt(r.atr_pct),
    },
    {
      key: "score",
      header: "Setup",
      sortValue: (r) => r.setup_score ?? -1,
      render: (r) =>
        r.setup_score == null ? (
          <span style={{ color: "var(--muted)" }}>not scored</span>
        ) : (
          fmt(r.setup_score, 0)
        ),
    },
  ];

  return (
    <>
      <div className="grid g4" style={{ marginBottom: 14 }}>
        <StatTile
          label={
            <>
              <InstrumentBadge instrument={inst} /> · last
            </>
          }
          badge={badge}
          badgeLabel={badgeLabel}
          value={`$${fmt(ind.close)}`}
          detail={
            <>
              <span className={cls(ind.change_pct)}>{pct(ind.change_pct)}</span>{" "}
              today · {pct(ind.trend.pct_from_52w_high)} from 6m high
            </>
          }
        />
        <StatTile
          label="RSI 14"
          value={fmt(ind.momentum.rsi14, 1)}
          detail={
            ind.momentum.gated
              ? "Gated — ADX below 20, the trend is too weak to read momentum from"
              : `Regime read: ${ind.momentum.rsi_regime ?? "unknown"}`
          }
        />
        <StatTile
          label="ATR 14"
          value={`$${fmt(ind.volatility.atr14)}`}
          detail={`${fmt(ind.volatility.atr_pct)}% of price — drives stop distance`}
        />
        <StatTile
          label="Swing setup score"
          value={score ? fmt(score.total, 0) : "—"}
          detail={
            score
              ? `${score.verdict} · components below, never a black box`
              : "Not scored"
          }
        />
      </div>

      <Card
        title={<>{inst.symbol} · price with 20 &amp; 50 EMA</>}
        badge={badge}
        badgeLabel={badgeLabel}
        caption="Six months of daily bars. Close, EMA 20 and EMA 50 are all prices, so they share one axis — there is no second scale here."
      >
        <Legend
          items={[
            { color: "var(--s1)", label: "Close" },
            { color: "var(--s2)", label: "EMA 20" },
            { color: "var(--s3)", label: "EMA 50" },
          ]}
        />
        <TableView
          chart={
            <PriceChart
              ariaLabel={`${inst.symbol} daily close with 20 and 50 period exponential moving averages, six months.`}
              dates={detail.dates}
              height={320}
              series={[
                { label: "Close", token: "--s1", values: detail.close },
                { label: "EMA 20", token: "--s2", values: detail.ema20 },
                { label: "EMA 50", token: "--s3", values: detail.ema50 },
              ]}
            />
          }
          table={
            <table>
              <thead>
                <tr>
                  <th>Date</th>
                  <th>Close</th>
                  <th>EMA 20</th>
                  <th>EMA 50</th>
                  <th>RSI</th>
                  <th>Volume</th>
                </tr>
              </thead>
              <tbody>
                {detail.dates
                  .map((d, i) => (
                    <tr key={d}>
                      <td>{d}</td>
                      <td>{fmt(detail.close[i])}</td>
                      <td>{fmt(detail.ema20[i])}</td>
                      <td>{fmt(detail.ema50[i])}</td>
                      <td>
                        {detail.rsi14[i] == null
                          ? "—"
                          : fmt(detail.rsi14[i], 1)}
                      </td>
                      <td>{compact(detail.volume[i])}</td>
                    </tr>
                  ))
                  .reverse()}
              </tbody>
            </table>
          }
        />
      </Card>

      <div className="grid g2">
        <Card
          title="RSI 14"
          badge={badge}
          badgeLabel={badgeLabel}
          caption="Bands at 30 / 70. Gated by ADX — greyed when the trend is too weak to trust it."
        >
          <TableView
            chart={
              <LineChart
                ariaLabel={`${inst.symbol} 14-period relative strength index with bands at 30 and 70.`}
                dates={labels}
                height={210}
                min={0}
                max={100}
                ticks={4}
                bands={[30, 70]}
                label={false}
                formatValue={(v) => fmt(v, 1)}
                series={[{ d: detail.rsi14, c: "var(--s1)", lab: "RSI" }]}
              />
            }
            table={
              <table>
                <thead>
                  <tr>
                    <th>Date</th>
                    <th>RSI 14</th>
                  </tr>
                </thead>
                <tbody>
                  {detail.dates
                    .map((d, i) => (
                      <tr key={d}>
                        <td>{d}</td>
                        <td>
                          {detail.rsi14[i] == null
                            ? "—"
                            : fmt(detail.rsi14[i], 1)}
                        </td>
                      </tr>
                    ))
                    .reverse()}
                </tbody>
              </table>
            }
          />
        </Card>

        <Card
          title="MACD histogram (12,26,9)"
          badge={badge}
          badgeLabel={badgeLabel}
          caption="Diverging encoding: one hue each side of a neutral zero line. These are series colours — a negative bar is not an error state."
        >
          <TableView
            chart={
              <HistChart
                ariaLabel={`${inst.symbol} MACD histogram, twelve twenty-six nine.`}
                dates={labels}
                values={detail.macd_hist}
              />
            }
            table={
              <table>
                <thead>
                  <tr>
                    <th>Date</th>
                    <th>Histogram</th>
                  </tr>
                </thead>
                <tbody>
                  {detail.dates
                    .map((d, i) => (
                      <tr key={d}>
                        <td>{d}</td>
                        <td>{fmt(detail.macd_hist[i], 3)}</td>
                      </tr>
                    ))
                    .reverse()}
                </tbody>
              </table>
            }
          />
        </Card>
      </div>

      <div className="grid g2">
        <Card
          title="Signal table"
          badge={badge}
          badgeLabel={badgeLabel}
          caption="Computed from the same bars — plain English, with the number beside it."
        >
          {detail.signals.map((s) => (
            <div className="kv" key={s.label}>
              <span className="k">
                <b style={{ color: "var(--ink)" }}>{s.label}</b> — {s.detail}
              </span>
              <span className="v">
                <StatusChip
                  tone={toneFromSeverity(s.severity)}
                  icon={s.chip_icon}
                  label={s.chip_label}
                />
              </span>
            </div>
          ))}
          <div style={{ marginTop: 12 }}>
            <ReconciliationBadge recs={ind.reconciliation} />
          </div>
        </Card>

        <Card
          title="Setup score breakdown"
          caption="Weighted blend, always shown open. Relative strength carries the most weight."
        >
          {score ? (
            <>
              {score.components.map((c) => (
                <ScoreBar
                  key={c.name}
                  label={c.name}
                  sublabel={`${Math.round(c.weight * 100)}%`}
                  value={c.value}
                />
              ))}
              <ScoreBar
                label="Composite"
                value={score.total}
                display={fmt(score.total, 0)}
                emphasis
              />
              {score.components.find((c) => c.note) ? (
                <p className="cap" style={{ margin: "12px 0 0" }}>
                  {score.components.find((c) => c.note)?.note}
                </p>
              ) : null}
            </>
          ) : (
            <p className="cap">
              No score yet — the indicator set is incomplete for this contract.
            </p>
          )}
        </Card>
      </div>

      <div className="grid g2">
        <Card
          title="Fundamentals"
          badge={badge}
          badgeLabel={badgeLabel}
          caption="The handful that change a swing decision. Everything else is noise at this horizon."
        >
          {f ? (
            <>
              <div className="kv">
                <span className="k">Forward P/E</span>
                <span className="v">{fmt(f.forward_pe)}</span>
              </div>
              <div className="kv">
                <span className="k">EPS growth</span>
                <span className={`v ${cls(f.eps_growth_pct)}`}>
                  {pct(f.eps_growth_pct)}
                </span>
              </div>
              <div className="kv">
                <span className="k">Revenue growth</span>
                <span className={`v ${cls(f.revenue_growth_pct)}`}>
                  {pct(f.revenue_growth_pct)}
                </span>
              </div>
              <div className="kv">
                <span className="k">Next earnings</span>
                <span className="v">
                  {f.next_earnings_date ?? "—"}
                  {f.days_to_earnings != null
                    ? ` · ${f.days_to_earnings}d`
                    : ""}
                </span>
              </div>
              <div className="kv">
                <span className="k">Short interest</span>
                <span className="v">
                  {fmt(f.short_interest_pct)}% · {fmt(f.days_to_cover, 1)}d to
                  cover
                </span>
              </div>
              <div className="kv">
                <span className="k">Analyst target</span>
                <span className="v">
                  ${fmt(f.analyst_target)}{" "}
                  <span className={cls(f.upside_to_target_pct)}>
                    ({pct(f.upside_to_target_pct)})
                  </span>
                </span>
              </div>
              <div className="kv">
                <span className="k">Float</span>
                <span className="v">{compact(f.float_shares)}</span>
              </div>
            </>
          ) : (
            <p className="cap">No fundamentals for this contract.</p>
          )}
        </Card>

        <Card
          title="Peer comparison"
          badge={badge}
          badgeLabel={badgeLabel}
          caption={`${detail.peers_basis} Ranked on relative strength, not on absolute move.`}
        >
          <DataTable
            columns={peerCols}
            rows={detail.peers}
            getRowKey={(r) => String(r.conid)}
            initialSortKey="rs13"
          />
        </Card>
      </div>
    </>
  );
}
