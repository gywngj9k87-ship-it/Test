import OpenAI from "openai";
import type { RunOptions, OpenAIEffort, ProviderResult, ProviderSettings } from "../types.ts";

let client: OpenAI | undefined;

export async function runOpenAI(
  settings: ProviderSettings<OpenAIEffort>,
  system: string,
  userMessage: string,
  { onText, signal }: RunOptions = {},
): Promise<ProviderResult> {
  client ??= new OpenAI();
  const started = Date.now();

  const stream = client.responses.stream({
    model: settings.model,
    reasoning: { effort: settings.effort },
    instructions: system,
    input: userMessage,
  }, { signal });
  if (onText) stream.on("response.output_text.delta", (e) => onText(e.delta));
  const response = await stream.finalResponse();

  const warning =
    response.status === "incomplete"
      ? `Response incomplete: ${response.incomplete_details?.reason ?? "unknown reason"}.`
      : undefined;

  return {
    provider: "openai",
    model: response.model,
    effort: settings.effort,
    text: response.output_text,
    warning,
    usage: {
      inputTokens: response.usage?.input_tokens ?? 0,
      outputTokens: response.usage?.output_tokens ?? 0,
    },
    durationMs: Date.now() - started,
  };
}
