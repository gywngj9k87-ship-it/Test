import ScreensView from "./screens-view";
import { getScreen } from "@/lib/api";
import { screenBlurb, screenLabel } from "@/lib/mock";
import { SCREEN_NAMES, ScreenName } from "@/lib/types";

export const metadata = { title: "Screens · Swing Dashboard" };

const SCREENS = SCREEN_NAMES.map((id) => ({
  id,
  label: screenLabel(id),
  blurb: screenBlurb(id),
}));

export default async function ScreensPage({
  searchParams,
}: {
  searchParams?: { screen?: string; scope?: string; watchlist?: string };
}) {
  const requested = searchParams?.screen as ScreenName | undefined;
  const active: ScreenName =
    requested && SCREEN_NAMES.includes(requested)
      ? requested
      : ScreenName.RS_LEADERS;

  // Honour the global filter row: the scope/watchlist come off the URL (set by
  // GlobalFilters) and go straight to the backend query params, which filter
  // the screen's rows by contract id. Undefined keys are dropped by buildUrl,
  // so an unscoped view sends nothing.
  const scope = searchParams?.scope;
  const watchlist = scope === "watchlists" ? searchParams?.watchlist : undefined;

  const result = await getScreen(active, {
    revalidate: 300,
    query: { scope, watchlist },
  });

  return (
    <ScreensView
      screens={SCREENS}
      active={active}
      result={result.data}
      source={result.source}
    />
  );
}
