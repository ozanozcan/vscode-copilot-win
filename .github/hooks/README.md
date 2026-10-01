# Optional Agent Host Hook

`release-safety.json` registers a workspace `SessionStart` hook. It writes
`.session-markers/<session-id>.json` with the worktree's starting commit, using
`python3` on macOS/Linux and `py -3` through `session-start.cmd` on Windows. The
public `/wrap-up` skill uses that marker when hooks are enabled and can create one
through taskman when enterprise policy disables hooks.

After reviewing the source, install the optional MOW tracker hook under your Copilot
home with `sh bin/py .github/hooks/install-stamp-tracker.py` on macOS/Linux or
`bin\py .github\hooks\install-stamp-tracker.py` on Windows. The installed copy keeps
`dispatch/tracker.json` timestamps current after supported VS Code Copilot or Local edit
tools. Restart the agent session, then confirm discovery under **Configure Chat → Hooks**
for the selected target.

`release-safety.json` is an optional VS Code Copilot Agent Host hook surface.
It starts as a capability probe and does not inspect or decide on tool payloads:
the managed Agent Host version and policy must prove the Copilot SDK event and
response contract before anyone enables `COPILOT_AGENT_HOST_HOOKS=1`.

The hook is never a release boundary. Enterprise policy can disable workspace
hooks, and the direct guard is required in either state.

With hooks disabled, run the direct Git guard before release:

```text
<launcher> .github/hooks/release-guard.py --hooks-disabled
```

The guard runs `git diff --check HEAD` and the public harness checks, then
returns a visible blocker on a Git failure, missing check, or non-checkout.
Run the workspace's documented MOW preflight and close-out checks as well; they
remain required whether this hook is enabled or disabled.