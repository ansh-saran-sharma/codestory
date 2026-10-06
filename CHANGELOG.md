# Changelog

All notable changes are recorded here. Versions follow [semantic versioning](https://semver.org/).

## Unreleased

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
