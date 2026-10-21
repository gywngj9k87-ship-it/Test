import type { Task } from "./types.ts";

export const SYSTEM_PROMPT = `You are a senior reviewer. You are given a set of files and a task.
Read the files carefully and respond with concrete, prioritized recommendations.

Format your answer in Markdown:
1. **Summary** - two or three sentences on overall quality and the biggest risks.
2. **Recommendations** - ordered by priority (High / Medium / Low). For each one give the
   file and line or section it applies to, what is wrong or could be better, why it matters,
   and a specific suggested change (a short code snippet when it helps).
3. **What's working well** - brief, only things worth keeping.

Only report issues you can point to in the provided files. If something cannot be judged
from the files alone, say what you would need to check.`;

export function buildUserMessage(task: Task): string {
  const files = task.files
    .map((f) => `<file path="${f.path}">\n${f.content}\n</file>`)
    .join("\n\n");
  return `<files>\n${files}\n</files>\n\n<task>\n${task.instruction}\n</task>`;
}

export const SYNTHESIS_PROMPT = `You are given independent reviews of the same files from different AI reviewers.
Merge them into one prioritized list of recommendations. Deduplicate overlapping points,
note where reviewers agree (higher confidence) and where they disagree (say which view you
find more convincing and why, using the files), and drop anything not supported by the files.`;
