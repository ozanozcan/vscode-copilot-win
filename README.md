# Public Logic Harness - VS Code Copilot work loop

**What it is:** a clean, self-contained MOW workspace for GitHub Copilot Agent Host,
with a bundled taskman runtime and repository-local Python launchers.

**What it is not:** a copy of ai-wow history, a Copilot CLI package, or proof that a
managed Windows environment permits every optional hook or telemetry surface.

**Why it exists:** a fresh Windows or macOS clone should expose the same instructions,
agents, skills, board workflow, and wrap-up path without global harness files.

## Contents

- [Start on Windows](#start-on-windows) - bootstrap and verify a fresh clone
- [Start on macOS or Linux](#start-on-macos-or-linux) - use the POSIX launcher
- [What ships](#what-ships) - the reviewed public boundary
- [What remains to prove](#what-remains-to-prove) - managed-environment release gates
- [Sources](#sources) - executable contracts and runbooks

---

## Start on Windows

Open the clone in VS Code, select **Copilot Agent Host**, and keep hooks and MCP disabled
for the baseline. From PowerShell:

```powershell
bin\py.cmd bin\tests\test_windows_wrapup.py
bin\py.cmd bin\bootstrap-taskman.py
bin\py.cmd -m taskman --help
```

Follow [the human work-PC runbook](docs/onboarding/work-pc.human.md) for the clean-clone
sequence. The agent-facing checklist is at
[docs/onboarding/work-pc.agent.md](docs/onboarding/work-pc.agent.md).

## Start on macOS or Linux

Use the same repository-local entry points through the POSIX launcher:

```sh
sh bin/py bin/tests/test_windows_wrapup.py
sh bin/py bin/bootstrap-taskman.py
sh bin/py -m taskman --help
```

The file name `test_windows_wrapup.py` reflects the release target; the test also runs
on POSIX to catch cross-platform drift before the Windows job executes.

## What ships

The export contains curated Copilot instructions, implementation and review agents,
MOW/taskman/wrap-up skills, a pinned Impeccable skill, optional Agent Host hooks, the
taskman source required for a fresh board, and content-free usage tooling. It excludes
Git history, existing board state, local configuration, virtual environments, caches,
transcripts, credentials, and private screenshots.

Hooks and MCP are conveniences. Core board initialization and workflow checks must work
without either one.

## What remains to prove

The checked-in `windows-latest` job exercises the Windows launcher, `SessionStart`
marker, and wrap-up digest. Release still requires a managed work-PC run that confirms
Agent Host discovers the workspace assets, concurrent lanes use separate worktrees,
enterprise policy is respected, and content-free telemetry behaves as documented.

Until that evidence exists, describe the package as Windows-targeted, not
Windows-validated.

## Sources

- [Windows human runbook](docs/onboarding/work-pc.human.md)
- [Windows agent runbook](docs/onboarding/work-pc.agent.md)
- [.github/workflows/windows-wrapup.yml](.github/workflows/windows-wrapup.yml)
- [bin/tests/test_windows_wrapup.py](bin/tests/test_windows_wrapup.py)
- [.github/hooks/README.md](.github/hooks/README.md)