#!/usr/bin/env node
import { mkdir, readFile, writeFile } from "node:fs/promises";
import http from "node:http";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { parseArgs } from "node:util";
import { loadConfig } from "./config.ts";
import { run, synthesize } from "./dispatch.ts";
import { collectFiles } from "./files.ts";
import { buildUserMessage, SYSTEM_PROMPT } from "./prompt.ts";
import { report } from "./report.ts";
import {
  CLAUDE_EFFORTS,
  OPENAI_EFFORTS,
  type DispatchConfig,
  type ProviderName,
  type ProviderResult,
  type SourceFile,
  type Task,
} from "./types.ts";

const { values } = parseArgs({
  options: {
    port: { type: "string", default: "8700" },
    root: { type: "string" },
    config: { type: "string", short: "c" },
  },
});
const PORT = Number(values.port);
// Paths typed into the UI are resolved against this folder and can't leave it.
const ROOT = path.resolve(values.root ?? process.cwd());
const APP_DIR = path.join(path.dirname(fileURLToPath(import.meta.url)), "..");
const PAGE = path.join(APP_DIR, "public", "index.html");
// Markdown rendering for the page, served locally so it works offline.
const VENDOR: Record<string, string> = {
  "/vendor/marked.min.js": path.join(APP_DIR, "node_modules", "marked", "marked.min.js"),
  "/vendor/purify.min.js": path.join(APP_DIR, "node_modules", "dompurify", "dist", "purify.min.js"),
};
const base = loadConfig(values.config, {});

interface ProviderInput {
  model: string;
  effort: string;
}

interface TaskInput {
  instruction: string;
  paths?: string[];
  uploads?: SourceFile[];
}

class HttpError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

function resolveInRoot(p: string): string {
  const abs = path.resolve(ROOT, p);
  if (abs !== ROOT && !abs.startsWith(ROOT + path.sep)) {
    throw new HttpError(400, `"${p}" is outside ${ROOT}.`);
  }
  return abs;
}

async function buildTask(input: TaskInput): Promise<Task> {
  const instruction = input.instruction?.trim();
  if (!instruction) throw new HttpError(400, "Write a prompt first.");
  const files = await loadFiles(input);
  if (files.length === 0) throw new HttpError(400, "Add at least one file.");
  return { instruction, files };
}

async function loadFiles(input: TaskInput): Promise<SourceFile[]> {
  const paths = (input.paths ?? []).map((p) => p.trim()).filter(Boolean);
  const fromDisk = paths.length
    ? (await collectFiles(paths.map(resolveInRoot), base.maxChars)).map((f) => ({
        ...f,
        path: path.relative(ROOT, path.resolve(f.path)) || f.path,
      }))
    : [];
  const files = [...fromDisk, ...(input.uploads ?? [])];
  const chars = files.reduce((n, f) => n + f.content.length, 0);
  if (chars > base.maxChars) {
    throw new HttpError(
      400,
      `Files total ${chars.toLocaleString()} characters, over the ${base.maxChars.toLocaleString()} limit.`,
    );
  }
  return files;
}

function configFor(provider: ProviderName, s: ProviderInput): DispatchConfig {
  return provider === "claude"
    ? loadConfig(values.config, { providers: "claude", claudeModel: s.model, claudeEffort: s.effort })
    : loadConfig(values.config, { providers: "openai", openaiModel: s.model, openaiEffort: s.effort });
}

function checkProvider(p: unknown): ProviderName {
  if (p !== "claude" && p !== "openai") throw new HttpError(400, "provider must be claude or openai.");
  return p;
}

async function save(r: ProviderResult, name: string, title: string): Promise<string> {
  const dir = path.resolve(base.outDir);
  await mkdir(dir, { recursive: true });
  const stamp = new Date().toISOString().replace(/[:.]/g, "-").slice(0, 19);
  const file = path.join(dir, `${stamp}-${name}.md`);
  await writeFile(file, report(r, title));
  return path.relative(process.cwd(), file);
}

/** Runs one model call and streams it to the browser as server-sent events. */
async function streamRun(
  req: http.IncomingMessage,
  res: http.ServerResponse,
  call: (opts: { onText: (d: string) => void; signal: AbortSignal }) => Promise<ProviderResult>,
  saveAs: { name: string; title: string },
) {
  const abort = new AbortController();
  res.on("close", () => abort.abort());
  res.writeHead(200, { "content-type": "text/event-stream", "cache-control": "no-cache" });
  const send = (event: string, data: unknown) => res.write(`event: ${event}\ndata: ${JSON.stringify(data)}\n\n`);
  try {
    const result = await call({ onText: (d) => send("delta", d), signal: abort.signal });
    const savedTo = await save(result, saveAs.name, saveAs.title);
    send("done", { ...result, savedTo });
  } catch (err) {
    if (!abort.signal.aborted) send("error", { message: (err as Error).message });
  }
  res.end();
}

async function readJson(req: http.IncomingMessage): Promise<any> {
  // Requiring JSON (which forces a CORS preflight we never answer) and a same-origin
  // Origin header stops other websites from triggering paid runs on this local server.
  if (!req.headers["content-type"]?.startsWith("application/json")) {
    throw new HttpError(415, "Expected application/json.");
  }
  const origin = req.headers.origin;
  if (origin && origin !== `http://${req.headers.host}`) throw new HttpError(403, "Cross-origin request refused.");
  let body = "";
  for await (const chunk of req) body += chunk;
  return JSON.parse(body || "{}");
}

const server = http.createServer(async (req, res) => {
  const json = (status: number, data: unknown) => {
    res.writeHead(status, { "content-type": "application/json" });
    res.end(JSON.stringify(data));
  };
  try {
    if (req.method === "GET" && (req.url === "/" || req.url === "/index.html")) {
      res.writeHead(200, { "content-type": "text/html; charset=utf-8" });
      res.end(await readFile(PAGE));
      return;
    }
    if (req.method === "GET" && req.url && VENDOR[req.url]) {
      res.writeHead(200, { "content-type": "text/javascript; charset=utf-8" });
      res.end(await readFile(VENDOR[req.url]));
      return;
    }
    if (req.method === "GET" && req.url === "/api/config") {
      return json(200, {
        root: ROOT,
        maxChars: base.maxChars,
        claude: { ...base.claude, efforts: CLAUDE_EFFORTS, hasKey: Boolean(process.env.ANTHROPIC_API_KEY) },
        openai: { ...base.openai, efforts: OPENAI_EFFORTS, hasKey: Boolean(process.env.OPENAI_API_KEY) },
      });
    }
    if (req.method !== "POST") return json(404, { error: "Not found" });

    const body = await readJson(req);
    if (req.url === "/api/files") {
      const files = await loadFiles({ instruction: "", paths: body.paths });
      return json(200, { files: files.map((f) => ({ path: f.path, chars: f.content.length })) });
    }
    if (req.url === "/api/run") {
      const provider = checkProvider(body.provider);
      const config = configFor(provider, body.settings);
      const task = await buildTask(body.task);
      const user = buildUserMessage(task);
      return streamRun(req, res, (opts) => run(provider, config, SYSTEM_PROMPT, user, opts), {
        name: provider,
        title: `Review by ${provider}`,
      });
    }
    if (req.url === "/api/synthesize") {
      const by = checkProvider(body.provider);
      const config = configFor(by, body.settings);
      const task = await buildTask(body.task);
      const results: ProviderResult[] = body.results ?? [];
      if (results.length < 2) throw new HttpError(400, "Need two reviews to merge.");
      return streamRun(req, res, (opts) => synthesize(task, results, by, config, opts), {
        name: "combined",
        title: `Combined review (synthesized by ${by})`,
      });
    }
    json(404, { error: "Not found" });
  } catch (err) {
    const status = err instanceof HttpError ? err.status : 400;
    if (!res.headersSent) json(status, { error: (err as Error).message });
  }
});

server.listen(PORT, "127.0.0.1", () => {
  console.log(`Dispatch UI running at http://localhost:${PORT}`);
  console.log(`File paths resolve against ${ROOT}`);
  if (!process.env.ANTHROPIC_API_KEY) console.log("Note: ANTHROPIC_API_KEY is not set - Claude runs will fail.");
  if (!process.env.OPENAI_API_KEY) console.log("Note: OPENAI_API_KEY is not set - ChatGPT runs will fail.");
});
