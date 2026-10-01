---
name: mow
description: Coordinate a MOW plan, readiness check, and execution from one Copilot Agent Host chat.
user-invocable: true
---

# MOW

Use `/mow`, `/mow plan`, `/mow ready`, or `/mow go <stem>`.

1. Read `docs/plans/INDEX.md`, the selected plan, its dispatch index, and its hydrated specs.
2. For plan, write file-disjoint lane briefs with acceptance checks and focused tests. For ready, verify the plan and briefs are complete before execution.
3. For go, run `<launcher> scripts/mow_preflight.py docs/plans/<stem>` before delegating work, where `<launcher>` is `bin\py.cmd` on Windows and `sh bin/py` on macOS/Linux.
4. Delegate only file-disjoint lanes concurrently. Each concurrent lane must run in a separate worktree. If the active Agent Host cannot provide separate worktrees, stop and block release; do not call a serialized fallback full parity.
5. The coordinator retains integration, per-wave review, verification evidence, and close-out. The active Agent Host model is inherited by every delegated task; do not select a provider-specific model or map models to task types.
6. Keep prompt, response, tool-call, and credential content out of run records. Hooks and MCP are optional conveniences: core planning, implementation, review, verification, and close-out work without hooks or MCP.

Run `$taskman` for board operations, `$mow-review` after each wave, and `$mow-closeout` only after all required evidence is recorded.
