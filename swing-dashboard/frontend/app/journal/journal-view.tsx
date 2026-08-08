"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState, type FormEvent, type ReactNode } from "react";
import Card from "@/components/Card";
import DataTable, { type Column } from "@/components/DataTable";
import StatTile from "@/components/StatTile";
import StatusChip from "@/components/StatusChip";
import { cls, fmt, longDate, pct, usd } from "@/lib/format";
import { postJournal, type DataSource } from "@/lib/api";
import type { JournalEntry, JournalStats, SetupPerformance } from "@/lib/types";

/**
 * The journal is the user's own data, not an IBKR feed — so it does not borrow
 * the "● IBKR / snapshot" badge. Live means the entries came back from the
 * service; mock means these are illustrative sample trades, and the badge says
 * exactly that so nothing invented is mistaken for a real trade.
 */
function journalBadge(source: DataSource): { badge: "live" | "mock"; label: string } {
  return source === "live"
    ? { badge: "live", label: "● Your journal" }
    : { badge: "mock", label: "Sample trades" };
}

/** A closed trade's outcome, always as icon + label — never colour alone. */
function outcomeChip(e: JournalEntry): ReactNode {
  if (e.closed_at == null) {
    return <StatusChip tone="neutral" icon="○" label="Open" />;
  }
  const outcome = e.realized_pnl ?? e.r_multiple ?? 0;
  if (outcome > 0) return <StatusChip tone="good" label="Win" />;
  if (outcome < 0) return <StatusChip tone="serious" label="Loss" />;
  return <StatusChip tone="neutral" icon="=" label="Scratch" />;
}

/** Identity is (conid, exchange), never the symbol. The journal row carries no
 *  exchange, so it shows the conid — the real key — beside the ticker. */
function TradeIdentity({ e }: { e: JournalEntry }) {
  return (
    <Link
      href={`/deep-dive/${e.conid}`}
      style={{ color: "var(--ink)", textDecoration: "none", whiteSpace: "nowrap" }}
    >
      <span className="tk">{e.symbol}</span>
      <span className="lv" style={{ color: "var(--muted)" }}>#{e.conid}</span>
    </Link>
  );
}

export default function JournalView({
  entries,
  stats,
  source,
}: {
  entries: JournalEntry[];
  stats: JournalStats;
  source: DataSource;
}) {
  const { badge, label: badgeLabel } = journalBadge(source);

  const rMult = (r: number | null): ReactNode =>
    r == null ? "—" : <span className={cls(r)}>{fmt(r, 2)}R</span>;

  // ─────────────── the compounding panel: which setups actually work ───────────────
  const setupCols: Array<Column<SetupPerformance>> = [
    {
      key: "setup",
      header: "Setup (score at entry)",
      align: "left",
      sortValue: (s) => s.setup,
      render: (s) => (
        <>
          <span className="tk">{s.setup}</span>
          {s.setup === stats.best_setup ? (
            <span style={{ marginLeft: 8 }}>
              <StatusChip tone="neutral" icon="★" label="Best" title="Highest expectancy at ≥3 closed trades" />
            </span>
          ) : null}
        </>
      ),
    },
    { key: "trades", header: "Closed", sortValue: (s) => s.trades, render: (s) => fmt(s.trades, 0) },
    {
      key: "win",
      header: "Win rate",
      sortValue: (s) => s.win_rate,
      render: (s) => `${fmt(s.win_rate * 100, 0)}%`,
    },
    {
      key: "avgwin",
      header: "Avg win",
      sortValue: (s) => s.avg_win_r,
      render: (s) => <span className={cls(s.avg_win_r)}>{fmt(s.avg_win_r, 2)}R</span>,
    },
    {
      key: "avgloss",
      header: "Avg loss",
      sortValue: (s) => s.avg_loss_r,
      render: (s) => <span className={cls(s.avg_loss_r)}>{fmt(s.avg_loss_r, 2)}R</span>,
    },
    {
      key: "exp",
      header: "Expectancy",
      title: "Mean R-multiple across the bucket",
      sortValue: (s) => s.expectancy_r,
      render: (s) => <span className={cls(s.expectancy_r)}>{fmt(s.expectancy_r, 2)}R</span>,
    },
    {
      key: "pnl",
      header: "Realised P&L",
      sortValue: (s) => s.total_pnl,
      render: (s) => <span className={cls(s.total_pnl)}>{usd(s.total_pnl)}</span>,
    },
  ];

  // ─────────────── the log itself ───────────────
  const logCols: Array<Column<JournalEntry>> = [
    {
      key: "sym",
      header: "Trade",
      align: "left",
      sortValue: (e) => e.symbol,
      render: (e) => <TradeIdentity e={e} />,
    },
    {
      key: "status",
      header: "Outcome",
      align: "left",
      sortValue: (e) => (e.closed_at == null ? 2 : (e.realized_pnl ?? 0) > 0 ? 1 : 0),
      render: outcomeChip,
    },
    {
      key: "dir",
      header: "Side",
      align: "left",
      sortValue: (e) => e.direction,
      render: (e) => e.direction,
    },
    {
      key: "score",
      header: "Score",
      title: "Setup score at entry",
      sortValue: (e) => e.entry_snapshot.setup_score ?? -1,
      render: (e) =>
        e.entry_snapshot.setup_score == null ? "—" : fmt(e.entry_snapshot.setup_score, 0),
    },
    { key: "entry", header: "Entry", sortValue: (e) => e.entry_price, render: (e) => fmt(e.entry_price) },
    {
      key: "exit",
      header: "Exit",
      sortValue: (e) => e.exit_price ?? 0,
      render: (e) => (e.exit_price == null ? "—" : fmt(e.exit_price)),
    },
    {
      key: "size",
      header: "Size",
      sortValue: (e) => e.size,
      render: (e) => fmt(e.size, e.size % 1 ? 4 : 0),
    },
    { key: "r", header: "R", title: "Realised R-multiple", sortValue: (e) => e.r_multiple ?? 0, render: (e) => rMult(e.r_multiple) },
    {
      key: "pnl",
      header: "P&L",
      sortValue: (e) => e.realized_pnl ?? 0,
      render: (e) => (e.realized_pnl == null ? "—" : <span className={cls(e.realized_pnl)}>{usd(e.realized_pnl)}</span>),
    },
    {
      key: "opened",
      header: "Opened",
      align: "left",
      sortValue: (e) => e.opened_at,
      render: (e) => longDate(e.opened_at.slice(0, 10)),
    },
  ];

  return (
    <>
      <div className="note" style={{ marginTop: 0 }}>
        <b>Why this tab exists.</b> Every entry snapshots the dashboard&rsquo;s own
        setup score the moment you opened the trade. Group the closed trades by
        that score and the journal stops being a diary and becomes a running
        back-test of the app&rsquo;s signal against the outcomes <i>you</i> actually
        got. If your high-score setups don&rsquo;t out-earn your low-score ones, the
        score isn&rsquo;t earning its place on the screen — and this is where that
        would show.
      </div>

      <div className="grid g4" style={{ marginBottom: 14 }}>
        <StatTile
          label="Expectancy"
          value={stats.expectancy_r == null ? "—" : `${fmt(stats.expectancy_r, 2)}R`}
          valueClass={cls(stats.expectancy_r)}
          detail={`per closed trade · avg win ${
            stats.avg_win_r == null ? "—" : `${fmt(stats.avg_win_r, 2)}R`
          } / avg loss ${stats.avg_loss_r == null ? "—" : `${fmt(stats.avg_loss_r, 2)}R`}`}
        />
        <StatTile
          label="Win rate"
          value={stats.win_rate == null ? "—" : `${fmt(stats.win_rate * 100, 0)}%`}
          detail={`${stats.closed_trades} closed · ${stats.open_positions} open`}
        />
        <StatTile
          label="Realised P&L"
          value={usd(stats.total_realized_pnl)}
          valueClass={cls(stats.total_realized_pnl)}
          detail="closed trades only"
        />
        <StatTile
          label="Best setup"
          value={stats.best_setup ?? "—"}
          detail={
            stats.best_setup == null
              ? "no bucket has ≥3 closed trades yet"
              : "highest expectancy at a real sample"
          }
        />
      </div>

      <Card
        badge={badge}
        badgeLabel={badgeLabel}
        title="Which of your setups actually work"
        caption="Closed trades grouped by the app's setup score at entry. Expectancy is the mean R-multiple across the bucket — the number that compounds, not the hit rate."
      >
        {stats.sample_warning ? (
          <div className="note" style={{ marginTop: 0 }}>
            <b>Provisional.</b> {stats.sample_warning}
          </div>
        ) : null}
        <DataTable
          columns={setupCols}
          rows={stats.by_setup}
          getRowKey={(s) => s.setup}
          initialSortKey="exp"
          emptyMessage="No closed trades yet — the breakdown appears once a position is closed."
        />
      </Card>

      <Card
        badge={badge}
        badgeLabel={badgeLabel}
        title="Trade log"
        caption="Every entry, newest first. The ticker links to the deep dive on its contract id — the journal keys on conid, never the symbol."
        actions={<AddTrade />}
      >
        <DataTable
          columns={logCols}
          rows={entries}
          getRowKey={(e) => e.id}
          initialSortKey="opened"
          emptyMessage="No trades logged yet. Add one to start the record."
        />
      </Card>
    </>
  );
}

/**
 * Log a new (open) trade. POSTs to the service — there is no offline fallback,
 * because writing into a mock would be a lie, so with no backend attached this
 * reports the failure instead of pretending it saved.
 */
function AddTrade() {
  const router = useRouter();
  const [open, setOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [done, setDone] = useState(false);

  async function onSubmit(ev: FormEvent<HTMLFormElement>) {
    ev.preventDefault();
    setBusy(true);
    setError(null);
    setDone(false);
    const f = new FormData(ev.currentTarget);
    const symbol = String(f.get("symbol") || "").trim().toUpperCase();
    const conid = Number(f.get("conid"));
    const score = f.get("score") === "" ? null : Number(f.get("score"));
    const entry: JournalEntry = {
      id: `${symbol || "TRADE"}-${Date.now()}`,
      conid,
      symbol,
      opened_at: new Date().toISOString(),
      closed_at: null,
      direction: String(f.get("direction") || "long") === "short" ? "short" : "long",
      entry_price: Number(f.get("entry_price")),
      exit_price: null,
      size: Number(f.get("size")),
      thesis: String(f.get("thesis") || "").trim(),
      exit_reason: null,
      entry_snapshot: score == null ? {} : { setup_score: score },
      realized_pnl: null,
      r_multiple: null,
    };
    try {
      await postJournal(entry);
      setDone(true);
      (ev.target as HTMLFormElement).reset();
      router.refresh(); // re-fetch the log + stats from the service
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  }

  if (!open) {
    return (
      <button type="button" className="btn" onClick={() => setOpen(true)}>
        + Log a trade
      </button>
    );
  }

  const field: React.CSSProperties = {
    background: "var(--plane)",
    border: "1px solid var(--ring)",
    color: "var(--ink)",
    borderRadius: 8,
    padding: "6px 9px",
    font: "inherit",
    fontSize: 12.5,
  };

  return (
    <form
      onSubmit={onSubmit}
      style={{ display: "grid", gap: 8, minWidth: 280, maxWidth: 360 }}
    >
      <div style={{ display: "flex", gap: 8 }}>
        <input name="symbol" placeholder="Symbol" required style={{ ...field, flex: 2 }} aria-label="Symbol" />
        <input name="conid" type="number" placeholder="conid" required style={{ ...field, flex: 2 }} aria-label="Contract id" />
      </div>
      <div style={{ display: "flex", gap: 8 }}>
        <select name="direction" defaultValue="long" style={{ ...field, flex: 1 }} aria-label="Direction">
          <option value="long">long</option>
          <option value="short">short</option>
        </select>
        <input name="entry_price" type="number" step="any" placeholder="Entry" required style={{ ...field, flex: 1 }} aria-label="Entry price" />
        <input name="size" type="number" step="any" placeholder="Size" required style={{ ...field, flex: 1 }} aria-label="Size" />
        <input name="score" type="number" step="any" placeholder="Score" style={{ ...field, flex: 1 }} aria-label="Setup score at entry" />
      </div>
      <textarea name="thesis" placeholder="Thesis — why this trade, in one line" required rows={2} style={{ ...field, resize: "vertical" }} aria-label="Thesis" />
      <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
        <button type="submit" className="btn" disabled={busy}>
          {busy ? "Saving…" : "Save entry"}
        </button>
        <button type="button" className="btn" onClick={() => setOpen(false)} disabled={busy}>
          Cancel
        </button>
        {done ? <StatusChip tone="good" label="Saved" /> : null}
      </div>
      {error ? (
        <div className="note" style={{ marginTop: 0 }}>
          <b>Not saved.</b> The service did not accept the write, so nothing was
          recorded: <code>{error}</code>. A journal entry is only real once the
          backend has it — start the API and try again.
        </div>
      ) : null}
    </form>
  );
}
