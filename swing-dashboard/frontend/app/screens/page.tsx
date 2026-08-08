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
  searchParams?: { screen?: string };
}) {
  const requested = searchParams?.screen as ScreenName | undefined;
  const active: ScreenName =
    requested && SCREEN_NAMES.includes(requested)
      ? requested
      : ScreenName.RS_LEADERS;

  const result = await getScreen(active, { revalidate: 300 });

  return (
    <ScreensView
      screens={SCREENS}
      active={active}
      result={result.data}
      source={result.source}
    />
  );
}
