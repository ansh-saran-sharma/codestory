# Changelog

All notable changes are recorded here. Versions follow [semantic versioning](https://semver.org/).

## Unreleased

## 0.3.0 — 2026-10-10

The walkthrough view: a line-by-line, debugger-style replay of the code for programmers, alongside the story view.
Use `--view walkthrough` with `scan` or `run`. Design: `docs/walkthrough-spec.md`.

- Added: user documentation for the walkthrough view in `README.md` and `USAGE.md`, with examples for every
  assistant, and `docs/walkthrough-demo.gif`.
- Added: example walkthroughs for the weather pipeline (a run), the log checker (every path) and a new stock-check
  example (a run of a stdlib-only job).
- Added: `walkthrough.schema.json`, the format of `walkthrough.json`: titles and explanations keyed by statement id,
  and notes keyed by step id.
- Added: `build` validates a walkthrough against its bundle: unknown statement or step ids (with the valid lines
  in that file as a hint), missing or over-long titles and texts, unknown fields. It notes explanations that would
  never be shown and low coverage of the most important statements. `--force` builds anyway.
- Added: `SKILL.md` covers the walkthrough view: `--view`, `--focus` and `--max-steps` in the `/codestory` command,
  when to choose it, recording commands for each environment, and a new section on writing a walkthrough.
  `references/walkthrough-guide.md` has the full writing rules and an example.
- Fixed: class bodies (for example a `@dataclass`) are no longer stepped into; they belong to the definition.
- Fixed: creating an empty container no longer ranks as a data change in `explain_first`.
- Changed: the walkthrough player shows a dataclass's fields, not just its type.
- Added: `walkthrough.html`, the walkthrough player: code with syntax highlighting and file tabs, an explanation
  and facts panel, call-stack breadcrumb, outline, and controls for next, back, step over, step out and autoplay.
  Every step type animates on arrival: the highlight glides, calls draw an arrow to the definition and carry their
  arguments, returns carry their value back, new values fly into the variables panel and counts move to their
  new value, branches dim the side that didn't run, loop summaries count up, exceptions are marked in red.
  Clicking a name opens its definition without losing your place. Light and dark themes, phone layout, reduced
  motion.
- Added: `build walkthrough.json --bundle codestory_bundle.json` merges the explanations with the bundle.
- Changed: the animation engine moved to `engine.js`, shared by both players; `build` embeds it, so built files
  are still single and offline. The story player is unchanged.
- Added: example walkthroughs for both examples (`walkthrough.json`, `codestory_walkthrough_bundle.json`,
  `walkthrough.html`), and build tests.
- Added: `--view walkthrough`, `--focus` and `--max-steps` for `scan` and `run`.
- Added: statement map: every statement's kind, the names it reads and writes and where each comes from,
  calls in evaluation order and their origin, I/O, type hints and comments.
- Added: line-level recording for `run --view walkthrough`, using `sys.monitoring` on Python 3.12+ and
  `sys.settrace` before; values before and after every recorded line, including in-place changes.
- Added: step plan for both modes: calls and returns, branches taken, loops collapsed after 3 iterations,
  generators, exceptions, and statements ranked for explanation.
- Changed: bundle schema is now `codestory.bundle/2`; version 1 fields are unchanged.
- Added: `tests/`, with 31 tests that run on both tracing backends.
- Added: a 200-line sample log to the log checker example, so it can be recorded with `run`.
- Docs: design spec for the walkthrough view, `docs/walkthrough-spec.md`.

## 0.2.0 — 2026-10-07

- Added: `-m MODULE` for `scan` and `run`, for programs started with `python -m`.
- Added: a defined `/codestory` command syntax in `SKILL.md` (`[scan | run] <entry> [options] [-- program arguments]`)
  with `--audience` and `--out`, so every assistant parses requests the same way.
- Added: `USAGE.md`, with invocation instructions and examples for every mode, option and assistant.
- Docs: every argument and option is marked required or optional, with its default, in `USAGE.md`, the
  README and `SKILL.md`.
- Fixed: in short browser windows, the middle card of a scene could overlap the narration. Scenes now fit
  the available height: the code shrinks with a fade (keeping the highlighted lines), sample tables are
  dropped, grid chips tighten, and as a last resort the scene scrolls.

## 0.1.0 — 2026-10-04

First public release.

- `codestory.py scan`: static analysis from the entry point (imports, constants, functions, call graph
  including functions passed as values, I/O sites, branches), with a source-code size budget.
- `codestory.py run`: traces one real run (`sys.monitoring` on Python 3.12+, `sys.setprofile` before),
  with value summaries for tables, arrays, collections and HTTP responses, and masking of secret-looking values.
- Safe mode for `run`: file writes and folder creation redirected to a sandbox; SQLite on a working copy;
  PostgreSQL (psycopg2, psycopg) and MySQL (pymysql) writes saved to JSONL files instead of being sent;
  HTTP POST/PUT/PATCH/DELETE and email blocked; subprocesses blocked unless allowed.
- `codestory.py build`: validates a storyboard and embeds it into the player as one offline HTML file.
- Player: scene timeline with data tokens, branch and grid layouts, scrubbing, keyboard controls, detail
  drawer, light and dark themes, mobile layout. Built-in animation engine; no third-party code.
- `SKILL.md` and references for Claude, GitHub Copilot, OpenAI Codex, Cursor, Gemini CLI and chat assistants.
- Examples: a `run` of a pandas + SQLite pipeline and a `scan` of a log checker.
