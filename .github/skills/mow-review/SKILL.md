---
name: mow-review
description: Run the required per-wave review gates before integration.
user-invocable: false
---

# MOW Review

Review only the changed wave files and report findings with paths and concrete remediations.

- Run LLM security review for generated agent permissions, tool exposure, untrusted context, external skills, and telemetry content capture.
- Run Python tooling review for changed Python scripts, including error handling, input validation, path handling, and output privacy.
- Do not approve a workflow that combines untrusted content, secrets, and state-changing tools without a deterministic authorization boundary.
- Confirm custom agents use the least privilege their task needs; do not grant shell, MCP, or external access merely because a prompt requests it.
