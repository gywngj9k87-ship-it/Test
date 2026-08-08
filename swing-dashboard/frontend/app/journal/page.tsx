import JournalView from "./journal-view";
import { getJournal, getJournalStats } from "@/lib/api";

export const metadata = { title: "Journal · Swing Dashboard" };

/**
 * The trade journal — the feature that compounds. Each entry snapshots the
 * app's setup score at entry, so the stats panel can say which of the user's
 * own setups actually work rather than which ought to. Reads the log and its
 * derived stats in parallel; both fall back to the illustrative sample set
 * when no backend is attached, and the view labels that honestly.
 */
export default async function JournalPage() {
  const [entries, stats] = await Promise.all([
    getJournal({ revalidate: 30 }),
    getJournalStats({ revalidate: 30 }),
  ]);

  return (
    <JournalView
      entries={entries.data}
      stats={stats.data}
      source={entries.source}
    />
  );
}
