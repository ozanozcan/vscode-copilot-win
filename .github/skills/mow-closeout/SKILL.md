---
name: mow-closeout
description: Preserve MOW verification evidence and enforce final ship checks.
user-invocable: false
---

# MOW Close-out

Before changing a run to shipped, record the exact commands, results, reviewers, artifacts, and unresolved blockers in the lane Verification files.

1. Confirm each lane has focused test evidence and its required review findings are resolved or explicitly blocking.
2. Run the repository ship-check and final verification commands.
3. Keep evidence in `docs/plans/<stem>/dispatch/verification/`; chat-only status is not evidence.
4. Do not claim Windows or macOS Agent Host proof without an actual run on that host. Missing concurrent worktree proof blocks release.
