# Contributing to codestory

Thanks for your interest. Bug reports and ideas are the most useful contributions, because they show where
codestory meets real code it wasn't tested on.

## Reporting a problem

Open an issue and include:

- **What you ran**: the command (`scan` or `run`) or what you asked your assistant, and which assistant
  (Claude Code, GitHub Copilot, ChatGPT, ...).
- **What happened** and what you expected instead.
- **Your environment**: operating system, Python version (`python --version`), and the main libraries your
  program uses (pandas, SQLAlchemy, requests, ...).
- **The smallest example that shows it**, if you can make one. A 20-line script that reproduces the problem
  is worth more than a long description.

Typical reports:

- **Safe mode missed a side effect**: name the library and the call (for example
  `boto3 ... upload_file`). Include the "REAL side effect" lines from the `run` output.
- **The story came out wrong or weak**: attach `storyboard.json` and describe what's wrong (too many scenes,
  vague narration, a wrong number, a highlight on the wrong line). This tells us which part of `SKILL.md`
  to improve.
- **The player misbehaves**: the browser and version, and a screenshot.

**Never attach a bundle from private code.** `codestory_bundle.json` contains source code and sample rows of
your data. Make a small synthetic example instead.

Security problems are different: please report them privately, as described in [SECURITY.md](SECURITY.md).

## Suggesting a change

For anything beyond a small fix, open an issue to discuss it before writing code, so we can agree on the
approach first.

If you send a pull request:

- `codestory.py` must stay **standard library only** and work on **Python 3.8+**.
- `player.html` must stay **a single file with no third-party code**, so stories work offline.
- Keep the storyboard format backwards compatible, or bump `codestory.storyboard/1` and explain why.
- Rebuild the examples and check them in a browser:
  ```bash
  python codestory.py build examples/weather-pipeline/storyboard.json -o examples/weather-pipeline/story.html
  python codestory.py build examples/log-check-scan/storyboard.json -o examples/log-check-scan/story.html
  ```
- If you change how `run` works, re-run the weather example in safe mode and confirm the real database
  file is unchanged:
  ```bash
  cd examples/weather-pipeline/project
  python ../../../codestory.py run main.py -o /tmp/bundle.json -- --date 2026-10-01 --full-refresh
  ```
- Add a line to [CHANGELOG.md](CHANGELOG.md) under "Unreleased".

By contributing, you agree that your contributions are licensed under the [MIT License](LICENSE).
