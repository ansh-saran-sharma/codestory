# codestory

Turns a Python program into an animated story of how it works: what it imports, the settings it reads,
the data it loads, every transformation, the decisions it makes, and what it writes. The result is one
HTML file that plays like a video, steps like a slideshow, and opens in any browser, offline.

It works in two modes:

- **`scan`** explains the code: every path it can take, without running anything. Use it to walk a colleague
  or stakeholder through a codebase.
- **`run`** shows what actually happened in one real run: which branches were taken and how many rows were
  read, filtered, transformed and written. Use it when the data or the outcome changes from day to day.

![A codestory scene: 601 rows flow into drop_invalid() and 576 come out](docs/demo.gif)

## Watch a demo

Two finished stories, playable in your browser:

- **[Daily weather pipeline](https://ansh-saran-sharma.github.io/codestory/examples/weather-pipeline/story.html)**,
  a `run`: 601 sensor readings are cleaned, summarized per station, saved to a report and a database, and
  trigger an alert, all held in safe mode.
- **[Nightly web error check](https://ansh-saran-sharma.github.io/codestory/examples/log-check-scan/story.html)**,
  a `scan`: every path through a log checker that emails on-call when too many requests fail, without
  running it.

Press space to play or pause, use the arrow keys to move between scenes, and click any card to see its code
and data. The source projects, bundles and storyboards are in [`examples/`](examples/).

## Contents

1. Install
2. Use it from your AI assistant
3. Use it from the command line
4. scan or run?
5. Safe mode
6. What the bundle contains
7. Troubleshooting
8. Files
9. Contributing
10. License

## 1. Install

The folder is an [Agent Skill](https://agentskills.io): `SKILL.md` plus the files it uses. Keep the folder
name `codestory`.

| Assistant | Where to put the folder |
|---|---|
| Claude Code | `~/.claude/skills/codestory/` (all projects) or `<project>/.claude/skills/codestory/` |
| GitHub Copilot in VS Code | `<project>/.github/skills/codestory/` (Copilot also reads `.claude/skills/` and `.agents/skills/`) |
| OpenAI Codex, Cursor, Gemini CLI and other Agent Skills tools | `<project>/.agents/skills/codestory/` or that tool's personal skills folder |
| claude.ai | Upload `codestory.skill` (or the zip) as a custom skill in settings |
| ChatGPT and other chat assistants | Use its skills feature if your plan has one. Otherwise, use a project or custom GPT: paste `SKILL.md` into the instructions and add the other files as knowledge files |

Requirements: Python 3.8 or later. `codestory.py` uses only the standard library, so there is nothing to
`pip install`.

## 2. Use it from your AI assistant

Whichever assistant you use, the request is the same. Tell it:

- **the entry point**: the script you normally run, such as `main.py`;
- **the mode**: explain the code (`scan`) or show what a run did (`run`). If you don't say, the assistant
  picks from your wording and asks if it can't tell;
- **arguments**, for `run` only: the ones you normally pass, such as `--date 2026-10-01`;
- optionally, **the audience**: "for our product manager" gives plainer narration, "for the engineering team"
  more technical detail.

Example requests:

```text
/codestory main.py
/codestory main.py scan, for a non-technical stakeholder
Animate how pipeline/run.py works so I can onboard a new teammate.
Show me what main.py does when run with --date 2026-10-01 --full-refresh.
Why did only 12 rows reach the report today? Trace main.py with today's input.
Here's my codestory_bundle.json. Turn it into a story.
```

How the conversation goes depends on whether the assistant can run commands on your computer.

### Agent assistants (they run commands for you)

GitHub Copilot in VS Code (agent mode), Claude Code, OpenAI Codex, Cursor, Gemini CLI.

1. Open your project, then open the assistant's chat.
2. Type your request, for example `/codestory main.py`.
3. The assistant finds your project's Python environment (for example `.venv`) and records the program:
   - for `scan`, it runs straight away, because nothing is executed;
   - for `run`, it **first shows you the exact command and what safe mode will do, and waits for your OK**,
     because it is about to run your program.
4. It writes `storyboard.json`, builds `story.html`, and tells you where the file is, plus any warnings (for
   example, a side effect safe mode couldn't intercept).
5. Open `story.html` in your browser.

Assistant-specific notes:

**GitHub Copilot in VS Code**

1. Put the folder in `<project>/.github/skills/codestory/`.
2. Open Copilot Chat (`Ctrl+Alt+I` on Windows and Linux, `Ctrl+Cmd+I` on macOS) and switch the mode picker
   to **Agent**. Ask and Edit modes can't run terminal commands, so the skill can't record your program there.
3. Type `/` to check that `codestory` appears in the list, then type your request: `/codestory main.py`.
4. When Copilot asks to run a terminal command, review it and choose **Continue** (or **Allow**).
5. If the skill doesn't appear, check that agent skills are enabled in your VS Code settings (search
   settings for "skills"), and that the folder contains `SKILL.md` directly, not inside a subfolder.

**Claude Code**

1. Put the folder in `~/.claude/skills/codestory/` or `<project>/.claude/skills/codestory/`.
2. Start `claude` in your project folder.
3. Type `/codestory main.py`, or describe what you want in plain words. Claude Code picks the skill from
   your wording.
4. Approve the `run` command when asked.

**OpenAI Codex**

1. Put the folder in `<project>/.agents/skills/codestory/` (or your personal Codex skills folder).
2. Run `/skills` to check that it's listed.
3. Mention it explicitly with `$codestory`, or describe what you want in plain words:
   `$codestory main.py -- --date 2026-10-01`.
4. Approve the `run` command when asked.

**Cursor, Gemini CLI and other tools that support Agent Skills**

Put the folder in `<project>/.agents/skills/codestory/` (or the tool's own skills folder), use the tool's
agent mode, and ask in plain words. The steps are the same as above.

### Chat assistants (you run one command, the assistant does the rest)

claude.ai, ChatGPT, and other browser chats. They can't run your program on your computer, so for `run` you
record it yourself with one command, then upload the result.

**claude.ai**

1. Turn on code execution: **Settings → Capabilities → Code execution and file creation**.
2. Add the skill: in the same Capabilities settings, under **Skills**, upload `codestory.skill` (or the zip)
   and make sure it's switched on.
3. Start a new chat and ask.
   - **To explain the code (`scan`)**: upload your script, or a zip of the project, and ask
     "Explain how this code works with codestory." Claude runs the scan itself, writes the story and gives
     you `story.html`.
   - **To show a real run (`run`)**: on your computer, with your project's virtualenv active, run
     ```bash
     python codestory.py run main.py -- <your usual arguments>
     ```
     Then upload the `codestory_bundle.json` it creates and ask "Turn this into a story." Claude gives you
     `story.html`. If you don't have `codestory.py` yet, ask Claude for it; it's part of the skill.
4. Download `story.html` and open it in your browser.

**ChatGPT**

1. If your plan supports skills, add the skill folder there. Otherwise, create a **Project** (or a custom
   GPT): paste the contents of `SKILL.md` into its instructions, and upload `codestory.py`, `player.html`,
   `storyboard.schema.json` and the two files in `references/` as project files.
2. For `run`, record the program on your computer first (the command above) and upload
   `codestory_bundle.json`. For `scan`, uploading the script is enough if ChatGPT can run Python in your
   plan; otherwise run `python codestory.py scan main.py` yourself and upload the bundle.
3. Ask: "Use the codestory instructions to turn this into a story."
4. ChatGPT returns `story.html`, or `storyboard.json` if it couldn't build the file. In that case, run
   ```bash
   python codestory.py build storyboard.json -o story.html
   ```
   or open `player.html` in your browser and drag `storyboard.json` onto it.

**Any other chat assistant**

Paste `SKILL.md` as instructions (or at the start of the chat), upload `codestory_bundle.json` and
`storyboard.schema.json`, and ask for `storyboard.json`. Then build it with the command above, or drop it onto
`player.html`.

## 3. Use it from the command line

The same three steps the assistant performs:

```bash
# 1. Record (pick one). Run with your project's Python environment active.
python codestory.py scan main.py                        # explain the code: nothing is executed
python codestory.py run  main.py -- --date 2026-10-01   # one real run; arguments for your program go after --

# 2. Give codestory_bundle.json to your assistant, which writes storyboard.json

# 3. Build one shareable HTML file
python codestory.py build storyboard.json -o story.html
```

Options:

| Command | Option | What it does |
|---|---|---|
| `scan`, `run` | `-o FILE` | Bundle file name (default `codestory_bundle.json`) |
| `scan`, `run` | `--root DIR` | Project root, when it isn't the current folder or the entry script's folder |
| `scan`, `run` | `--budget N` | Maximum characters of source code in the bundle (default 240,000) |
| `run` | `--live` | Turn safe mode off: writes, posts and emails really happen |
| `run` | `--allow-subprocess` | Let the program start other programs in safe mode |
| `build` | `-o FILE` | Output file name (default `story.html`) |
| `build` | `--force` | Build even if the storyboard has problems (not recommended) |

Watching a story: space plays and pauses; the left and right arrows move between scenes; Home and End jump to
the start and end. Click any card to see its code, columns and sample rows. Click a station on the line at
the top to jump to that scene.

## 4. scan or run?

| | `scan` | `run` |
|---|---|---|
| Use it to | explain the whole flow to someone | see what happened on a particular day |
| Executes your code | no | yes, in safe mode by default |
| Needs your environment (packages, data, database access) | no | yes |
| Branches | all shown as possible | taken path solid, others greyed |
| Data | names and types only | row counts, columns and samples at each step |
| Dynamic calls (registries, `getattr`) | may be missed | captured |

## 5. Safe mode (default for `run`)

Your code is never edited. codestory launches it the way `python main.py` would and watches from outside.

| Side effect | What safe mode does |
|---|---|
| File writes, folder creation, deletes, renames | redirected to a temporary sandbox folder; later reads see the sandbox copy |
| SQLite | the program works on a copy of the database file in the sandbox |
| PostgreSQL (psycopg2, psycopg), MySQL (pymysql) | INSERT/UPDATE/DELETE and schema changes are not sent; they are saved to `db_writes/*.jsonl` in the sandbox. SELECTs run normally |
| HTTP POST/PUT/PATCH/DELETE (requests, httpx, urllib) | blocked; the program receives a fake 200 OK. GETs run normally |
| Email (smtplib) | blocked and recorded |
| Starting other programs | blocked unless `--allow-subprocess` |

Reads really happen: input files are read, SELECT queries run, and GET requests reach the API. Point the
program at test data or a dev database if even reads matter.

Limits:
- A read that comes after a shadowed write to a server database does not see the shadowed rows. codestory
  flags this in the story.
- `INSERT ... RETURNING` cannot return real ids.
- Cloud SDKs (boto3, Google Cloud, Azure), MongoDB, Redis and Kafka are not intercepted yet. codestory warns
  when it sees them.
- The PostgreSQL and MySQL interception has been tested with a simulated driver only. Try it against a dev
  database before relying on it.

## 6. What the bundle contains

Structure (imports, constants, functions, call graph, I/O sites), and for `run` a call tree with timings
and a summary of each argument and return value: shape, columns, dtypes and 3 sample rows for tables, never
the full data. Values that look like secrets are masked. Source code is included for the functions that
matter, within a size budget, so large repositories stay small: only code reachable from the entry point is
read. Full field reference: `references/bundle-format.md`.

Check the bundle before uploading it to a chat assistant if your data is sensitive. It contains sample rows.

## 7. Troubleshooting

| Problem | Fix |
|---|---|
| `ModuleNotFoundError` during `run` | Activate your project's virtualenv (or conda env) first. codestory must run with the same Python as your program. |
| The assistant doesn't use the skill | Check the folder location and that `SKILL.md` sits directly inside `codestory/`. Mention it by name (`/codestory`, or `$codestory` in Codex). |
| Copilot can't run the command | Switch Copilot Chat to Agent mode and allow terminal commands. |
| The story file shows "Open a storyboard" | It's the empty player. Build with `codestory.py build`, or drop `storyboard.json` onto it. |
| `build` reports storyboard problems | Paste the messages back to the assistant and ask it to fix the storyboard. |
| Fonts look plain | Stories load the Overpass font from Google Fonts when online and use system fonts offline. The story still works. |
| A side effect really happened | Look for "REAL side effect" lines in the `run` output and `real_effects` in the bundle. If safe mode should have caught it, please report the library involved. |

## 8. Files

- `SKILL.md`: instructions that teach the assistant to write a good storyboard from a bundle.
- `references/bundle-format.md`, `references/example-storyboard.json`: read by the assistant when needed.
- `codestory.py`: scan, run, build. Python 3.8+, standard library only.
- `player.html`: the player, with its own small animation engine. One file, no third-party code, works in
  any modern browser.
- `storyboard.schema.json`: the contract between the assistant and the player.
- `examples/weather-pipeline/`: a `run` of a pandas + SQLite pipeline, with its bundle, storyboard and story.
- `examples/log-check-scan/`: a `scan` of a stdlib-only log checker, with its bundle, storyboard and story.
- `docs/demo.gif`: the animation at the top of this page.

## 9. Contributing

Bug reports and ideas are welcome, especially a library safe mode missed or a story that came out wrong.
See [CONTRIBUTING.md](CONTRIBUTING.md). Report security problems privately, as described in
[SECURITY.md](SECURITY.md). Changes are listed in [CHANGELOG.md](CHANGELOG.md).

## 10. License

[MIT](LICENSE). The whole project, including the player, is original code under this license. Stories
request the [Overpass](https://fonts.google.com/specimen/Overpass) fonts from Google Fonts when viewed online;
the fonts are not included in this repository.
