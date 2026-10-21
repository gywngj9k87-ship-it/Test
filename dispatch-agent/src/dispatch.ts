import { buildUserMessage, SYNTHESIS_PROMPT, SYSTEM_PROMPT } from "./prompt.ts";
import { runClaude } from "./providers/claude.ts";
import { runOpenAI } from "./providers/openai.ts";
import type { DispatchConfig, ProviderName, ProviderResult, Task } from "./types.ts";

export interface DispatchOutcome {
  results: ProviderResult[];
  errors: { provider: ProviderName; error: Error }[];
}

function run(provider: ProviderName, config: DispatchConfig, system: string, user: string) {
  return provider === "claude"
    ? runClaude(config.claude, system, user)
    : runOpenAI(config.openai, system, user);
}

/** Sends the same task to every configured provider in parallel. One failing doesn't cancel the others. */
export async function dispatch(task: Task, config: DispatchConfig): Promise<DispatchOutcome> {
  const user = buildUserMessage(task);
  const settled = await Promise.allSettled(
    config.providers.map((p) => run(p, config, SYSTEM_PROMPT, user)),
  );

  const outcome: DispatchOutcome = { results: [], errors: [] };
  settled.forEach((s, i) => {
    if (s.status === "fulfilled") outcome.results.push(s.value);
    else outcome.errors.push({ provider: config.providers[i], error: s.reason as Error });
  });
  return outcome;
}

/** Asks one provider to merge the individual reviews into a single prioritized list. */
export async function synthesize(
  task: Task,
  results: ProviderResult[],
  by: ProviderName,
  config: DispatchConfig,
): Promise<ProviderResult> {
  const reviews = results
    .map((r) => `<review reviewer="${r.provider} (${r.model}, effort ${r.effort})">\n${r.text}\n</review>`)
    .join("\n\n");
  const user = `${buildUserMessage(task)}\n\n<reviews>\n${reviews}\n</reviews>`;
  return run(by, config, SYNTHESIS_PROMPT, user);
}
