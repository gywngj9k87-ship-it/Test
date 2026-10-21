import type { ProviderResult } from "./types.ts";

export function report(r: ProviderResult, title: string): string {
  const meta = `model \`${r.model}\` · effort \`${r.effort}\` · ${r.usage.inputTokens} in / ${r.usage.outputTokens} out tokens · ${(r.durationMs / 1000).toFixed(1)}s`;
  const warn = r.warning ? `\n> **Warning:** ${r.warning}\n` : "";
  return `# ${title}\n\n${meta}\n${warn}\n${r.text}\n`;
}
