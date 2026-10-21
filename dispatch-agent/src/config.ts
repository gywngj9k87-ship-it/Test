import { existsSync, readFileSync } from "node:fs";
import {
  CLAUDE_EFFORTS,
  OPENAI_EFFORTS,
  type ClaudeEffort,
  type DispatchConfig,
  type OpenAIEffort,
  type ProviderName,
} from "./types.ts";

export const DEFAULT_CONFIG: DispatchConfig = {
  providers: ["claude", "openai"],
  claude: { model: "claude-opus-5-5", effort: "high" },
  openai: { model: "gpt-5.5", effort: "high" },
  maxChars: 400_000,
  outDir: "reviews",
};

export interface Overrides {
  providers?: string;
  claudeModel?: string;
  claudeEffort?: string;
  openaiModel?: string;
  openaiEffort?: string;
  maxChars?: string;
  outDir?: string;
}

function oneOf<T extends string>(value: string, allowed: readonly T[], label: string): T {
  if (!(allowed as readonly string[]).includes(value)) {
    throw new Error(`Invalid ${label} "${value}". Use one of: ${allowed.join(", ")}.`);
  }
  return value as T;
}

/** Defaults <- config file <- CLI flags. */
export function loadConfig(configPath: string | undefined, o: Overrides): DispatchConfig {
  const file = configPath ?? "dispatch.config.json";
  const fromFile: Partial<DispatchConfig> = existsSync(file)
    ? JSON.parse(readFileSync(file, "utf8"))
    : {};
  if (configPath && !existsSync(file)) throw new Error(`Config file not found: ${file}`);

  const c: DispatchConfig = {
    ...DEFAULT_CONFIG,
    ...fromFile,
    claude: { ...DEFAULT_CONFIG.claude, ...fromFile.claude },
    openai: { ...DEFAULT_CONFIG.openai, ...fromFile.openai },
  };

  if (o.providers) c.providers = o.providers.split(",").map((p) => p.trim()) as ProviderName[];
  if (o.claudeModel) c.claude.model = o.claudeModel;
  if (o.claudeEffort) c.claude.effort = o.claudeEffort as ClaudeEffort;
  if (o.openaiModel) c.openai.model = o.openaiModel;
  if (o.openaiEffort) c.openai.effort = o.openaiEffort as OpenAIEffort;
  if (o.maxChars) c.maxChars = Number(o.maxChars);
  if (o.outDir) c.outDir = o.outDir;

  c.providers.forEach((p) => oneOf(p, ["claude", "openai"] as const, "provider"));
  oneOf(c.claude.effort, CLAUDE_EFFORTS, "Claude effort");
  oneOf(c.openai.effort, OPENAI_EFFORTS, "OpenAI effort");
  if (!Number.isFinite(c.maxChars) || c.maxChars <= 0) throw new Error("maxChars must be a positive number.");
  return c;
}
