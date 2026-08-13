# Developer Setup (VS Code)

How to get a working dev environment for the `sixMans` cog: a virtual environment, a local
Red-DiscordBot instance, and the cog loaded from your working tree so edits take effect on reload.

[uv](https://docs.astral.sh/uv/) is the standard tool for this project. It manages the Python
version, the virtual environment, and the locked dependency set in `uv.lock`. Don't use
`pip install -e .` or `python -m venv` — they ignore the lockfile and will drift from CI.

## Prerequisites

- **uv** — install it once:
  - Linux / macOS / WSL: `curl -LsSf https://astral.sh/uv/install.sh | sh`
  - Windows (PowerShell): `powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"`
  - Or via your package manager (`brew install uv`, `pipx install uv`, `winget install astral-sh.uv`).
- **Git**
- **VS Code** with the [Python](https://marketplace.visualstudio.com/items?itemName=ms-python.python)
  extension.
- A **Discord bot application** and token — see Red's
  [Creating a bot account](https://docs.discord.red/en/stable/bot_application_guide.html) guide.

You do *not* need to install Python yourself. `uv` downloads a Python matching the
`requires-python` constraint in `pyproject.toml` if you don't already have one.

> **Use Python 3.11.** Red-DiscordBot 3.5.24 declares `>=3.8.1,<3.12` — it does not officially
> support 3.12. If `uv` picks a newer interpreter for you, force it with
> `uv python pin 3.11 && uv sync`.

## 1. Clone and sync

```bash
git clone <repo-url> bot-SixMans
cd bot-SixMans
uv sync
```

`uv sync` creates `.venv/` in the project root and installs the exact versions from `uv.lock`,
including the `dev` dependency group (pytest and friends). It is idempotent — re-run it any time
`pyproject.toml` or `uv.lock` changes, for example after a `git pull`.

Two ways to use the environment from here:

- **Recommended:** prefix commands with `uv run` (`uv run pytest`, `uv run redbot --list`). This
  syncs the environment first, so you never run against stale dependencies.
- **Or** activate the venv the usual way — `source .venv/bin/activate` (bash/zsh),
  `.venv\Scripts\Activate.ps1` (PowerShell) — and call `pytest` / `redbot` directly.

## 2. Point VS Code at the environment

Press `Ctrl+Shift+P` → **Python: Select Interpreter** → choose the one labelled
`('.venv': venv)` in the project folder. VS Code usually offers this automatically the first time
it notices `.venv/`.

This is what fixes unresolved `redbot.*` imports and makes the Test Explorer work. The repo's
`.vscode/settings.json` already enables pytest discovery.

> `.vscode/` is gitignored, so `settings.json` and `launch.json` are per-developer files you
> create locally.

## 3. Create a Red instance

Each Red *instance* is a named bundle of config and data, stored outside the repo. Create one
once:

```bash
uv run redbot-setup
```

Answer the prompts (name it something like `sixmans-dev`, JSON storage is fine for local work).
Then start it and paste your bot token when asked:

```bash
uv run redbot sixmans-dev --dev --debug
```

## 4. Load the cog from your working tree

In Discord, with your bot in a test server, run these once (`[p]` is your prefix):

```
[p]addpath /absolute/path/to/bot-SixMans
[p]load sixMans
```

`addpath` takes the directory *containing* the `sixMans` package — the repo root, not
`bot-SixMans/sixMans`. On Windows use the full path, e.g. `C:\Users\you\dev\bot-SixMans`.

After editing code, reload without restarting the bot:

```
[p]reload sixMans
```

## Debugging in VS Code

Open the Run and Debug panel (`Ctrl+Shift+D`), click **create a launch.json file**, and use this
configuration:

```json
{
    "version": "0.2.0",
    "configurations": [
        {
            "name": "Python: RedBot",
            "type": "debugpy",
            "request": "launch",
            "module": "redbot",
            "args": [
                "sixmans-dev",
                "--dev",
                "--debug"
            ],
            "console": "integratedTerminal"
        }
    ]
}
```

Replace `sixmans-dev` with your instance name. `type` is `debugpy` — the older `"type": "python"`
is deprecated and no longer works. The configuration inherits the interpreter you selected in
step 2, so there's no need to hardcode a `python` path.

Select **Python: RedBot** in the dropdown and hit the green play button. Breakpoints in
`sixMans/` will hit on the next command that reaches them.

## Tests, linting, and formatting

```bash
uv run pytest                 # full suite
uv run pytest tests/test_vote.py -k timeout   # one file / filter
```

Linting and formatting use [ruff](https://docs.astral.sh/ruff/), configured in `pyproject.toml`.
It isn't a project dependency — run it with `uvx`, which fetches and caches tools on demand:

```bash
uvx ruff check .
uvx ruff format .
```

Install the pre-commit hooks (ruff check/format, trailing whitespace, codespell) so this happens
on every commit:

```bash
uvx pre-commit install
uvx pre-commit run --all-files    # optional: check the whole tree now
```

## Managing dependencies

Edit dependencies through uv so `pyproject.toml` and `uv.lock` stay in sync — commit both.

```bash
uv add "some-package>=1.2"        # runtime dependency
uv add --dev pytest-cov           # dev-only dependency
uv remove some-package
uv lock --upgrade-package red-discordbot   # bump one locked package
```

## Useful commands

| Command | What it does |
| --- | --- |
| `uv sync` | Bring `.venv` in line with `uv.lock` |
| `uv run redbot --list` | List all Red instances on this machine |
| `uv run redbot <instance>` | Launch an instance |
| `uv run redbot-setup delete <instance>` | Delete an instance and its data |
| `uv run python -c "import redbot; print(redbot.__version__)"` | Confirm which Red you're on |

## Troubleshooting

- **`redbot` imports unresolved in VS Code** — the interpreter isn't set. Redo step 2, then
  reload the window (`Ctrl+Shift+P` → **Developer: Reload Window**).
- **`uv sync` fails on the Python version** — run `uv python install 3.11` and retry.
- **`[p]load sixMans` says the cog isn't found** — `addpath` was given the cog folder instead of
  its parent. Check with `[p]paths`, remove the wrong one with `[p]removepath <index>`, and add
  the repo root.
- **Changes don't appear in Discord** — you edited a module that was already imported; `[p]reload
  sixMans` handles most cases, but restart the bot if you changed something at import time.
