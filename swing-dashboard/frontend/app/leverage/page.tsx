import LeverageView from "./leverage-view";
import { getCollisions, getLeverage, getRoundTrip } from "@/lib/api";

export const metadata = { title: "Leverage · Swing Dashboard" };

/** The §2c view: leveraged ETPs as their own instrument class. */
export default async function LeveragePage() {
  const [views, roundTrip, collisions] = await Promise.all([
    getLeverage({ revalidate: 300 }),
    getRoundTrip({ revalidate: 3600 }),
    getCollisions({ revalidate: 3600 }),
  ]);

  return (
    <LeverageView
      views={views.data}
      roundTrip={roundTrip.data}
      collisions={collisions.data}
      source={views.source}
    />
  );
}
