# Bundle format (`codestory.bundle/2`)

`codestory.py scan` and `codestory.py run` write `codestory_bundle.json`. This is what each part means and how to
use it when writing a storyboard. Fields marked *(run)* exist only in run mode.

## Contents
1. Top level
2. `run` *(run)*
3. `libraries`
4. `modules`
5. `runtime_constants` *(run)*
6. `trace` *(run)*
7. `io` *(run)*
8. Value summaries
9. Unexecuted, unreached and budget
10. Walkthrough sections (`--view walkthrough`)

Version 2 adds the walkthrough sections (section 10). Everything in version 1 is unchanged, and a bundle recorded
without `--view walkthrough` has no new sections.

## 1. Top level

| Field | Meaning |
|---|---|
| `mode` | `"scan"` or `"run"`. Copy it into the storyboard. |
| `entry` | Entry script path relative to the project root. |
| `entry_module` | Module name used for the entry script in function ids (its file name without `.py`). |
| `root` | Project folder name. |
| `python` | Python version that ran the tool. |

## 2. `run` *(run)*

```json
{"started_at": "2026-10-03T20:55:46+00:00", "args": ["--date", "2026-10-01"], "safe_mode": true,
 "sandbox": "/tmp/codestory_hdwgt0ru", "status": "ok", "duration_ms": 468.9}
```
- `status`: `ok`, `exit` (`sys.exit` with a non-zero code: `exit_code`, maybe `message`), or `error`.
- On `error`: `error` is `"Type: message"`, and `traceback` lists project frames only, outermost first, each with
  `file`, `line`, `function` and `code`. The **last** frame is where it failed.
- `sandbox`: where safe mode put redirected files (`files/` mirrors real absolute paths) and shadowed database
  writes (`db_writes/*.jsonl`).

## 3. `libraries`

One entry per imported top-level package that isn't part of the project:
`{"name": "pandas", "kind": "third_party", "used_by": ["etl.extract"]}`. `kind` is `stdlib`, `third_party`, or
`missing` (not installed where the scan ran, which is normal when scanning uploaded files).

## 4. `modules`

Keyed by module name (`main`, `config`, `etl.clean`). Only modules reachable from the entry point are present;
in run mode, modules imported dynamically at runtime are added too.

| Field | Meaning |
|---|---|
| `path`, `lines` | File path relative to the root, and line count. |
| `imports` | `{module, names, alias, line, kind, scope}`. `kind`: `project` / `stdlib` / `third_party` / `missing`. |
| `constants` | Module-level assignments: `{name, line, value, how, upper}`. `how` is `literal`, `expression`, `environment` or `config file`. Secret-looking names have `value: "***"` and `redacted: true`. `upper` marks ALL_CAPS names, which are usually the real settings. |
| `functions` | Keyed by qualified name (see below). |
| `classes` | `{id, name, line, end, bases, doc}`. |
| `main_flow` | Entry module only. Its top-level statements in order: `{line, kind, code, calls, calls_project}`. A `kind: "main_guard"` item is the `if __name__ == "__main__":` block, with its statements in `body`. |
| `module_code` | Top-level lines that aren't inside functions or classes, prefixed `N: `. |

### Functions

```json
"etl.clean:drop_invalid"  ->  modules["etl.clean"].functions["drop_invalid"]
{"id": "etl.clean:drop_invalid", "name": "drop_invalid", "qualname": "drop_invalid", "line": 13, "end": 17,
 "args": ["df"], "doc": "Remove missing values and physically impossible temperatures.",
 "calls": ["df.dropna"], "calls_project": [], "io": [], "branches": [], "loops": [],
 "reach_depth": 2, "source": "def drop_invalid(df):\n ...", "executed": true,
 "runtime": {"calls": 1, "total_ms": 2.53}}
```
- **Function ids** are `module:qualname` everywhere: trace nodes, `io` events, `calls_project`. Methods are
  `Class.method`; nested functions are `outer.<locals>.inner`; module top-level code is `module:<module>`.
- `source` is verbatim; `line` is the absolute line number of its first line. For highlights, absolute line =
  `line` + index within `source.split("\n")`. When the budget ran out, `source` is only the signature and
  `source_trimmed` is true. Say so if that function matters to the story.
- `calls_project`: other project functions this one calls, resolved statically. `references_project` lists
  functions passed as values (e.g. `for step in (a, b, c): step(df)`); these are included in `calls_project` too.
- `io`: I/O spotted in the source: `{line, call, direction (read/write/connect), kind (file/database/api/email/config), target}`.
  `target` is the literal argument or the expression text. In scan mode this is your main evidence for inputs and outputs.
- `branches`: `{line, condition, has_else, body_lines}`, which help you find decision points.
- `loops`: `{line, code}`.
- `reach_depth`: how many calls away from the entry point's top-level code (0 = called directly). `null` = not
  reachable statically.
- *(run)* `executed` and `runtime.calls` / `runtime.total_ms`.

## 5. `runtime_constants` *(run)*

`"config.ANOMALY_Z": {"type": "float", "value": "1.4"}`: the actual value after the program ran, including values
that came from the environment or config files. Redacted names are absent.

## 6. `trace` *(run)*

```json
{"id": 14, "fn": "etl.clean:drop_invalid", "parent": 12, "t_ms": 41.2, "dur_ms": 2.53,
 "args": {"df": {"type": "DataFrame", "rows": 601, "cols": 4, ...}},
 "ret": {"type": "DataFrame", "rows": 576, "cols": 4, ...},
 "io": [3], "repeats": {"etl.clean:helper": 9}, "raised": "KeyError: 'x'"}
```
- `nodes` are in start order. `parent` builds the tree; the root is the entry module's `<module>` node. Other
  `<module>` nodes directly under the root are imports of project modules, with their import time.
- `args` and `ret` are value summaries (section 8). `<module>` nodes have no `ret`.
- `io` lists `seq` numbers of `io.events` this call performed directly.
- `repeats`: further calls to a child function beyond the 3 kept in detail. Total calls for any function are in
  `function_stats[fn].calls`.
- `raised`: the exception that left this call.
- `function_stats`: `{fn: {calls, total_ms}}` for every project function that ran.
- `truncated`: true if the node limit (4,000) was hit.

## 7. `io` *(run)*

`events`, in order of first occurrence, with repeated identical events merged:
```json
{"seq": 8, "kind": "database", "op": "insert", "target": "sqlite:data/stations.db / daily_summary",
 "fn": "etl.load:save_summary", "node": 20, "count": 24, "rows": 24, "handled": "working-copy",
 "sql": "INSERT INTO daily_summary ..."}
```
- `kind`: `file`, `database`, `api`, `email`, `process`.
- `op`: files `read`, `write`, `mkdir`, `remove`, `rename`, ...; databases `connect`, `read`, `read-after-write`,
  or the SQL verb (`insert`, `update`, `delete`, `create`, ...); APIs the HTTP method; email `send`; processes `run`.
- `handled` (safe mode): `redirected` (file went to the sandbox), `read-redirected` (read the sandbox copy),
  `working-copy` (SQLite file copied to the sandbox and used there), `shadowed` (server-database write saved to a
  JSONL file instead), `blocked` (not performed; a fake success was returned). Missing means it really happened.
- `rows` / `bytes` where known. `via` names the pandas writer or reader when one was used.

Summaries:
- `intercepted`: side effects safe mode held back. List them in the story.
- `real_effects`: writes that really happened (live mode, or something safe mode didn't cover). **Always tell the user.**
- `not_intercepted_libraries`: libraries in use whose side effects safe mode can't hold. Put this in the summary notes.
- `shadow_tables`: `{table: {rows, file}}` for shadowed server-database writes.
- `env_vars`: environment variables read through `os.getenv`: whether set, and whether the name looks secret. No values.

A `read-after-write` event means a later query read a table that had shadowed writes, so its result is missing
those rows. Mention it if later numbers depend on it.

## 8. Value summaries

Never full data. By type:
- Table (pandas or polars): `{type, rows, cols, columns, dtypes, sample: {columns, rows}}`, with 3 sample rows of up to 10 columns as short strings.
- Series: `{rows, name, dtype, sample}`. ndarray: `{shape, dtype, sample}`.
- list/tuple/set: `{len, sample}`. dict: `{len, keys, values}` (first few values summarised).
- str: `{len, value}` truncated to 100 characters. Numbers, bool, None: `{value}`.
- HTTP response: `{status, url, content_type}`. Dataclass: `{fields, values}`. Other objects: `{type, attrs}`.
- Anything whose name looks like a secret is `"***"`; tokens, passwords in URLs and bearer headers are masked inside strings.

## 9. Unexecuted, unreached and budget
10. Walkthrough sections (`--view walkthrough`)

- `unexecuted_functions` *(run)*: project functions that exist but didn't run. Use it to identify untaken branches.
- `unreached_functions` *(scan)*: functions not reachable statically from the entry point. Either dead code or
  dynamically called. Don't present them as part of the flow.
- `budget`: `{chars_used, functions_trimmed}`. Source included versus the `--budget` limit.
- `notes` *(scan)*: reminders about what static analysis can't see.

## 10. Walkthrough sections (`--view walkthrough`)

Present only when recorded with `--view walkthrough`.

| Field | Meaning |
|---|---|
| `view` | `"walkthrough"` |
| `focus` | `"whole program"`, or the files and functions chosen with `--focus` |
| `sources` | Full source text of every file in focus, keyed by path |
| `statements` | The statement map: every statement in those files, keyed by statement id |
| `docstrings` | Docstrings of modules, classes and functions, keyed by scope id |
| `plan` | The ordered steps of the walkthrough |
| `lines` *(run)* | The raw line events the plan was built from, per-line execution totals, and limits |

### Statements

Statement ids are `file:line` (the first line, including decorators), with `#2`, `#3` for a second statement
starting on the same line.

```json
"etl/clean.py:15": {"id": "etl/clean.py:15", "file": "etl/clean.py", "line": 15, "end": 15, "kind": "assign",
  "scope": "etl.clean:drop_invalid", "parent": "etl/clean.py:13", "block": "body",
  "reads": ["df"], "writes": ["df"], "names": {"df": {"kind": "parameter"}},
  "calls": [{"call": "df.dropna", "origin": "method", "on": "df"}]}
```

- `kind`: `import`, `constant`, `assign`, `call`, `return`, `yield`, `if`, `for`, `while`, `with`, `try`, `raise`,
  `assert`, `def`, `class`, `match`, `delete`, `pass`, `break`, `continue`, `scope`, `expr`.
- `line`–`end` cover the statement's own lines. For compound statements (`if`, `for`, `def`...) that's the header
  only; `full_end` includes the body, and `blocks` lists the statement ids in each block (`body`, `orelse`,
  `finalbody`, `handler0`..., `case0`...).
- `scope`: the function (`module:qualname`), class, or `module:<module>` the statement belongs to.
- `reads`, `writes`, `mutates`: names the statement reads, assigns, and changes in place (`df.loc[...] = ...`).
  Comprehension variables are excluded.
- `names`: where each name comes from: `parameter`, `local`, `constant` (with `value`), `global`, `function` or
  `class` (with `where`, as `file:line`), `import_project` (with `from`, `where`), `import_package` or
  `import_stdlib` (with `from`, `package`), `builtin`, `unknown`.
- `calls`, in evaluation order (arguments before the call that receives them): `origin` is `project` (with `id`
  and `where`), `package` or `stdlib` (with `qualified`, e.g. `pandas.read_csv`), `builtin`, or `method` (with
  `on`, the variable it's called on).
- `references`: project functions used as values here (passed, stored or looped over) rather than called.
- `imports_modules`: project modules an import statement loads.
- `io`: I/O visible in the source, as in the function-level `io` list.
- `hint` (annotated assignment), `hints` (function parameters and return), `defines`, `doc`, `generator`
  (definitions), `value` (constants; `***` for secret-looking names), `comments` (on or just above the statement).
- `group`: `import`, `constant`, `simple` or `definition` when consecutive statements of this kind may be shown as
  one step.

### Plan

```json
{"view": "walkthrough", "mode": "run", "focus": "whole program", "max_steps": 150,
 "steps": [...], "explain_first": ["etl/extract.py:7", ...], "truncated": false,
 "counts": {"steps": 117, "visible_steps": 117, "statements": 97}}
```

`explain_first` lists up to `max_steps` statement ids in order of importance: statements that change data, branch,
call into focused code, do I/O, or raise come first. Write explanations for these first.

Each step has an `id` (`s1`, `s2`, ...), a `type` and a `depth` (call depth within the focus). By type:

| `type` | Fields |
|---|---|
| `statement` | `stmt`, `file`, `lines`; *(run)* `call` (trace node), `occurrence`, `executions`, `changes`, `changes_unrecorded`, `value` (on `return`/`yield`), `io`, `raised`; `branch` on `if`/`match` (`taken`: `body`, `orelse`, `none`, or `possible` in scan); `loop` on `for`/`while` (`iterations`); *(scan)* `possible` (inside a branch), `repeats` (inside a loop), `see` (steps where a function already walked through starts) |
| `group` | Like `statement`, with `stmts` (several consecutive simple statements) instead of `stmt` |
| `enter` | Stepping into a function or module: `fn`, `from_step` (the call site), `args` *(run)*, `caller`, `via` (`import`, or `reference` for functions called through a variable), `def_stmt` *(scan)* |
| `return` | Back to the caller: `fn`, `to_step`, `value` *(run)*, `yield` (true when a generator yielded), `changes` (what the call site's statement changed, shown here because it happens on return), `changes_of`, `raised` |
| `loop_summary` | After the first iteration of a loop with more than 3 iterations: `stmt`, `iterations`, `detailed_iterations`, `changes` (the latest value of each variable the loop changed) |
| `unfocused_call` | A call into project code outside `--focus`: `fn`, `from_step`, *(run)* `args`, `value`, `repeats` |

Steps with `hidden_by` belong to iterations 2 and 3 of a collapsed loop: the player shows them on request.
`changes` and `value` are value summaries (section 8); `in_place: true` marks a value changed without being
reassigned.

### Lines *(run)*

`lines.events` are the raw line events: `seq`, `node`, `file`, `line`, `occ` (execution of that line in that call),
`t_ms`, `changes`, `changes_unrecorded` (changes made by lines that ran without being recorded), `raised`.
`lines.totals` gives every line's execution count; `lines.stats` the number recorded and counted only. The first 3
executions of each line in each call are recorded; later ones are counted. Lambdas and comprehensions are not
line-traced: they belong to the line that contains them.
