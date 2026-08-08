import Link from "next/link";
import { notFound } from "next/navigation";
import DeepDiveView from "./deep-dive-view";
import Card from "@/components/Card";
import { getInstrument } from "@/lib/api";
import { MOCK_DETAILS } from "@/lib/mock";

/**
 * Deep dive, routed on CONID.
 *
 * Not on symbol, and this is the one route where that matters most: `SOXL` is
 * a 4× LSE ETP and a 3× US ETF, `MAGS` is a 1× US ETF and a −3× LSE inverse.
 * A symbol route would happily show you the wrong instrument.
 */

export function generateStaticParams() {
  return Object.keys(MOCK_DETAILS).map((conid) => ({ conid }));
}

export async function generateMetadata({
  params,
}: {
  params: { conid: string };
}) {
  const detail = MOCK_DETAILS[Number(params.conid)];
  return {
    title: detail
      ? `${detail.instrument.symbol} · deep dive · Swing Dashboard`
      : `Contract ${params.conid} · deep dive`,
  };
}

export default async function DeepDivePage({
  params,
}: {
  params: { conid: string };
}) {
  const conid = Number(params.conid);
  if (!Number.isFinite(conid)) notFound();

  const detail = await getInstrument(conid, { revalidate: 60 });

  if (!detail.data) {
    // No bars for this contract. We say so. We do NOT quietly render some other
    // instrument's chart under this contract's heading.
    return (
      <Card
        title={`Contract ${conid}`}
        badge="mock"
        caption="No indicator set for this contract."
      >
        <p style={{ color: "var(--ink-2)", fontSize: 12.5, margin: 0 }}>
          The backend at{" "}
          <code>
            {process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000"}
          </code>{" "}
          is not answering, and the mock data carries daily bars for two
          contracts only —{" "}
          {Object.values(MOCK_DETAILS)
            .map((d) => `${d.instrument.symbol} (${d.instrument.conid})`)
            .join(" and ")}
          . Rather than show you a different instrument under this heading, the
          panel is empty.
        </p>
        <p style={{ marginTop: 12 }}>
          {Object.values(MOCK_DETAILS).map((d) => (
            <Link
              key={d.instrument.conid}
              href={`/deep-dive/${d.instrument.conid}`}
              className="btn"
              style={{
                marginRight: 8,
                display: "inline-block",
                textDecoration: "none",
              }}
            >
              {d.instrument.symbol} · {d.instrument.exchange}
            </Link>
          ))}
        </p>
      </Card>
    );
  }

  return <DeepDiveView detail={detail.data} source={detail.source} />;
}
