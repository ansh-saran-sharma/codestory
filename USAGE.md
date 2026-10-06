# Using codestory

This page shows exactly how to invoke codestory, in both modes and with every option, in each kind of
assistant. If you haven't installed it yet, see [Install](README.md#1-install) in the README.

## Contents

1. How invocation works
2. The `/codestory` command
3. Every variant, with examples
4. Agents: Claude Code, GitHub Copilot, OpenAI Codex, Cursor, Gemini CLI
5. Chat assistants: claude.ai, ChatGPT, others
6. Without an assistant
7. Questions

## 1. How invocation works

Three things explain everything else on this page.

**1. You invoke the skill with a chat message, not a terminal command.** A skill is instructions the assistant
follows. You write a message, either the `/codestory` command or plain words, and the assistant runs
`codestory.py` for you with the right options.

**2. There is one command syntax, the same in every assistant:**

```
/codestory [scan | run] <entry> [options] [-- program arguments]
```

Plain language works too. "Walk my manager through how main.py works" is the same as
`/codestory scan main.py --audience "my manager"`. The command is just more precise.

**3. Where you type the options depends on whether the assistant can run commands on your computer.**

| | Agents (Claude Code, Copilot agent mode, Codex, Cursor, Gemini CLI) | Chat assistants (claude.ai, ChatGPT) |
|---|---|---|
| `scan` | Everything in the chat | Everything in the chat, after uploading your code |
| `run` | Everything in the chat | Recording options and program arguments in **your terminal**; story options in the chat |
| Who runs `codestory.py` | The assistant, on your computer | You, for `run`. The assistant, for `scan` and `build` |
| You get | `story.html` in your project folder | `story.html` to download |

Chat assistants can't run your program on your computer, because it needs your Python packages, data and
database access. So for `run`, you record the program yourself with one command and upload the result.

## 2. The `/codestory` command

```
/codestory [scan | run] <entry> [options] [-- program arguments]
```

How to read it: `<entry>` is something you fill in and must give. Anything in `[square brackets]` is optional.
`scan | run` means "one of these".

### What's required

Only one thing: **the entry**, meaning what to record. Everything else has a default.

```
/codestory main.py
```

is a complete request. For `run`, also give **your program's own arguments if your program needs them** to
start (for example a required `--date`). That's a requirement of your program, not of codestory.

### Every part, with its default

| Part | Required? | If you leave it out | What it does | Modes |
|---|---|---|---|---|
| `<entry>` | **Required** | — | What to record. One of: a script (`main.py`, `jobs/nightly.py`); a module started with `python -m`, written `-m package.module`; or an existing `codestory_bundle.json` to turn into a story. | both |
| `scan` or `run` | Optional | The assistant picks from your wording ("explain" → `scan`, "what happened" → `run`) and asks if it can't tell. With nothing to go on, it uses `scan`. | The mode. | |
| `--audience TEXT` | Optional | A mixed audience: plain narration for non-programmers, with the code on every card for developers. | Who the story is for, for example `stakeholders`, `engineers`, `"new team members"`. Changes the narration. | both |
| `--out FILE` | Optional | `story.html` | Name of the story file. | both |
| `--root DIR` | Optional | The folder you're in, if it contains the entry; otherwise the entry's folder. For `-m`, the folder you're in. | The project's root folder. Needed only when imports don't resolve from those defaults, as in some monorepos. | both |
| `--budget N` | Optional | 240,000 characters | Maximum characters of source code to include. Lower it for very large codebases or small chat limits. | both |
| `--live` | Optional | **Safe mode is on**: writes go to a sandbox, database writes are captured, web posts and emails are blocked. | Turn safe mode off: everything really happens. | run |
| `--allow-subprocess` | Optional | Your program can't start other programs; the attempt is recorded and skipped. | Let your program start other programs. | run |
| `-- ...` | Optional for codestory; required if your program needs arguments | Your program runs with no arguments, as if you typed `python main.py`. | Everything after a bare `--` goes to **your program**, exactly as written. | run |

In `scan`, `--live`, `--allow-subprocess` and program arguments don't apply, because nothing is executed.

Two rules worth remembering:

- **codestory's options go before `--`, your program's arguments go after it.** In
  `/codestory run main.py --live -- --date 2026-10-01`, `--live` is for codestory and `--date 2026-10-01` is
  for `main.py`.
- **`run` always asks before executing.** In agents, the assistant shows you the exact command and what safe
  mode will do, and waits for your OK. It never adds `--live` or `--allow-subprocess` unless you asked.

## 3. Every variant, with examples

The command is the same in Claude Code, GitHub Copilot, Cursor and Gemini CLI. In OpenAI Codex, start with
`$codestory` instead of `/codestory`. The last column shows a plain-language request that does the same thing.

The first row is the minimum. Every other row adds optional parts to it; anything a row leaves out takes its
default from the table above.

| Variant | Command | In plain words |
|---|---|---|
| The minimum: only the required entry | `/codestory main.py` | "Animate how main.py works." |
| Explain the code | `/codestory scan main.py` | "Explain how main.py works with codestory." |
| Explain it for a specific audience | `/codestory scan main.py --audience stakeholders` | "Make a codestory of main.py for our stakeholders." |
| Show what a run did (no arguments) | `/codestory run main.py` | "Show me what main.py does when it runs." |
| Run with your program's arguments | `/codestory run main.py -- --date 2026-10-01 --full-refresh` | "Show what main.py does with --date 2026-10-01 --full-refresh." |
| Run with real side effects | `/codestory run main.py --live -- --date 2026-10-01` | "Trace main.py for 1 Oct and let it really write its outputs." |
| Run a program that starts other programs | `/codestory run main.py --allow-subprocess` | "Trace main.py; it's fine for it to call other programs." |
| A module started with `python -m` | `/codestory run -m etl.cli -- --full-refresh` | "Trace python -m etl.cli --full-refresh." |
| Explain a module | `/codestory scan -m etl.cli` | "Explain how the etl.cli module works." |
| Project root elsewhere | `/codestory scan services/billing/app.py --root services/billing` | "Explain services/billing/app.py; the project root is services/billing." |
| A very large codebase | `/codestory scan main.py --budget 120000` | "Explain main.py, but keep the bundle small." |
| Choose the story file name | `/codestory run main.py --out nightly-2026-10-01.html -- --date 2026-10-01` | "...and save it as nightly-2026-10-01.html." |
| Story from an existing bundle | `/codestory codestory_bundle.json` | "Turn codestory_bundle.json into a story." |
| Everything at once | `/codestory run -m etl.cli --root . --budget 150000 --live --allow-subprocess --audience engineers --out etl.html -- --full-refresh` | |

Combine options freely. Order among them doesn't matter, as long as your program's arguments come last,
after `--`.

## 4. Agents

Agents run `codestory.py` on your computer, so you type everything in the chat. Open your project folder
first: the assistant works from it, and finds your Python environment (for example `.venv`) there.

What happens after you send the command:

1. For `scan`, the assistant records straight away; nothing of yours is executed. No approval is needed.
2. For `run`, it shows you the exact command and what safe mode will do, then **waits for your OK**:
   > I'll run `python codestory.py run main.py -- --date 2026-10-01`. Safe mode is on: file writes go to a
   > temporary folder, database writes are captured instead of applied, and web posts and emails are blocked.
   > Reads really happen. OK to go ahead?
3. It writes the storyboard, builds the story, and tells you where `story.html` is (or your `--out` name),
   plus any warnings.
4. Open the file in your browser.

### Claude Code

- **Install**: put the folder in `~/.claude/skills/codestory/` (all projects) or
  `<project>/.claude/skills/codestory/` (one project).
- **Start**: run `claude` in your project folder.
- **Check** (optional): type `/` and look for `codestory` in the list.
- **Invoke**: type the command, or plain words.

```
/codestory scan main.py --audience stakeholders
/codestory run main.py -- --date 2026-10-01
/codestory run -m etl.cli --live -- --full-refresh
```

- **Approve**: when Claude Code asks permission to run the command, review it and approve.

### GitHub Copilot in VS Code

- **Install**: put the folder in `<project>/.github/skills/codestory/` (Copilot also reads `.claude/skills/`
  and `.agents/skills/`).
- **Start**: open Copilot Chat (`Ctrl+Alt+I` on Windows and Linux, `Ctrl+Cmd+I` on macOS) and choose
  **Agent** in the mode picker. Ask and Edit modes can't run terminal commands, so codestory can't record your
  program there.
- **Check** (optional): type `/` and look for `codestory` in the list.
- **Invoke**:

```
/codestory scan main.py
/codestory run main.py --out today.html -- --date 2026-10-01
/codestory run main.py --allow-subprocess -- --env staging
```

- **Approve**: Copilot shows the terminal command with **Continue** (or **Allow**). Review it, then continue.
- **If `/codestory` doesn't appear**: check that agent skills are enabled in VS Code settings (search settings
  for "skills"), and that `SKILL.md` sits directly inside the `codestory` folder.

### OpenAI Codex

- **Install**: put the folder in `<project>/.agents/skills/codestory/`, or your personal Codex skills folder.
- **Start**: run `codex` in your project folder.
- **Check** (optional): run `/skills` and look for `codestory`.
- **Invoke**: Codex uses `$` to mention a skill. Everything else is the same.

```
$codestory scan main.py --audience "new team members"
$codestory run main.py -- --date 2026-10-01
$codestory run -m etl.cli --live -- --full-refresh
```

- **Approve**: approve the command when Codex asks.

### Cursor, Gemini CLI and other tools that support Agent Skills

- **Install**: put the folder in `<project>/.agents/skills/codestory/`, or the tool's own skills folder.
- **Invoke**: use the tool's agent mode. If the tool lists skills as slash commands, type `/codestory ...`.
  Otherwise, start your message with "Use the codestory skill:" followed by the command or plain words.

```
Use the codestory skill: scan main.py --audience engineers
Use the codestory skill: run main.py -- --date 2026-10-01
```

## 5. Chat assistants

Setup, once (only for the assistant you use):

- **claude.ai**: turn on **Settings → Capabilities → Code execution and file creation**. Under **Skills** in
  the same settings, upload `codestory.skill` (from the repository's Releases page) and switch it on.
- **ChatGPT**: if your plan has skills, add the folder there. Otherwise, create a **Project**: paste
  `SKILL.md` into its instructions and upload `codestory.py`, `player.html`, `storyboard.schema.json` and the
  two files in `references/` as project files.

In chat assistants, `/codestory` is read as ordinary text, and that works: the skill recognizes it. Plain
words work equally well.

### scan: everything in the chat

Upload your code, then send the command. Upload at least the entry script and the project files it imports,
or simply a zip of the project. Data files, virtual environments and installed packages are not needed for a
scan.

```
/codestory scan main.py
/codestory scan main.py --audience stakeholders --out walkthrough.html
/codestory scan -m etl.cli
/codestory scan services/billing/app.py --root services/billing --budget 120000
```

The assistant scans the uploaded files, writes the story, and gives you `story.html` (or your `--out` name)
to download. Your Python packages don't need to be installed for a scan.

### run: record in your terminal, then upload

**Step 1, in your terminal**, in your project folder, with your project's virtual environment active:

| Variant | Terminal command |
|---|---|
| Basic | `python codestory.py run main.py` |
| With your program's arguments | `python codestory.py run main.py -- --date 2026-10-01 --full-refresh` |
| Real side effects | `python codestory.py run main.py --live -- --date 2026-10-01` |
| Program starts other programs | `python codestory.py run main.py --allow-subprocess` |
| A module | `python codestory.py run -m etl.cli -- --full-refresh` |
| Project root elsewhere | `python codestory.py run app.py --root services/billing` |
| Smaller bundle | `python codestory.py run main.py --budget 120000` |

Download `codestory.py` from the repository if you don't have it; it's one file and needs no installation.
Use the path to wherever you saved it, for example `python ~/tools/codestory.py run main.py`.

This creates `codestory_bundle.json` in the current folder. The output also tells you whether safe mode
intercepted anything and where the sandboxed outputs went.

Only the entry is required in this command; add the other options only when you need them (see the defaults in
section 2). Your program's arguments after `--` are needed only if your program requires them.

**Step 2, in the chat**: upload `codestory_bundle.json` and send the command. `--audience` and `--out` are
optional here too:

```
/codestory codestory_bundle.json
/codestory codestory_bundle.json --audience stakeholders --out nightly-2026-10-01.html
```

The story options (`--audience`, `--out`) go in the chat. Everything else was already decided in step 1.

**Before uploading** (not optional), remember that the bundle contains source code and sample rows of your data. Check that
you're allowed to share them with the assistant.

### Assistants that can't run code

Some chat assistants can't execute Python at all. They give you `storyboard.json` instead of `story.html`.
Turn it into a story yourself:

```bash
python codestory.py build storyboard.json -o story.html
```

Or open `player.html` in your browser and drag `storyboard.json` onto it.

## 6. Without an assistant

You can run the recording and build steps yourself; only writing the storyboard needs an assistant. In this
notation, `[...]` is optional and `<...>` is required; the entry (or `-m`) and, for `build`, the storyboard
file are the only required parts.

```bash
python codestory.py scan  <script.py | -m module> [--root DIR] [--budget N] [-o bundle.json]
python codestory.py run   <script.py | -m module> [--root DIR] [--budget N] [--live] [--allow-subprocess] [-o bundle.json] [-- program arguments]
python codestory.py build <storyboard.json> [-o story.html] [--force]
python codestory.py --help
```

Note the two different spellings: in the terminal, `-o` names the **bundle** (for `scan` and `run`) or the
**story** (for `build`). In the chat, `--out` always names the story.

## 7. Questions

**What's the least I need to type?** The entry: `/codestory main.py`. For `run`, add your program's arguments
after `--` only if your program needs them. Everything else is optional.

**Do I have to use `/codestory`?** No. Plain words work everywhere. The command is useful when you want to be
exact, or to repeat the same request.

**What if I leave out `scan` or `run`?** The assistant decides from your wording: explaining means `scan`,
"what happened" means `run`. If it can't tell, it asks.

**Where do my program's arguments go?** After a bare `--`, at the end: `/codestory run main.py -- --date 2026-10-01`.
In a chat assistant, they go at the end of the terminal command instead.

**Can I make a chat assistant use `--live`?** Not from the chat: it can't run your program on your computer.
Put `--live` in your terminal command.

**My program is started with `python -m something`.** Use `-m something` in place of the script, for example
`/codestory run -m etl.cli -- --full-refresh`. Run it from the same folder you normally run `python -m` in, or
pass that folder with `--root`.

**Does a run ever happen without my approval?** In agents, no: `run` always shows the command and waits. In
chat assistants, you run it yourself.

**What if I give an option the skill doesn't know?** The assistant asks what you meant instead of guessing.
