import { readdir, readFile, stat } from "node:fs/promises";
import path from "node:path";
import type { SourceFile } from "./types.ts";

const SKIP_DIRS = new Set([".git", "node_modules", "dist", "build", ".next", "coverage", "reviews"]);
const SKIP_FILES = new Set(["package-lock.json", "yarn.lock", "pnpm-lock.yaml"]);

async function walk(target: string, out: string[]): Promise<void> {
  const info = await stat(target);
  if (info.isFile()) {
    out.push(target);
    return;
  }
  for (const entry of await readdir(target, { withFileTypes: true })) {
    if (entry.isDirectory() && SKIP_DIRS.has(entry.name)) continue;
    if (entry.isFile() && SKIP_FILES.has(entry.name)) continue;
    await walk(path.join(target, entry.name), out);
  }
}

/**
 * Reads the given files and directories (recursively). Binary files are skipped.
 * Throws instead of truncating when the total exceeds maxChars, so a review never
 * silently runs on partial input.
 */
export async function collectFiles(targets: string[], maxChars: number): Promise<SourceFile[]> {
  const paths: string[] = [];
  for (const t of targets) await walk(t, paths);

  const files: SourceFile[] = [];
  let total = 0;
  for (const p of [...new Set(paths)].sort()) {
    const buf = await readFile(p);
    if (buf.includes(0)) continue; // binary
    const content = buf.toString("utf8");
    total += content.length;
    files.push({ path: path.relative(process.cwd(), p) || p, content });
  }
  if (total > maxChars) {
    throw new Error(
      `Selected files total ${total.toLocaleString()} characters, over the ${maxChars.toLocaleString()} limit. ` +
        `Narrow the paths or raise --max-chars.`,
    );
  }
  return files;
}
