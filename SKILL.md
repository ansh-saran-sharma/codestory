---
name: codestory
description: Turns a Python script or codebase into an animated, shareable HTML file showing how the code works - either a story of the data for a mixed audience (imports, settings, inputs, every transformation, decisions, outputs), or a line-by-line code walkthrough for programmers with real values at every step. Use this whenever the user wants to visualize, animate, walk through, step through, or explain how their code or pipeline works, show what happened in a particular run ("what did today's run do", "where did my rows go", "which branch ran"), onboard someone onto a codebase, or explain code to a stakeholder or to engineers. Also use it when the user types /codestory or uploads a codestory_bundle.json, even if they don't name the skill.
---

# codestory

The scripts do the mechanical work: `codestory.py` records the program and builds the player. Your job is the
part that needs judgment. You read a **bundle** (what the code is and, for a run, what it did) and write one of
two documents, depending on the **view**:

- **Story** (default): a **storyboard** (`storyboard.json`), an ordered set of scenes about the data that a
  non-expert can follow. Sections 3–6.
- **Walkthrough**: a **walkthrough** (`walkthrough.json`), titles and technical explanations for the statements
  of a line-by-line, debugger-style replay, for programmers. The tool decides the steps and measures every value;
  you write the words. Section 7.

The quality of the result depends almost entirely on what you write.

Files in this skill folder:
- `codestory.py` — `scan`, `run`, `build`. Python 3.8+, standard library only.
- `player.html` (story) and `walkthrough.html` (walkthrough) — the players. `build` embeds your document, and
  `engine.js`, into one offline HTML file.
- `storyboard.schema.json`, `walkthrough.schema.json` — the exact formats you must produce.
- `references/walkthrough-guide.md` — how to write a walkthrough. Read it whenever the view is `walkthrough`.
- `references/bundle-format.md` — what every field in the bundle means. Read it the first time you use this skill.
- `references/example-storyboard.json` — a complete, good storyboard for a real run. Look at it before writing your first one.

## 1. Understand the request

### The `/codestory` command

Users may invoke you with this exact syntax (in Codex it starts with `$codestory`). Parse it strictly:

```
/codestory [scan | run] <entry> [options] [-- program arguments]
```

Only `<entry>` is required. Everything else is optional; when it's missing, use the default below and don't
ask about it.

| Part | Required? | Default if missing | Meaning | Becomes |
|---|---|---|---|---|
| `<entry>` | **Required** (ask if missing) | — | The script they normally run: `main.py`, `jobs/nightly.py`. Or `-m package.module` for programs started with `python -m`. Or a `codestory_bundle.json`: then skip section 2 and write the story from it. | the entry argument, or `-m MODULE` |
| `scan` / `run` | Optional | Infer from wording (below); if nothing to go on, `scan` | The mode. | the `codestory.py` subcommand |
| `--live` | Optional, run only | Off: safe mode | Real side effects, no sandbox. | `run --live` |
| `--allow-subprocess` | Optional, run only | Off | Let the program start other programs. | `run --allow-subprocess` |
| `--root DIR` | Optional | Omit; codestory picks the folder | The project root, when it isn't the current folder. | `--root DIR` |
| `--budget N` | Optional | Omit (240,000) | Max characters of source code in the bundle. | `--budget N` |
| `--view story \| walkthrough` | Optional | `story` | Story of the data, or line-by-line code walkthrough. Must be chosen **before recording**. | `--view walkthrough` on `scan`/`run` |
| `--focus TARGET` | Optional, walkthrough only | The whole program | Files or functions to cover, comma-separated: `etl/clean.py`, `clean`, `etl.clean:clean`. | `--focus TARGET` |
| `--max-steps N` | Optional, walkthrough only | 150 | How many statements to explain in writing. | `--max-steps N` |
| `--audience TEXT` | Optional | A mixed audience (story); programmers (walkthrough) | Who it's for: `stakeholders`, `engineers`, `new team members`, or any description. | narration style (sections 5, 7) |
| `--out FILE` | Optional | `story.html`, or `walkthrough.html` | Name of the output file. | `build -o FILE` |
| `-- ...` | Optional; needed only if their program requires arguments | No program arguments | Everything after a bare `--` belongs to the user's program, unchanged. | appended after `--` |

Examples, and what you run:

```
/codestory main.py                                   -> infer mode from context; if none, scan
/codestory scan main.py --audience stakeholders      -> codestory.py scan main.py
/codestory run main.py -- --date 2026-10-01          -> codestory.py run main.py -- --date 2026-10-01
/codestory run -m etl.cli --live -- --full-refresh   -> codestory.py run -m etl.cli --live -- --full-refresh
/codestory codestory_bundle.json --out today.html    -> no recording; storyboard, then build -o today.html
/codestory scan main.py --view walkthrough           -> codestory.py scan main.py --view walkthrough
/codestory run main.py --view walkthrough --focus clean -- --date 2026-10-01
                                                     -> codestory.py run main.py --view walkthrough --focus clean -- --date 2026-10-01
```

Users will just as often write plain language. Map it the same way: "explain", "walk through", "how does it work"
mean `scan`; "what happened", "today's run", "with these arguments" mean `run`; "for real", "don't sandbox",
"actually write the files" mean `--live`; "for my manager" sets the audience. "Line by line", "step through the
code", "explain each line", "like a debugger", "what does each statement do" mean `--view walkthrough`; asking for
programmers alone doesn't. Unknown options: ask, don't guess.
Never add `--live` or `--allow-subprocess` on your own.

### What to work out

Work out these things from the request. Ask only for what you cannot infer, in one question.

**Entry point.** The script they normally run (`main.py`, `run_pipeline.py`), or a module started with
`python -m app` (use `-m app`). If they named a folder, look for `if __name__ == "__main__":`, a `main.py`, a
`__main__.py`, or the command in their README or Makefile.

**Mode.**
- `scan` when they want to *explain the code*: "how does this work", onboarding, a walkthrough for a colleague or
  stakeholder, or when running it is impossible or unsafe. Nothing is executed. Every path is shown as possible.
- `run` when they want *what actually happened*: a specific run, a specific date or input, "why did only 12 rows
  come out", "what did the job do this morning". The program is executed under the tracer.
- If the message fits both, prefer `scan` and offer `run` in one sentence at the end.

**View.** `story` unless they ask for line-by-line detail (above). A walkthrough of a large program is long:
when there are more than about 300 statements in the plan, suggest `--focus` on the part they care about.

**Program arguments** (run mode only). If the script needs arguments and they gave none, read its argument parser
and ask for the values, or propose the ones from their README.

**Audience.** Default to a mixed audience: a curious non-programmer should follow the narration, and a developer
should find the code on every card. If they say it's for executives or for engineers, lean that way (see section 5).

## 2. Get the bundle

Pick the path that matches what you can do in this environment.

### A. You can run commands on the user's machine (Claude Code, Copilot agent mode, Codex, Cursor, Gemini CLI)

1. Find the project's Python environment. Look for `.venv/`, `venv/`, a `poetry.lock`/`uv.lock`, or conda
   instructions, and use that interpreter. The program's imports must resolve, so the system Python is usually wrong.
2. `scan`: run it straight away. It reads files and executes nothing.
   ```bash
   <python> <skill>/codestory.py scan <entry.py> -o codestory_bundle.json [--view walkthrough] [--focus T] [--max-steps N] [--root DIR] [--budget N]
   ```
   For a module, use `-m package.module` instead of the script path, from the folder they run `python -m` in.
3. `run`: **ask before executing**, because it runs the user's program. Show the exact command and what safe mode
   will do, in a few lines:
   > I'll run `python codestory.py run main.py -- --date 2026-10-01`. Safe mode is on: file writes go to a temporary
   > folder, database writes are captured instead of applied, and web POSTs and emails are blocked. Reads (input
   > files, SELECT queries, GET requests) really happen. OK to go ahead?

   Only use `--live` if the user explicitly asks for real side effects. Only use `--allow-subprocess` if they agree.
   For a walkthrough, add `--view walkthrough` (and `--focus`, `--max-steps` if given) and mention that line-by-line
   recording makes the run slower: 2–10 times, most for tight pure-Python loops.
4. Read what the command printed: outcome, intercepted side effects, any "REAL side effect" lines and warnings about
   libraries safe mode cannot intercept. You will repeat the important ones to the user at the end.

### B. Chat with code execution but no access to their machine (claude.ai, ChatGPT)

- If they uploaded `codestory_bundle.json`, use it.
- If they uploaded the source files and want `scan`, you can run `scan` yourself on the uploaded files in your
  sandbox. Missing third-party packages don't matter for a scan.
- For `run`, the program must execute in *their* environment. Give them the one command to run locally with their
  virtualenv active, and ask them to upload the resulting `codestory_bundle.json`:
  ```bash
  python codestory.py run main.py -- <their usual arguments>
  ```
  Put any options they asked for into that command (`--live`, `--allow-subprocess`, `--root`, `--budget`, `-m`,
  and for a walkthrough `--view walkthrough`, `--focus`, `--max-steps`), because in this environment they are the
  one running it. Options about the output (`--audience`, `--out`) stay with you. They need `codestory.py` from this skill; offer it as a download.

### C. No code execution at all

Same as B for getting the bundle. At the end, give them your document and the build command (section 6 or 7).

### Check the bundle matches the view

A bundle recorded with `--view walkthrough` has a `"view": "walkthrough"` field and a `plan`; it can produce either
view. A bundle without them can only produce a story. If they want a walkthrough from a story bundle, it must be
recorded again with `--view walkthrough`; say so.

**If the view is `walkthrough`, skip sections 3–6 and go to section 7.**

## 3. Read the bundle

Read `references/bundle-format.md` if you haven't. The fields you'll use most:

- `run` — outcome, duration, arguments, safe mode, error and traceback.
- `trace.nodes` — the call tree, in execution order. Each node has the function id (`module:qualname`), parent,
  start time, duration, and summaries of its arguments and return value (`rows`, `cols`, `columns`, `sample` for tables).
  This is the backbone of a run story.
- `io.events` — every read and write, attached to the function (`fn`) and node that did it. `handled` tells you
  what safe mode did: `redirected`, `working-copy`, `shadowed`, `blocked`.
- `modules.<name>.functions.<qualname>.source` — the code, verbatim, with its first line number in `line`.
- `modules.<entry>.main_flow` — top-level statements of the entry script, in order. The backbone of a scan story.
- `libraries`, `modules.<name>.constants`, `runtime_constants` — for the imports and settings scenes.
- `unexecuted_functions` (run) / `unreached_functions` (scan) — for skipped or dead paths.

Follow the data, not the call tree. A good scene answers "what happened to the data here?" Some calls (logging
setup, small helpers, getters) don't change anything worth showing.

## 4. Design the scenes

### Shape of the story

Most programs follow this arc. Use the phases that exist and skip the ones that don't:

| Phase | What it shows | Layout |
|---|---|---|
| `imports` | Libraries and the project's own modules | grid |
| `constants` | Settings that shape behaviour: paths, thresholds, flags, environment values | grid |
| `setup` | Reading arguments, connecting, building clients | flow |
| `input` | Each source of data: file, query, API call | flow |
| `transform` | Each step that changes the data | flow |
| `branch` | A decision that changes what happens next | branch |
| `output` | Each thing written or sent: file, table, API, email | flow |
| `error` | Where and why a run stopped | flow |

Leave out `definitions` unless the audience is developers and the module structure itself is the point.

**How many scenes.** Aim for 8–16 top-level scenes. A 30-line script may need 5; a large pipeline still rarely
needs more than 20. If you have more candidates, merge consecutive small steps into one scene and put the detail in
`children`. The player limit is 60 including children.

**One scene per meaningful change to the data.** Rules of thumb:
- A function that loads, filters, joins, aggregates, enriches, splits, validates or writes data gets a scene.
- A function that only wraps others (`clean()` calling three steps) becomes a parent scene with `children`.
- A function called in a loop (`process_row` × 12,840) is one scene. Say how many times it ran.
- Pure plumbing (logging config, path joining, `parse_args` with nothing interesting) is skipped or folded into
  `setup`. Keep `parse_args` if the arguments change the behaviour, as in a `--full-refresh` flag.
- Decisions get a `branch` scene only when the outcome changes which steps run or what gets written. Not every `if`.

**Order.** Run mode: order by `t_ms` of the trace nodes. Scan mode: follow `main_flow`, then the calls inside each
function in source order.

### Imports and constants scenes

- Imports: list third-party packages with a two-word `note` on what they're for (`pandas` → "tables",
  `requests` → "web calls"), the project's own modules, and the standard-library modules that matter
  (`sqlite3`, `csv`, `smtplib`). Skip ones like `typing`, `dataclasses` and `__future__`. At most about 15 items.
- Constants: only the ones that shape behaviour. Use `kind: "config"` for values from the environment or config
  files, with a `note` saying so ("from WEATHER_ENV", "default; env var not set"). Use `kind: "secret"` with the
  value `"••••••"` for anything the bundle redacted. Never print a secret, even one you can see in the source.

### Cards

Every flow scene has an `actor` (the function doing the work) and usually `inputs` and `outputs`.

- **Actor**: `kind: "function"`, `label` is the function name with `()`, `sublabel` is the file. Put the
  function's `source` from the bundle in `code.snippet` **verbatim**, set `code.line` and `code.file`, and set
  `code.highlight` to the 1–3 absolute line numbers that do the work. Absolute line = `line` + index of the line
  within the snippet. Check your arithmetic: a wrong highlight undermines trust in the whole story.
- **Data cards**: `kind: "data"`. `label` is the variable name the code uses (`raw`, `readings`, `summary`) so
  developers can map card to code. Copy `rows`, `cols`, `columns` and `sample` exactly from the matching argument
  or return value in the trace. Don't round or invent; the player animates these numbers.
- **Sources and destinations**: `kind` `file`, `database`, `api`, `email` or `process`. `label` is the short name
  (`readings.csv`, `daily_summary`, `POST weather-alerts`); `sublabel` is the path, database and table, or host.
- **Status from safe mode**: `handled` = `redirected` / `working-copy` / `shadowed` → card `status: "sandboxed"`;
  `blocked` → `"blocked"`. Give that card a `detail` saying what happened ("Written to the sandbox, not the real
  output folder."). Set the scene's `status` to `"sandboxed"` too.
- `detail` holds anything worth knowing that doesn't fit on the card. It appears when the viewer clicks.

### Status, by mode

- Run mode: executed scenes are `ran` (the default; omit it). Steps that exist in the code but didn't execute,
  shown only where it helps the story (usually the untaken side of a branch), are `skipped`.
- Scan mode: everything is `possible` (the default; omit it). Leave out `rows` and `stats` because nothing ran.
  Use `shape` for structural facts ("one row per station per day").
- `failed` marks the scene where an error was raised.

### Branch scenes

Set `branch.condition` to the code exactly, and `branch.question` to a plain question
("Any anomalies, and are alerts allowed?"). Each path gets a `label` describing what happens on that side and a
`status`: in run mode `taken` / `not_taken`; in scan mode `possible`. Work out which side was taken from the trace:
the functions under the taken side executed, the others appear in `unexecuted_functions`. Set `goto` to the scene
the taken path leads to. Put the `if` line in `actor.code.highlight`.

### Errors

If `run.status` is `"error"`, the story ends at the failure. Add an `error` scene whose actor is the innermost
project frame in `run.traceback`, highlight that line, mark it `failed`, and explain in plain words what went wrong
and what data was in hand at that moment. Scenes after the failure point don't appear.

## 5. Write the words

The narration is what makes this useful to someone who can't read the code. Write it for a smart person from
outside the team.

**Titles**: sentence case, start with a verb, describe the action rather than naming the function.
"Drop impossible temperatures", not "drop_invalid()" or "Data validation step". Under 60 characters.

**Narration**: 1–3 sentences, under 320 characters. Say what happens and why it matters, with the real numbers.
- Good: "Rows with a missing temperature or a value outside −40 to 55 °C are removed: 25 rows, including sensor glitches that read 999."
- Weak: "This function filters the DataFrame using boolean indexing on the temp column."
- Weak: "The data is cleaned." (No numbers, no reason.)

Guidelines:
- Plain words over jargon: table, not DataFrame; remove duplicates, not dedupe; look up, not join (unless the
  audience is developers). Name the business object: readings, orders, customers.
- **Every number must come from the bundle.** Compute differences yourself (601 in, 552 out → 49 removed) and
  double-check them. If you can't tell a number from the bundle, leave it out rather than estimating.
- Mention constants by their meaning and value ("1.4 standard deviations"), not just their name.
- Explain *why* when the code makes it clear (a comment, a docstring, an obvious intent). Don't speculate beyond that.
- Don't repeat the title. Don't start every narration with "This step".
- Run mode: past or present tense, specific ("this run is for 1 October"). Scan mode: general and conditional
  ("each night", "if any anomalies are found, an alert is sent").
- Be candid about safe mode in output scenes, briefly: "In safe mode the file went to the sandbox instead."
- For executives: shorter narration, outcomes and counts, fewer code details. For developers: you can name
  functions and libraries, and mention timings from `dur_ms` when they're notable.

**Stats** (up to 4 per scene): the numbers worth glancing at, such as rows in and out, rows removed, rows written or
records sent. Use `delta` for a change versus the previous step. Skip stats in scan mode.

**Title, subtitle, summary.**
- `title`: what the program is, in plain words ("Daily weather pipeline").
- `subtitle`: one sentence from input to output.
- `summary.headline`: the run in one sentence with the headline numbers ("601 readings became a 24-row daily summary
  and one alert."). Scan mode: what the program produces.
- `summary.stats`: the 3–4 numbers that tell the arc.
- `summary.notes`: what the viewer should know: side effects safe mode held, real side effects, libraries safe mode
  couldn't intercept, read-after-write warnings, trimmed sources, or a truncated trace.

## 6. Build, check, deliver

1. Write `storyboard.json` following `storyboard.schema.json` exactly. Copy `run` fields from the bundle
   (`status`, `started_at`, `duration_ms`, `args`, `safe_mode`, and `error` if any). Set `entry` to the command as
   the user would type it, without `python`: `main.py --date 2026-10-01`.
2. Build (use the name from `--out` if they gave one):
   ```bash
   python <skill>/codestory.py build storyboard.json -o story.html
   ```
   `build` validates the storyboard and lists problems. Fix them and build again; don't use `--force` to hide them.
3. Before delivering, check:
   - Every number in the narration and stats appears in, or follows arithmetically from, the bundle.
   - Every `code.highlight` line points at the line that does the work.
   - Every intercepted, blocked or real side effect in `io` appears on a card or in the summary notes.
   - In run mode, the untaken side of every branch you show is marked `not_taken` or `skipped`.
4. Deliver `story.html` as a file the user can open. In environment C, deliver `storyboard.json` and tell them:
   `python codestory.py build storyboard.json -o story.html`, or open `player.html` and drop the JSON onto it.
5. Reply briefly: what the story shows, the arc in one sentence with the key numbers, and any warnings
   (real side effects, libraries not intercepted, an error the run hit). In run mode, mention where safe mode put
   the sandboxed outputs (`run.sandbox`) in case they want to inspect them.

## 7. Write a walkthrough

Read `references/walkthrough-guide.md` first; it has the full rules and an example. In short:

1. **Know what's yours.** The tool already decided the steps, their order, and every value, call, branch outcome
   and name origin; the player shows all of that automatically. You write `walkthrough.json`
   (`walkthrough.schema.json`): a `title`, a `subtitle`, the `entry`, and `explanations` keyed by **statement id**
   (`"etl/clean.py:15"`), each with a `title` and a `text`.
2. **Choose what to explain.** Work down `plan.explain_first` (already ranked: data changes, branches, calls,
   I/O, exceptions first) and explain up to `plan.max_steps` statements. For a grouped step, explain its first
   statement. Skip trivial statements unless they're surprising.
3. **Write for programmers.** Title: sentence case, starts with a verb, at most 60 characters. Text: 1–4
   sentences, at most 700 characters: what the statement does, how (the mechanism), and anything non-obvious
   (in-place mutation, laziness, a performance trap, a bug risk). Don't restate the facts the player already
   shows (where a name is defined, its type, the measured values) unless you're adding meaning to them.
4. **Numbers must match the bundle.** One explanation covers every execution of a statement, so only quote values
   from a statement that ran once, or describe the pattern. Use `notes` (keyed by step id) for remarks about one
   particular execution.
5. **Build and fix.** `build` checks every id against the bundle and stops on mistakes:
   ```bash
   python <skill>/codestory.py build walkthrough.json --bundle codestory_bundle.json -o walkthrough.html
   ```
   Fix every problem it lists; don't use `--force` to hide them. Its notes (for example "an explanation inside a
   grouped step") are worth fixing too.
6. **Deliver** `walkthrough.html` as in section 6. In environment C, give them `walkthrough.json` and that build
   command; they need the bundle next to it.

## Limits to be honest about

- `scan` misses functions called dynamically (registries, `getattr`, configuration-driven dispatch), although it
  does follow functions passed as values. If `main_flow` calls into something the scan couldn't resolve, say so
  rather than guessing.
- In a `run`, each function's first 3 calls under the same parent are recorded in detail. Later calls are only
  counted (`repeats` on the parent). If `trace.truncated` is true, say the story covers the first part in detail.
- Safe mode covers files, SQLite, PostgreSQL (psycopg2/psycopg), MySQL (pymysql), HTTP via requests/httpx/urllib,
  smtplib and subprocesses. It does not cover cloud SDKs, MongoDB, Redis or Kafka; check
  `io.not_intercepted_libraries` and pass the warning on.
- A read after a shadowed write to a server database doesn't see the shadowed rows. Look for `read-after-write`
  events, and if one exists, say the later numbers may differ from a live run.
- Walkthrough recording follows the main thread only, records the first 3 executions of each line in each call,
  and doesn't see in-place changes except in statements that visibly mutate a variable (`df.loc[...] = ...`).
- Only Python is supported today.
