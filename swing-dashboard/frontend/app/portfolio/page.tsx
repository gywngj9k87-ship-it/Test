import PortfolioView from "./portfolio-view";
import { getPortfolio } from "@/lib/api";

export const metadata = { title: "Portfolio · Swing Dashboard" };

export default async function PortfolioPage() {
  const snapshot = await getPortfolio({ revalidate: 30 });
  return <PortfolioView snapshot={snapshot.data} source={snapshot.source} />;
}
