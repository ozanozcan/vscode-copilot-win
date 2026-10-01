# Windows work-PC setup - public clone

**What it is:** the operator runbook for checking a fresh `public-logic-harness` clone
in managed Windows VS Code.

**What it is not:** permission to change company policy, inspect employer code, install
global tooling, publish the repository, or treat a macOS result as Windows evidence.

**Why it exists:** the release claim depends on what the managed Copilot Agent Host can
actually discover and run, not only on files passing tests elsewhere.

## Contents

- [Before you start](#before-you-start) - tools and safety boundaries
- [Check the clone](#check-the-clone) - repository-local automated baseline
- [Open Agent Host](#open-agent-host) - workspace discovery in VS Code
- [Initialize the board](#initialize-the-board) - bundled taskman only
- [Prove the work loop](#prove-the-work-loop) - concurrent isolated MOW lanes
- [Optional surfaces](#optional-surfaces) - hooks, MCP, and telemetry
- [Record the verdict](#record-the-verdict) - evidence and stop conditions
- [Sources](#sources) - executable checks

---

## Before you start

You need Git, Python 3 through the Windows `py` launcher, VS Code, and GitHub Copilot
Chat with the **Copilot Agent Host** target. Use a fresh clone that contains no employer
source or private ai-wow state.

Keep hooks and MCP disabled for the baseline. Do not install Copilot CLI, Bash, a global
taskman package, or credentials on an agent's request. Stop when a command would change
enterprise policy or leave the public clone without explicit approval.

## Check the clone

From PowerShell in the repository root:

```powershell
git status --short
py -3 --version
code --version
bin\py.cmd bin\tests\test_windows_wrapup.py
```

The last command must create a temporary Git repository, run the Windows launcher and
session marker, and render a session-attributed digest. A missing file or nonzero exit is
a release blocker; do not replace it with a private test.

## Open Agent Host

Open the repository root in VS Code and select Copilot Agent Host. Under **Configure
Chat**, confirm the workspace instructions, MOW agents, and bundled skills are listed.
File presence is not discovery evidence.

If the target is absent or a customization is missing, restart VS Code once and retry.
Then stop and record the VS Code and Copilot extension versions plus the visible error.

## Initialize the board

Use the repository-local bootstrap and launcher:

```powershell
bin\py.cmd bin\bootstrap-taskman.py
bin\py.cmd -m taskman --help
```

Follow the bootstrap's printed initialization command. The resulting board must be empty
of imported tasks, decisions, personal paths, and event history. Do not commit local board
state unless the public repository explicitly documents that action and you approve it.

## Prove the work loop

From one Agent Host coordinator chat, run `/mow plan`, `/mow ready`, and `/mow go` for a
disposable two-lane change. The lanes must edit disjoint files concurrently in separate
worktrees, run focused checks, and return to the coordinator for review and close-out.

Serial execution is not equivalent. If the managed host cannot create concurrent isolated
lanes, Windows parity remains blocked.

## Optional surfaces

Only after the hook-free and MCP-free baseline passes should you consider optional hooks.
Review the files first, obtain policy approval, and follow
[the hook guide](../../.github/hooks/README.md). A denied hook or MCP request is recorded
as policy-blocked; it does not justify changing policy.

Check telemetry only when the operator confirms local content-free export is permitted.
Keep prompts, responses, tool arguments, credentials, organization names, allowances, and
billing data out of the repository and report.

## Record the verdict

Record command exit codes, VS Code/Copilot versions, discovered workspace assets, fresh
board status, concurrent worktree evidence, and the first blocker. Redact usernames and
machine paths. Do not commit, push, publish, or attach screenshots without explicit
approval.

A passing local test is not the final verdict. Mark Windows validated only after the
managed Agent Host discovery and concurrent-lane checks pass on the work PC.

## Sources

- [Repository README](../../README.md)
- [Agent execution checklist](work-pc.agent.md)
- [Windows acceptance test](../../bin/tests/test_windows_wrapup.py)
- [Windows CI job](../../.github/workflows/windows-wrapup.yml)