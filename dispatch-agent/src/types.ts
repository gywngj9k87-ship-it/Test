export type ProviderName = "claude" | "openai";

// Claude: output_config.effort. Opus 5.5 defaults to "medium" if unset.
export const CLAUDE_EFFORTS = ["low", "medium", "high", "xhigh", "max"] as const;
export type ClaudeEffort = (typeof CLAUDE_EFFORTS)[number];

// OpenAI: reasoning.effort. Not every model accepts every level
// (e.g. "none"/"minimal"/"xhigh" are model-specific) - the API rejects unsupported ones.
export const OPENAI_EFFORTS = ["none", "minimal", "low", "medium", "high", "xhigh", "max"] as const;
export type OpenAIEffort = (typeof OPENAI_EFFORTS)[number];

export interface ProviderSettings<E> {
  model: string;
  effort: E;
}

export interface DispatchConfig {
  providers: ProviderName[];
  claude: ProviderSettings<ClaudeEffort>;
  openai: ProviderSettings<OpenAIEffort>;
  /** Upper bound on total characters of file content sent per task. */
  maxChars: number;
  outDir: string;
}

export interface SourceFile {
  path: string;
  content: string;
}

export interface Task {
  instruction: string;
  files: SourceFile[];
}

export interface ProviderResult {
  provider: ProviderName;
  model: string;
  effort: string;
  text: string;
  /** Set when the response was cut short or declined. */
  warning?: string;
  usage: { inputTokens: number; outputTokens: number };
  durationMs: number;
}

export interface RunOptions {
  /** Called with each chunk of answer text as it streams in. */
  onText?: (delta: string) => void;
  signal?: AbortSignal;
}
