# Security policy

codestory's `run` command executes the program you point it at, and safe mode is meant to stop that program
from changing the outside world. A bug in either can cause real harm, so security reports are taken seriously.

## Reporting a vulnerability

**Please don't open a public issue.** Report it privately through GitHub instead: on this repository, go to
the **Security** tab and click **Report a vulnerability**.

Include what you can of:

- what the problem is and what an attacker or a mistaken program could do with it;
- the steps or a small script that shows it;
- the codestory version (`python codestory.py --version`), operating system and Python version.

You'll get an acknowledgement within 7 days. Once the problem is confirmed, a fix is released as soon as
practical, and you'll be credited in the release notes unless you prefer not to be.

## What counts as a vulnerability

- **Safe mode lets a side effect through** that it claims to intercept (see the README's safe mode table):
  a file write that reaches the real path, a database write that reaches the server, an HTTP POST or email
  that is actually sent.
- **The bundle leaks a secret** that should have been masked: a password, token or key in a value summary,
  constant or URL.
- **A crafted storyboard runs code in the viewer's browser** when a story is opened.
- **`codestory.py` itself** reads, writes or sends anything it shouldn't.

## What doesn't

- **Side effects through libraries safe mode doesn't claim to cover**, such as cloud SDKs, MongoDB, Redis
  and Kafka. These are documented limits; codestory warns when it sees them. Requests to cover more
  libraries are welcome as ordinary issues.
- **Reads.** Safe mode deliberately lets reads through (input files, SELECT queries, GET requests).
- **`--live` and `--allow-subprocess`**, which turn protections off on purpose.

## A reminder for users

Safe mode reduces risk; it is not a sandbox. Run `run` against test data or a development database when you
can, and read the warnings it prints.
