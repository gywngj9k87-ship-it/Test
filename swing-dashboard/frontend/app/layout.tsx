import type { Metadata } from "next";
import "./globals.css";
import { FilterProvider } from "@/components/GlobalFilters";
import TabNav from "@/components/TabNav";
import ThemeToggle, {
  ThemeProvider,
  THEME_BOOT_SCRIPT,
} from "@/components/ThemeToggle";
import { getWatchlists } from "@/lib/api";

export const metadata: Metadata = {
  title: "Swing · Income · Leverage Dashboard",
  description:
    "Market breadth, swing setups, portfolio risk and leveraged-ETP decay, keyed on IBKR contract ids.",
};

export default async function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  const watchlists = await getWatchlists({ revalidate: 300 });

  return (
    <html lang="en" suppressHydrationWarning>
      <head>
        {/* Applies a stored theme before first paint so an explicit choice
            never flashes the wrong palette. With nothing stored we set no
            attribute and the prefers-color-scheme block in globals.css wins. */}
        <script dangerouslySetInnerHTML={{ __html: THEME_BOOT_SCRIPT }} />
      </head>
      <body>
        <ThemeProvider>
          <div className="wrap">
            <header className="app-header">
              <div>
                <h1>Swing · Income · Leverage Dashboard</h1>
                <p className="sub">
                  Spec v0.3 · every instrument keyed on contract id, never on
                  symbol
                </p>
              </div>
              <div className="spacer" />
              <span
                className={`pill ${watchlists.source === "live" ? "live" : "mock"}`}
              >
                {watchlists.source === "live" ? "● IBKR" : "Mock data"}
              </span>
              <ThemeToggle />
            </header>

            {watchlists.source === "mock" ? (
              <div className="note">
                <b>No backend attached.</b> The API at{" "}
                <code>
                  {process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000"}
                </code>{" "}
                did not answer, so every panel is rendering the data extracted
                from the approved mockup — real IBKR figures as at the
                2026-08-06 close for breadth, rotation, the drivers table, BABA
                and KKR technicals, the book, and the full leveraged-ETP decay
                analysis. The headline tape and the income sleeve were
                placeholders in the mockup and are still placeholders here.
                Nothing on screen is presented as live when it is not.
              </div>
            ) : null}

            <FilterProvider watchlists={watchlists.data}>
              <TabNav />
              {children}
            </FilterProvider>

            <p className="foot">
              Not investment advice, and not a live terminal. Historical figures
              are history, not forecast. Status colours always ship with an icon
              and a label; no chart on this dashboard uses two y-axes.
            </p>
          </div>
        </ThemeProvider>
      </body>
    </html>
  );
}
