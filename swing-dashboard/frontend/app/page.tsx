import OverviewView from "./overview-view";
import { getEvents, getOverview } from "@/lib/api";
import { MKT_WEEK_LABELS, SEMIS_SERIES } from "@/lib/mock";

export const metadata = { title: "Market overview · Swing Dashboard" };

export default async function MarketOverviewPage() {
  const [overview, events] = await Promise.all([
    getOverview({ revalidate: 60 }),
    getEvents({ revalidate: 60 }),
  ]);

  return (
    <OverviewView
      overview={overview.data}
      events={events.data}
      weekLabels={MKT_WEEK_LABELS}
      semisSeries={SEMIS_SERIES}
      overviewSource={overview.source}
      eventsSource={events.source}
    />
  );
}
