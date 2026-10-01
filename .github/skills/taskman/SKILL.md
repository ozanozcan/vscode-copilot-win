---
name: taskman
description: Operate the local MOW board with explicit Python commands and no MCP dependency.
user-invocable: true
---

# Taskman

Use `<launcher> -m taskman` to initialize and inspect the local board, where `<launcher>` is `bin\py.cmd` on Windows and `sh bin/py` on macOS/Linux. Read the plan and lane brief before changing a task.

- Record decisions and requirements as durable board data, not chat-only assertions.
- Keep task ownership file-disjoint before a coordinator delegates concurrent lanes.
- Do not persist monthly allowances, billed totals, prompt content, response content, tool inputs, or tool results in task records.
- The full workflow must work without hooks or MCP. Treat either as an optional convenience, never a safety gate.
