import Anthropic from "@anthropic-ai/sdk";
import type { RunOptions, ClaudeEffort, ProviderResult, ProviderSettings } from "../types.ts";

// Models that accept the server-side refusal fallback ("default" routing).
const FALLBACK_MODELS = new Set(["claude-fable-5-1", "claude-opus-5-5", "claude-opus-5", "claude-sonnet-5-5"]);

let client: Anthropic | undefined;

export async function runClaude(
  settings: ProviderSettings<ClaudeEffort>,
  system: string,
  userMessage: string,
  { onText, signal }: RunOptions = {},
): Promise<ProviderResult> {
  client ??= new Anthropic();
  const started = Date.now();
  const useFallbacks = FALLBACK_MODELS.has(settings.model);

  // Streaming so long reviews don't hit HTTP timeouts.
  const stream = client.beta.messages.stream({
    model: settings.model,
    max_tokens: 64000,
    thinking: { type: "adaptive" },
    output_config: { effort: settings.effort },
    system,
    messages: [{ role: "user", content: userMessage }],
    ...(useFallbacks && {
      betas: ["server-side-fallback-2026-07-01"],
      fallbacks: "default" as const,
    }),
  }, { signal });
  if (onText) stream.on("text", (delta) => onText(delta));
  const message = await stream.finalMessage();

  const text = message.content
    .filter((b): b is Anthropic.Beta.BetaTextBlock => b.type === "text")
    .map((b) => b.text)
    .join("");

  let warning: string | undefined;
  if (message.stop_reason === "refusal") {
    warning = `Declined (${message.stop_details?.category ?? "unspecified"}): ${message.stop_details?.explanation ?? ""}`;
  } else if (message.stop_reason === "max_tokens") {
    warning = "Output hit max_tokens and is truncated.";
  }
  if (message.model !== settings.model) {
    warning = [warning, `Served by fallback model ${message.model}.`].filter(Boolean).join(" ");
  }

  return {
    provider: "claude",
    model: message.model,
    effort: settings.effort,
    text,
    warning,
    usage: { inputTokens: message.usage.input_tokens, outputTokens: message.usage.output_tokens },
    durationMs: Date.now() - started,
  };
}
