import IncomeView from "./income-view";
import { getIncome } from "@/lib/api";

export const metadata = { title: "Income sleeve · Swing Dashboard" };

export default async function IncomePage() {
  const income = await getIncome({ revalidate: 900 });
  return <IncomeView rows={income.data} source={income.source} />;
}
