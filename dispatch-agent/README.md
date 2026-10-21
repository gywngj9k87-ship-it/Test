# dispatch-agent

Send a review task about a set of files to **Claude** and/or **ChatGPT** in parallel, with the
model and reasoning effort configurable per provider. Each provider's review is written to
its own Markdown file, and both can be merged into one combined review.

## Setup

Requires Node 22.18+ (runs the TypeScript directly, no build step).

```bash
cd dispatch-agent
npm install
cp .env.example .env    # then paste your keys into .env
```

`.env` is git-ignored, and `npm run ui` / `npm run dispatch` load it automatically.
Exported `ANTHROPIC_API_KEY` / `OPENAI_API_KEY` environment variables work too.
Get keys at https://console.anthropic.com/settings/keys and https://platform.openai.com/api-keys.

## Web app

```bash
npm run ui                                # serves http://localhost:8700
npm run ui -- --root ~/code/my-project    # let file paths point into another folder
npm run ui -- --port 9000
```

Open http://localhost:8700 and:

1. Write a prompt (or pick a preset: general review, bugs, security, performance, readability).
2. Add files: type paths inside the root folder (`src/hooks, src/lib/api.js`) and press **Check**,
   or drop files onto the page.
3. For each agent, switch it on or off, choose the model, and choose the reasoning effort.
4. Press **Send to agents** (Ctrl/⌘ + Enter). Both reviews stream in side by side; **Stop** cancels.
5. Press **Merge reviews** to have Claude or ChatGPT combine them into one list.

Each review can be copied or downloaded, and is also saved in `reviews/`. Your prompt, paths and
settings are remembered in the browser.

The server only listens on `localhost`, keeps the API keys on your machine, refuses paths outside
the root folder, and rejects requests from other websites.

## Command line

```bash
# Review a folder with both providers using the defaults in dispatch.config.json
npm run dispatch -- ../src

# Give it a specific task
npm run dispatch -- -t "Look for bugs and race conditions in the data-fetching hooks" ../src/hooks

# Set the model and effort for each provider
npm run dispatch -- \
  --claude-model claude-sonnet-5-5 --claude-effort xhigh \
  --openai-model gpt-5.4-mini --openai-effort low \
  ../src

# Only one provider
npm run dispatch -- -p openai --openai-effort high ../src/lib

# Merge both reviews into one prioritized list (Claude merges by default)
npm run dispatch -- -s ../src
npm run dispatch -- -s --synthesizer openai ../src

# See which files would be sent and with which settings, without calling any API
npm run dispatch -- --dry-run ../src
```

Reports go to `reviews/<timestamp>-claude.md`, `-openai.md` and `-combined.md`.

## Settings

Defaults live in `dispatch.config.json`; command-line flags override them.

| Setting | Claude | ChatGPT (OpenAI) |
|---|---|---|
| Model flag | `--claude-model` (default `claude-opus-5-5`) | `--openai-model` (default `gpt-5.5`) |
| Effort flag | `--claude-effort` | `--openai-effort` |
| Effort levels | `low` `medium` `high` `xhigh` `max` | `none` `minimal` `low` `medium` `high` `xhigh` `max` (which ones are accepted depends on the model) |
| API field | `output_config.effort`, with adaptive thinking | `reasoning.effort` (Responses API) |

Notes:

- **Effort guidance:** `high` is a good default for reviews. Use `xhigh`/`max` for hard or
  high-stakes reviews and `low`/`medium` for quick passes; higher effort costs more tokens
  and takes longer.
- **Claude refusal fallback:** on models that support it (Opus 5.5, Opus 5, Sonnet 5.5,
  Fable 5.1), requests include `fallbacks: "default"`, so if a request is declined by a safety
  classifier it is retried on a fallback model in the same call. The report notes when that happens.
- **Input size:** all files are sent in full. If the total exceeds `maxChars`
  (default 400,000 characters), the run stops rather than silently cutting files.
  `node_modules`, `.git`, build output, lockfiles and binary files are skipped.
- If one provider fails, the other's review is still saved and the exit code is 1.

## Using it from code

```ts
import { loadConfig } from "./src/config.ts";
import { collectFiles } from "./src/files.ts";
import { dispatch, synthesize } from "./src/dispatch.ts";

const config = loadConfig(undefined, { claudeEffort: "xhigh", openaiEffort: "high" });
const files = await collectFiles(["../src"], config.maxChars);
const task = { instruction: "Review for accessibility issues", files };
const { results, errors } = await dispatch(task, config);
const combined = await synthesize(task, results, "claude", config);
```

## Layout

```
src/cli.ts               command-line entry point
src/server.ts            local web server for the UI (streams results to the browser)
public/index.html        the web app
src/config.ts            defaults, config file and flag merging, validation
src/dispatch.ts          parallel dispatch and synthesis
src/files.ts             file collection
src/prompt.ts            review and synthesis prompts
src/report.ts            Markdown report formatting
src/providers/claude.ts  Anthropic SDK call
src/providers/openai.ts  OpenAI SDK call
```
