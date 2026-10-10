# Writing a walkthrough

A walkthrough is a line-by-line, debugger-style replay of the code for programmers. The tool has already decided
every step, recorded every value and resolved every name. Your job is the one thing it can't do: explain what each
important statement is for and how it works.

## Contents
1. What you write, and what the player already shows
2. Choosing what to explain
3. Reading the bundle for one statement
4. Titles
5. Explanations
6. Numbers and repeated statements
7. Notes for one step
8. Example
9. Checklist

## 1. What you write, and what the player already shows

You write `walkthrough.json` (format: `walkthrough.schema.json`):

```json
{
  "schema": "codestory.walkthrough/1",
  "title": "Daily weather pipeline, line by line",
  "subtitle": "One run on 1 October 2026: readings in, a cleaned daily summary, a report, a table and an alert out.",
  "entry": "main.py --date 2026-10-01 --full-refresh",
  "explanations": {
    "etl/clean.py:15": {"title": "Drop rows with missing values", "text": "..."}
  },
  "notes": {"s65": "..."}
}
```

The player already shows, for every step, without you writing it:
- the code, highlighted, with the call stack;
- the kind of statement (assignment, call, decision, loop...);
- where every name comes from: parameter, local, constant with its value, a project function with its file and
  line, an installed package, the standard library;
- every call and its origin (`pandas.read_csv, from the installed package pandas`);
- in `run`: the values before and after (rows, columns, sample rows), what was returned or yielded, which side of
  each branch ran, how many times a line and a loop ran, the I/O performed and what safe mode did with it;
- animations for calls, returns, changed values, branches and loops.

So don't restate those. Write what the facts can't say: **purpose, mechanism and consequences.**

Steps without an explanation still appear, with their facts and a note that there's no written explanation.
That's expected for trivial statements.

## 2. Choosing what to explain

`plan.explain_first` lists statement ids ranked by importance: statements that raise, change data, branch, call
into focused code or do I/O come first. Work down it and explain up to `plan.max_steps` statements (default 150),
unless the user asked for more or less.

- **Grouped steps** (a step with `stmts`, such as a run of imports or constants): key one explanation to the
  **first** statement of the group and describe the whole group. `build` warns if you key one to a later statement,
  because it would never be shown.
- **Skip** statements whose facts say everything: `x = 0`, a plain `return result`, imports of well-known modules.
  Keep them if something about them is surprising.
- **Enter steps** (stepping into a function) show the function's docstring. If a function has none and its purpose
  isn't obvious, explain it on the statement that calls it, or add a note on the enter step (section 7).
- If `plan.counts.statements` is far more than `max_steps`, say in your reply how many you explained, and offer
  `--focus` for the parts left without prose.

## 3. Reading the bundle for one statement

For each statement id `sid` you explain:
- `statements[sid]`: `kind`, `line`–`end`, `reads`, `writes`, `mutates`, `names` (where each name comes from),
  `calls` (with origin), `references`, `io`, `hints`, `comments`, `doc`.
- The code itself: `sources[file]`, lines `line` to `end`.
- *(run)* The steps showing it: every entry in `plan.steps` whose `stmt` is `sid` (or whose `stmts` contains it).
  Their `changes`, `value`, `branch`, `loop`, `io`, `executions`, `raised`, and `occurrence` tell you what
  actually happened. A statement that calls a function has its result on the matching `return` step, under
  `changes` (with `changes_of` pointing back to the statement's step).
- The surrounding statements, so your explanation fits the flow.

## 4. Titles

- Sentence case, starting with a verb, at most 60 characters.
- Say what the statement achieves, not its syntax: **"Drop rows with missing values"**, not "Call dropna" or
  "Assignment to df".
- Unique enough to scan in the outline. Two statements in different functions shouldn't both be "Return the
  result".

## 5. Explanations

- **1–4 sentences, at most 700 characters, plain text.** No Markdown: backticks and asterisks would show literally.
  Write names as they appear in the code: df.loc, MIN_TEMP_C.
- **The audience is programmers.** Use the precise term (boolean mask, left join, generator, context manager,
  vectorised, in place) without defining it.
- **Mechanism, then purpose, then anything non-obvious:**
  - mechanism: how the statement does what it does ("builds a boolean mask from two comparisons combined with &,
    then indexes df with it");
  - purpose: why it's there in this program ("so only physically plausible readings reach the summary");
  - non-obvious: in-place mutation, laziness, evaluation order, a default that matters, an edge case, a performance
    trap, a likely bug. These are the most valuable sentences you can write.
- **Don't paraphrase the code literally.** "Assigns df.dropna(subset=['temp']) to df" says nothing the code doesn't.
- **Don't speculate.** If intent isn't clear from the code, comments, docstrings or names, describe the behaviour
  and stop.
- **Tense.** `run`: what happened in this run, past or present ("19 rows go, leaving 582"). `scan`: what the code
  does whenever it runs, conditional where it depends on input ("if any anomalies are found...").
- **Secrets.** Never write a value the bundle masked (`***`), even if it's visible in the source.

## 6. Numbers and repeated statements

One explanation is shown at **every** execution of its statement. So:
- If the statement ran once (`executions` is 1 or absent, and only one step shows it), quote its measured values:
  "19 rows go, leaving 582".
- If it ran several times, describe the pattern ("each iteration removes...") or quote totals that hold for all
  of them, such as a loop summary's final values. Put a value that's true of one execution in a note on that step.
- Every number you write must appear in, or follow arithmetically from, the bundle. Check differences yourself.
- In `scan`, there are no measured values: only quote constants and literals from the source.

## 7. Notes for one step

`notes` are keyed by **step id** (`"s65"`) and shown on that step only, under the explanation. Use them for:
- one occurrence of a repeated statement ("Second iteration: step is now drop_invalid");
- enter, return, loop summary or unfocused-call steps, which can't have explanations;
- pointing out something in the measured values ("Only 3 of the 24 summary rows are flagged, all Mesa Top").

At most 300 characters each. Use them sparingly.

## 8. Example

From the weather pipeline (`examples/weather-pipeline/walkthrough.json`):

```json
"etl/clean.py:15": {
  "title": "Drop rows with missing values",
  "text": "dropna with subset only considers temp and station_id: a row is removed if either is NaN. 19 rows go, leaving 582."
},
"etl/clean.py:16": {
  "title": "Keep plausible temperatures",
  "text": "Builds a boolean mask from two comparisons combined with & (element-wise and; the parentheses are required because & binds tighter than >=), then indexes df with it. The sensor glitches reading 999 are removed: 576 rows remain."
},
"etl/clean.py:25": {
  "title": "Apply each cleaning step in order",
  "text": "Iterates over a tuple of functions. Functions are first-class values, so step is bound to to_celsius, then drop_invalid, then dedupe; static analysis can't see these calls, which is why codestory records them at run time."
}
```

What makes these good: each names the mechanism precisely, explains a detail a reader could trip over (the subset
argument, operator precedence, first-class functions), and quotes only numbers measured once.

## 9. Checklist

- Every key in `explanations` is a statement id from `statements`; every key in `notes` is a step id from
  `plan.steps`.
- Grouped steps are explained on their first statement.
- The most important statements in `explain_first` are covered, up to `max_steps`.
- Titles are at most 60 characters and start with a verb; texts are plain text, at most 700 characters.
- Every number matches the bundle, and repeated statements don't quote a single execution's values.
- `build` runs without problems:
  ```bash
  python codestory.py build walkthrough.json --bundle codestory_bundle.json -o walkthrough.html
  ```
