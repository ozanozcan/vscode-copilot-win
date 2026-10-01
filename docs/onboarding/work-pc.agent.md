# Windows work-PC agent runbook — prove the public clone

**What this is:** the execution checklist for an agent running inside a fresh
`public-logic-harness` clone on a managed Windows PC.

**What this is not:** permission to change enterprise policy, install global tooling,
access employer repositories, publish evidence, or push changes.

**Outcome:** either produce a factual PASS report for the supported Windows workflow,
or STOP at the first blocker and report the exact command, output, and missing contract.

## Contents

- [Operating boundaries](#operating-boundaries) — actions that always require restraint
- [Confirm the clone](#confirm-the-clone) — establish the repository and tool baseline
- [Confirm Agent Host discovery](#confirm-agent-host-discovery) — prove VS Code loaded the workspace assets
- [Run the hook-free baseline](#run-the-hook-free-baseline) — verify the core with hooks and MCP disabled
- [Initialize local state](#initialize-local-state) — create only repository-local board data
- [Prove the MOW workflow](#prove-the-mow-workflow) — test one coordinator and concurrent worktrees
- [Check optional hooks](#check-optional-hooks) — install only with operator approval
- [Check telemetry](#check-telemetry) — inspect content-free OTel only when policy permits
- [Write the result](#write-the-result) — return evidence without leaking work-PC data
- [Troubleshooting](#troubleshooting) — stop conditions and permitted recovery
- [Sources](#sources) — repository contracts this runbook executes

---

## Operating boundaries

Follow these rules for the entire run:

- Work only inside this public clone and temporary worktrees created from it.
- Do not open, scan, modify, or cite employer source repositories or files.
- Do not change VS Code organization policy, Windows policy, GitHub visibility, remotes,
  credential storage, firewall settings, or telemetry policy.
- Do not install Copilot CLI, Bash, a global taskman, or a global Python package to fill
  a repository gap. The supported path is VS Code **Copilot Agent Host** plus bundled files.
- Do not enable hooks or MCP to rescue a failed baseline. The core workflow must pass with
  **hooks disabled** and **MCP disabled**.
- Do not commit, push, publish, or attach screenshots unless the operator explicitly asks.
- Never copy prompts, responses, tool inputs, tool outputs, credentials, organization names,
  monthly allowances, or billing data into the repository or the final report.

**STOP:** If any requested action crosses these boundaries, report the blocked step and wait.

## Confirm the clone

Run from PowerShell in the repository root:

```powershell
git rev-parse --show-toplevel
git status --short
git remote -v
git --version
py -3 --version
code --version
```

Record versions and whether `git status --short` was clean. Do not print environment
variables, credential-helper contents, tokens, or full VS Code diagnostic bundles.

Confirm these public assets exist:

```powershell
$required = @(
  ".github\copilot-instructions.md",
  ".github\agents\mow-implementer.agent.md",
  ".github\agents\mow-reviewer.agent.md",
  ".github\skills\mow\SKILL.md",
  ".github\skills\taskman\SKILL.md",
  ".github\skills\mow-review\SKILL.md",
  ".github\skills\mow-closeout\SKILL.md",
  ".github\skills\impeccable\SKILL.md",
  "bin\py.cmd",
  "bin\tests\test_windows_wrapup.py"
)
$missing = $required | Where-Object { -not (Test-Path $_) }
if ($missing) { $missing; throw "STOP: public clone is incomplete" }
```

**STOP:** Do not recreate a missing file from memory. Report the missing path as a release blocker.

## Confirm Agent Host discovery

1. Open this clone as the VS Code workspace and trust only this public repository.
2. In Chat, select **Copilot Agent Host** as the session target. Do not substitute Local,
   Copilot CLI, Claude, or a cloud agent.
3. Open **Configure Chat** and inspect the selected target's customizations.
4. Confirm `.github/copilot-instructions.md`, both MOW agents, and the bundled skills are listed.
5. Confirm agent definitions inherit the active host model and do not pin a provider model.

Record discovered names and the VS Code/Copilot extension versions. Do not claim discovery
from file presence alone.

**STOP:** If the managed build has no Copilot Agent Host target or does not discover the
workspace assets, capture the visible error text and report a platform blocker.

## Run the hook-free baseline

Do not install the optional tracker hook yet. Do not approve or start `.mcp.json` servers.
Run every available repository-local check through the Windows launcher:

```powershell
bin\py.cmd bin\tests\test_repo_shape.py
bin\py.cmd bin\tests\test_public_customizations.py
bin\py.cmd bin\tests\test_windows_wrapup.py
```

If a named check is absent, STOP and report the missing release asset. Do not replace it
with a private ai-wow test, a global command, or a macOS result.

The baseline passes only when all commands exit `0` while hooks and MCP remain unavailable
or unused. Optional surfaces cannot supply a release guarantee.

## Initialize local state

Use only the repository's documented bootstrap and `bin\py.cmd`. Never copy ai-wow board
state or use a global taskman installation.

```powershell
if (-not (Test-Path "bin\bootstrap-taskman.py")) {
  throw "STOP: bundled taskman bootstrap is missing"
}
bin\py.cmd bin\bootstrap-taskman.py
bin\py.cmd -m taskman --help
```

Follow the bootstrap's printed next command to initialize an empty local board. Verify the
new board contains no imported tasks, decisions, sessions, personal paths, or private history.
Do not commit generated local state unless the public repository explicitly documents it as
tracked fixture data and the operator approves.

## Prove the MOW workflow

Use one Copilot Agent Host coordinator chat:

1. Invoke `/mow plan` for a disposable two-lane change whose files are disjoint.
2. Invoke `/mow ready` and require preflight to pass before delegation.
3. Invoke `/mow go <stem>`.
4. Require both lanes to run concurrently in separate worktrees.
5. Confirm each lane uses its declared custom agent, runs a focused check, and does not commit.
6. Confirm the coordinator integrates, runs the review gate, records verification, and closes out.
7. Confirm the active Agent Host model is inherited rather than hard-coded by the harness.

Use disposable files created specifically for this proof. Do not point the workflow at employer
code or personal repositories.

**STOP:** Serial execution is not accepted as parity. If Agent Host cannot delegate concurrent,
file-disjoint lanes in separate worktrees, report task #431 as blocked and do not claim Windows
support complete.

## Check optional hooks

Only after the hook-free baseline passes, ask the operator whether user-level hook installation
is allowed. If approved, review both installer and handler, then run:

```powershell
py -3 .github\hooks\install-stamp-tracker.py
```

Restart the Agent Host session. Under **Configure Chat → Hooks**, confirm the user-level
`postToolUse` hook is discovered once. Edit a disposable MOW `dispatch\tracker.json` and verify
its `updated` timestamp changes without warnings.

If policy blocks hooks, record `optional hooks: blocked by policy` and continue. Do not change
policy or treat the denial as a core-workflow failure.

## Check telemetry

Proceed only when the operator confirms that local Copilot OTel export is permitted and content
capture is disabled. Do not change organization policy. Use a work-PC-local output path outside
the repository, then run the bundled parser against only the disposable MOW tracker.

Verify that the report contains conversation ID, agent, resolved model, and token counts, while
prompt, response, tool arguments, tool results, credentials, and monthly allowances are absent.
Calculated AI credits must be labeled as estimates; unknown rates remain `unknown`.

If export or billing reconciliation is unavailable, report `unknown` or `policy blocked`. Never
infer missing usage from timestamps, prompt content, or token shape.

## Write the result

Return this exact structure in chat. Do not write it into the repository unless asked.

```markdown
# Windows public-clone proof

- Verdict: PASS | BLOCKED
- Repository status before test: clean | dirty
- Windows version: <version>
- VS Code version: <version>
- Copilot extension version: <version>
- Session target: Copilot Agent Host
- Workspace assets discovered: PASS | BLOCKED
- Hook-free/MCP-free checks: PASS | BLOCKED
- Fresh board bootstrap: PASS | BLOCKED
- Concurrent isolated MOW lanes: PASS | BLOCKED
- Optional hooks: PASS | blocked by policy | not tested
- Content-free OTel: PASS | blocked by policy | not tested
- Model inheritance: PASS | BLOCKED
- Unexpected repository changes: <paths only, or none>
- First blocker: <exact command and concise error, or none>
```

Attach command exit codes and concise output needed to prove each line. Redact usernames and
machine paths. Do not include screenshots unless the operator explicitly requests reviewed images.

## Troubleshooting

| Symptom | Permitted response |
|---|---|
| `py` is unavailable | STOP; report missing Python 3. Do not install software without approval. |
| Agent Host target is absent | STOP; report VS Code and extension versions plus visible error text. |
| Workspace assets are not discovered | Reopen the repository root, confirm Workspace Trust, restart VS Code, retry once, then STOP. |
| Hooks are denied | Record the optional surface as policy-blocked; keep the hook-free baseline authoritative. |
| MCP is denied | Keep MCP disabled and continue the core workflow. |
| A bundled test is missing | STOP; report an incomplete public export. |
| Concurrent worktrees are unavailable | STOP; Windows parity is blocked. Do not serialize and call it equivalent. |
| A command requests credentials | Let the operator type them directly; never ask for or echo secrets. |
| The repository becomes dirty unexpectedly | Record changed paths, stop mutation, and ask the operator before cleanup. |

## Sources

- `.github/copilot-instructions.md` — public workspace rules.
- `.github/skills/mow/SKILL.md` and `.github/skills/taskman/SKILL.md` — coordinator and board contracts.
- `.github/hooks/README.md` — optional hook and hook-disabled behavior.
- `.github/workflows/windows-wrapup.yml` — real Windows acceptance job.
- `bin/tests/test_windows_wrapup.py` — repository-local Windows wrap-up proof.