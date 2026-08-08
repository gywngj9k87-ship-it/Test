import { redirect } from "next/navigation";
import { DEFAULT_CONID } from "@/lib/mock";

/** /deep-dive with no contract lands on the default one. */
export default function DeepDiveIndex() {
  redirect(`/deep-dive/${DEFAULT_CONID}`);
}
