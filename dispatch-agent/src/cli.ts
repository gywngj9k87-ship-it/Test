#!/usr/bin/env node
import { mkdir, readFile, writeFile } from "node:fs/promises";
import path from "node:path";
import { parseArgs } from "node:util";
import { loadConfig } from "./config.ts";
import { dispatch, synthesize } from "./dispatch.ts";
import { collectFiles } from "./files.ts";
import { report } from "./report.ts";
import type { ProviderName } from "./types.ts";

const HELP = `Usage: dispatch [options] <file-or-dir>...

Send a review task about the given files to Claude and/or ChatGPT in parallel.

Task:
  -t, --task <text>          What to do (default: general review with recommendations)
      --task-file <path>     Read the task from a file

Providers:
  -p, --providers <list>     claude, openai, or claude,openai
      --claude-model <id>    e.g. claude-opus-5-5, claude-sonnet-5-5, claude-haiku-5-5
      --claude-effort <lvl>  low | medium | high | xhigh | max
      --openai-model <id>    e.g. gpt-5.5, gpt-5.4-mini
      --openai-effort <lvl>  none | minimal | low | medium | high | xhigh | max (model-dependent)

Output:
  -s, --synthesize           Merge the reviews into one combined report
      --synthesizer <who>    Which provider merges them: claude (default) or openai
  -o, --out <dir>            Where to write Markdown reports (default: reviews)
      --max-chars <n>        Refuse to send more than n characters of file content
  -c, --config <path>        Config file (default: dispatch.config.json if present)
      --dry-run              Show what would be sent, without calling any API
  -h, --help`;

const DEFAULT_TASK = "Review these files and recommend the most valuable improvements.";

async function main(): Promise<number> {
  const { values, positionals } = parseArgs({
    allowPositionals: true,
    options: {
      task: { type: "string", short: "t" },
      "task-file": { type: "string" },
      providers: { type: "string", short: "p" },
      "claude-model": { type: "string" },
      "claude-effort": { type: "string" },
      "openai-model": { type: "string" },
      "openai-effort": { type: "string" },
      synthesize: { type: "boolean", short: "s" },
      synthesizer: { type: "string" },
      out: { type: "string", short: "o" },
      "max-chars": { type: "string" },
      config: { type: "string", short: "c" },
      "dry-run": { type: "boolean" },
      help: { type: "boolean", short: "h" },
    },
  });

  if (values.help || positionals.length === 0) {
    console.log(HELP);
    return values.help ? 0 : 1;
  }

  const config = loadConfig(values.config, {
    providers: values.providers,
    claudeModel: values["claude-model"],
    claudeEffort: values["claude-effort"],
    openaiModel: values["openai-model"],
    openaiEffort: values["openai-effort"],
    maxChars: values["max-chars"],
    outDir: values.out,
  });

  if (values.synthesizer && !["claude", "openai"].includes(values.synthesizer)) {
    throw new Error("--synthesizer must be claude or openai.");
  }

  const instruction = values["task-file"]
    ? (await readFile(values["task-file"], "utf8")).trim()
    : (values.task ?? DEFAULT_TASK);
  const files = await collectFiles(positionals, config.maxChars);
  if (files.length === 0) throw new Error("No readable text files found in the given paths.");

  const chars = files.reduce((n, f) => n + f.content.length, 0);
  console.error(`Task: ${instruction}`);
  console.error(`Files: ${files.length} (${chars.toLocaleString()} chars)`);
  for (const p of config.providers) {
    const s = config[p];
    console.error(`  → ${p}: ${s.model} @ effort ${s.effort}`);
  }
  if (values["dry-run"]) {
    files.forEach((f) => console.error(`    ${f.path}`));
    return 0;
  }

  const task = { instruction, files };
  const { results, errors } = await dispatch(task, config);

  const stamp = new Date().toISOString().replace(/[:.]/g, "-").slice(0, 19);
  await mkdir(config.outDir, { recursive: true });
  const written: string[] = [];
  for (const r of results) {
    const file = path.join(config.outDir, `${stamp}-${r.provider}.md`);
    await writeFile(file, report(r, `Review by ${r.provider}`));
    written.push(file);
    console.error(`✓ ${r.provider} (${r.model}) ${(r.durationMs / 1000).toFixed(1)}s${r.warning ? ` - ${r.warning}` : ""}`);
  }
  for (const e of errors) console.error(`✗ ${e.provider}: ${e.error.message}`);

  if (values.synthesize && results.length > 1) {
    const by = (values.synthesizer ?? "claude") as ProviderName;
    console.error(`Synthesizing with ${by}…`);
    const merged = await synthesize(task, results, by, config);
    const file = path.join(config.outDir, `${stamp}-combined.md`);
    await writeFile(file, report(merged, `Combined review (synthesized by ${by})`));
    written.push(file);
  }

  written.forEach((f) => console.log(f));
  return errors.length > 0 ? 1 : 0;
}

main().then(
  (code) => process.exit(code),
  (err: Error) => {
    console.error(`Error: ${err.message}`);
    process.exit(1);
  },
);
