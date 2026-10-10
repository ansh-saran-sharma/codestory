# Walkthrough view: design spec

Status: built and released in 0.3.0. The notes below record where the result differs from the original plan.

## 1. Summary

codestory gets a second way to present a recording. The existing **story view** tells the story of the data
for a mixed audience. The new **walkthrough view** is for programmers: it steps through the code itself, line
by line or block by block, and explains what each statement does, where every name comes from, and how the
data changes.

Views and modes are independent, so there are four combinations:

| | `scan` (every possible path, nothing executed) | `run` (one real run) |
|---|---|---|
| **story** (default, unchanged) | Story of every path | Story of what happened |
| **walkthrough** (new) | Code walkthrough in reading order, with types and possible paths | Code walkthrough in execution order, with real values at every line |

The story view, its player and the storyboard format do not change.

## 2. Goals and non-goals

Goals:
- Explain each statement or block: what it does, what kind of statement it is, where each name it uses is
  defined or imported from, what it reads and writes, and what it returns.
- In `run`, show the actual values before and after each line, from a real execution.
- Moving animation, not static frames: every step animates on arrival (section 7).
- Same principles as the story player: one HTML file, works offline, no third-party code, MIT, light and dark
  themes, keyboard and phone support.

Non-goals for this version (possible later):
- Stepping into library code (pandas, requests, ...). Library calls are explained, not entered.
- Showing the program's printed output.
- Editing code from the walkthrough.
- Comparing two runs.
- Languages other than Python.

## 3. Invocation

### `/codestory` command

```
/codestory [scan | run] <entry> [--view story | walkthrough] [--focus TARGET] [--max-steps N] [other options] [-- program arguments]
```

| Option | Required? | Default | Meaning |
|---|---|---|---|
| `--view` | Optional | `story` | Which view to produce. |
| `--focus TARGET` | Optional | The whole program | Limit the walkthrough to a file (`etl/clean.py`), a function (`clean` or `etl.clean:clean`), or several, comma-separated. Ignored by the story view. |
| `--max-steps N` | Optional | 150 | How many steps get a written explanation. Steps beyond this still show the tool's facts (section 6), without prose. |

All existing options keep their meaning and defaults.

### `codestory.py`

```bash
python codestory.py scan  <script.py | -m module> --view walkthrough [--focus TARGET] [...]
python codestory.py run   <script.py | -m module> --view walkthrough [--focus TARGET] [...] [-- program arguments]
python codestory.py build walkthrough.json --bundle codestory_bundle.json [-o walkthrough.html]
```

- `--view walkthrough` must be given **when recording**, because `run` then records line by line (section 4).
  Chat-assistant users add it to their terminal command; agents add it for them.
- A walkthrough bundle is a superset of a story bundle: it can also produce the story view, so nobody needs to
  record twice.
- `build` picks the player from the document's `schema` field: `codestory.storyboard/1` uses `player.html`,
  `codestory.walkthrough/1` uses `walkthrough.html`. A walkthrough build also needs the bundle (`--bundle`),
  because the source code and facts come from it (section 5).

## 4. Recording

### `scan --view walkthrough`

Adds to the bundle, for each file in focus that's reachable from the entry point:
- the full source text;
- a **statement map**: every statement with its line range, kind, names it reads and writes, calls, and where
  each name resolves to (section 6).

Nothing is executed. Subject to `--budget`.

### `run --view walkthrough`: line-level tracing

In addition to today's call-level trace, the tracer records each line of project code as it executes, within
the focus.

- **Mechanism**: `sys.monitoring` `LINE` events on Python 3.12+; `sys.settrace` line events on older versions
  (slower). Library code is never line-traced.
- **What each line event records**: the line, the call it belongs to (trace node id), and the local variables
  that changed since the previous line in the same frame, as value summaries (the same summaries as today:
  shape, columns, dtypes and sample rows for tables, never full data).
- **Detecting changes cheaply**: a variable is re-summarized when its identity changes, or when a cheap
  fingerprint changes (type, length, shape). Known limit: an in-place mutation that changes none of these is
  shown as unchanged; the explanation may still describe it.
- **Volume control**: the first 3 executions of each line in each call are recorded in full; later executions
  are counted only. Loop iteration counts come from the loop header's count. A global cap (default 20,000
  line events) protects the bundle size; if reached, the bundle says so and the walkthrough says it covers the
  first part in detail.
- **Branches**: the line after an `if`/`elif`/`match` shows which side was taken; no extra instrumentation.
- **Exceptions**: the line where an exception was raised, and the exception, are recorded.
- **Threads**: the walkthrough follows the main thread; other threads appear as call-level summaries.
- **In-place changes**: for statements the statement map knows mutate a variable in place (`df.loc[...] = ...`,
  `counts[key] += 1`), the variable is re-read after the line runs, so those changes are recorded too.
- **Lambdas and comprehensions** are not line-traced or stepped into; they belong to the line that contains them.
- **Overhead**, measured end to end including interpreter start-up: about 2.3× a plain run for the weather pipeline
  (time spent mostly in pandas), and about 8–9× for the log checker over 20,000 lines (a tight pure-Python loop).
  The story view's recording costs 1.1× and 3× on the same programs.

Safe mode and all its guarantees apply unchanged.

### Bundle format

The schema becomes `codestory.bundle/2`. Version 1 fields are unchanged; new optional sections:
- `sources`: full source text of files in focus.
- `statements`: the statement map.
- `lines` (run): line events and per-line counts.
- `plan`: the step sequence for the walkthrough (section 5).

## 5. Steps and the division of labour

### Who does what

- **The tool builds the step sequence and the facts.** It decides which statements become steps, in what
  order, how loops collapse, and what is measured at each step. This is deterministic and verifiable.
- **The assistant writes the explanations.** It reads the plan and the source, and writes a title and a
  technical explanation for each step it covers, keyed by the step's statement id.
- **`build` merges them**: plan + facts + source from the bundle, explanations from `walkthrough.json`.

This keeps the assistant's output small, means source code is never retyped (so it can't be mistyped), and
keeps every number in the player measured rather than written.

### What becomes a step

- One statement is one step. A multi-line statement is one step.
- Simple consecutive statements are grouped into one step: a run of imports, a run of constant assignments, a
  run of module-level definitions, or a run of trivial assignments (a literal, a name or an attribute assigned to
  a plain variable). Anything that computes, indexes or mutates stays its own step.
- Comments and docstrings are not steps; the assistant uses them as context.
- Function and class definitions are steps in `scan` reading order; in `run` they appear only as part of the
  module-level code that defines them, grouped. Class bodies are never stepped into.

### Order

- `run`: execution order. A call to a project function steps into it (its statements follow) and then returns
  to the caller. "Step over" in the player skips the inside.
- `scan`: reading order along the call flow. Start at the entry's top-level code; enter each project module at
  its first import and each project function at its first call site, with nested calls in evaluation order
  (arguments first). Functions used as values (for example looped over and called through a variable) are entered
  where they're referenced. Later calls to an already-explained function link to it instead of repeating it.
  Branches show both sides, marked as possible.

### Loops

- `run`: loops with up to 3 iterations are shown in full, since each iteration is recorded and may do different
  work (for example calling a different function each time). Longer loops show the first iteration step by step,
  then one **loop summary** step: the iteration count and the combined effect (the latest value of every variable
  the loop changed). Iterations 2 and 3 are kept in the plan, hidden, for the player to show on request.
- Generators: each `yield` returns to the consumer as a return step marked as a yield, with the yielded value.
- `scan`: the loop body is shown once, marked "repeats for each item".

### Libraries

A call into a library is part of its statement's step. The facts say where it comes from (installed package
or standard library, with the module path) and, in `run`, what it returned. The walkthrough never descends
into library code.

### Ranking

The plan suggests which statements to explain first (`explain_first`, up to `--max-steps`): statements that raise,
change data (tables, collections), branch, call into focused code, or do I/O rank highest.

### Size

- Steps beyond `--max-steps` (default 150) have facts but no written explanation; the player shows them in a
  compact style.
- `--focus` limits the steps to chosen files or functions. Code outside the focus appears as a single "call
  into unfocused code" step with its inputs and outputs.

## 6. Facts (computed by the tool, every step)

| Fact | scan | run |
|---|---|---|
| Statement kind: import, constant, assignment, call, return, branch, loop, definition, with, try, raise | ✓ | ✓ |
| For each name used: local variable, parameter, constant (with value), function defined at file:line, imported from project file:line, from an installed package, or from the standard library | ✓ | ✓ |
| Names read and names written | ✓ | ✓ |
| Type hints, where present | ✓ | ✓ |
| Values of changed variables, before and after (summaries) | | ✓ |
| Return value | | ✓ |
| Branch taken | possible sides | ✓ |
| Times executed, loop iterations | | ✓ |
| I/O performed (file, database, API, email) and how safe mode handled it | where visible in the source | ✓ |
| Exception raised | | ✓ |

The player marks facts as measured, so readers can tell them apart from the written explanation.

## 7. The walkthrough player (`walkthrough.html`)

### Technology

Agreed after comparing the options in a live demo:

| Part | Technology |
|---|---|
| Code, explanations, facts, variables | HTML and CSS: real text, selectable and searchable |
| Highlight moving between lines, scrolling, cross-fades | CSS transitions |
| Call arrows, returns, values travelling between lines and files | An SVG layer on top of the code |
| Sequencing within a step, autoplay, speed | codestory's own animation engine (shared with the story player, factored into one module that `build` inlines), using the Web Animations API where it fits |
| Large data moments (hundreds of rows changing) | Canvas, optional |
| 3D | Not used |

Syntax highlighting is a small Python highlighter written for codestory: keywords, built-ins, strings
(including f-strings and triple-quoted), numbers, comments, decorators, and definition names.

### Layout

```
┌─ file tabs ──────────────────────────────────────┬─ Step 14 of 86 ─────────────────────────┐
│ code pane, line numbers, highlight bar            │ title                                   │
│ SVG layer for arrows and travelling values        │ explanation                             │
│                                                   │ facts (measured)                        │
│                                                   │ variables: before → after, sample rows  │
├───────────────────────────────────────────────────┴─────────────────────────────────────────┤
│ call stack breadcrumb   │ outline (jump anywhere)   │ ◀ ▶  step over  step out  autoplay  1×  │
└─────────────────────────────────────────────────────────────────────────────────────────────┘
```

On phones, the code and the explanation stack vertically; arrows run vertically.

### Animation per step type

Every step plays an entry animation of about 0.6–2 seconds on arrival.

| Step | Animation |
|---|---|
| Any statement | Highlight glides to the new lines; the code pane scrolls smoothly if needed; the explanation cross-fades |
| Assignment | Changed variables pulse in the variables panel; numbers count to their new value; in `run`, the value travels as a token from the line to the panel |
| Filter or reshape of a table (`run`) | The row count counts to its new value with a +/− marker, a proportion bar shrinks or grows, and new columns fade in, highlighted. (The sample rows are the first three, which a filter often leaves unchanged, so they aren't animated row by row. The optional Canvas particle flow is not built.) |
| Call into a project function | An arrow draws from the call to the definition; a token carrying the arguments travels along it; the code pane moves to the definition (cross-file: the tab switches with a slide); the breadcrumb grows |
| Return | A token with the return value travels back to the call site; the breadcrumb shrinks |
| Library call | A badge appears naming the source ("pandas, installed package"), and in `run` the returned value appears |
| Branch | The condition highlights; in `run` a True or False chip appears and the untaken block dims; in `scan` both blocks are outlined as possible |
| Loop summary | An iteration counter ticks up to the total; the combined effect counts in |
| Import group | Module names appear one by one with their origin: project file, installed package or standard library |
| Constant group | Each name appears with its value |
| Exception | The raising line is marked in red with the exception; the breadcrumb shows where it propagated |

### Navigation and playback

- Next and previous step (→ and ←); step over (↓) and step out (↑); Home and End. Step over and step out land on
  the return step, which shows the value coming back and what it changed at the call site.
- Autoplay at 0.5×–2×, starting on its own unless reduced motion is set. Each step plays its animation, then holds
  long enough to read its explanation (about 3.6 words a second); steps without one move on after about 1.5 s.
- Moving forward plays the arrival animation. Moving backward, or jumping, shows the target step's finished
  state immediately. Every step's finished state is a pure function of the step, so it's always the same.
- Outline panel: the step tree by file and function; click to jump.
- Clicking a name with a definition or import jumps the code pane to it without changing the current step.

### Quality floor

- Respects `prefers-reduced-motion`: movement becomes fades; autoplay is off by default.
- Keyboard accessible, visible focus, explanation announced to screen readers.
- Measured on a 2,000-line file: about 3 ms to jump to any step, and normal frame times while animating. Files
  are rendered in full; rendering only the visible lines of much longer files is future work.

## 8. Writing the explanations (`SKILL.md`)

A new section in `SKILL.md`, plus `references/walkthrough-guide.md`:
- Audience: programmers. Use technical terms precisely; don't simplify.
- One explanation per statement id; it applies to every time that statement runs. Optional notes for a specific
  occurrence (for example "on the second iteration...").
- Explain intent and mechanism ("filters with a boolean mask on `temp`") and anything non-obvious (a
  side-effect, a mutation in place, a performance trap). Don't restate the facts the tool already shows.
- Never invent values; they come from the facts.
- Cover the most important steps first when the cap applies: data-changing statements, branches, calls into
  focus, I/O.

## 9. New and changed files

| File | Change |
|---|---|
| `codestory.py` | `--view`, `--focus`, `--max-steps`; statement map; line tracer; plan builder; bundle schema 2; `build` dispatch by schema and `--bundle` |
| `walkthrough.html` | New player |
| `walkthrough.schema.json` | New: format of `walkthrough.json` |
| `player.html` | Animation engine factored out to share with `walkthrough.html` (no behaviour change) |
| `SKILL.md`, `references/walkthrough-guide.md` | How to write walkthrough explanations |
| `references/bundle-format.md` | Bundle schema 2 |
| `README.md`, `USAGE.md` | `--view`, `--focus`, `--max-steps`, with examples |
| `examples/` | A `run` walkthrough of the weather pipeline and a `scan` walkthrough of the log checker |

## 10. Acceptance criteria

- All four combinations (scan or run, story or walkthrough) work from every assistant described in `USAGE.md`.
- The story view and existing bundles and storyboards behave exactly as in 0.2.0.
- A `run` walkthrough of the weather example shows correct before and after values at every data-changing line
  (in `drop_invalid`: 601 rows in, 582 after `dropna`, 576 returned), the taken side of each branch, and loop counts that match the trace.
- Safe mode guarantees are unchanged with line tracing on: the weather example's database file is unchanged
  after a safe-mode run.
- Every step type in section 7 has its animation, in light and dark themes, on desktop and phone, and with
  reduced motion.
- Going back or jumping to a step always shows the same finished state.
- Tracing overhead on the weather example is measured and documented.

## 11. Milestones

1. **Recording**: statement map, line tracer, plan builder, bundle schema 2, with tests on both examples.
2. **Player**: `walkthrough.html` built against fixture data, with every step type's animation. Built; it also
   brought forward `build`'s merge of document and bundle, since the player needs real input to be tested.
3. **Glue**: `walkthrough.schema.json` and validation in `build`, `SKILL.md` section and walkthrough guide. Built;
   tested end to end by following only `SKILL.md` and the guide on a program not used during development.
4. **Examples and docs**: both example walkthroughs, README, USAGE and changelog. Built, with a third example
   (stock-check) and a walkthrough demo GIF.

Each milestone is a separate pull request.
