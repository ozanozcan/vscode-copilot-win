#!/usr/bin/env python3
"""Contract checks for exported VS Code Copilot customizations."""

import json
import re
import sys
from pathlib import Path


REPO = Path(__file__).resolve().parents[2]
AGENTS = REPO / ".github" / "agents"
FAILURES = []


def check(label, got, want=True):
    if got == want:
        print(f"  PASS  {label}")
    else:
        print(f"  FAIL  {label} - got {got!r}, want {want!r}")
        FAILURES.append(label)


def frontmatter(path):
    text = path.read_text(encoding="utf-8")
    match = re.match(r"---\n(.*?)\n---\n", text, re.DOTALL)
    if match is None:
        return {}
    values = {}
    for line in match.group(1).splitlines():
        key, separator, value = line.partition(":")
        if separator:
            values[key.strip()] = value.strip()
    return values


def main():
    print("public Copilot workspace customizations")

    instructions = REPO / ".github" / "copilot-instructions.md"
    expected = [instructions, REPO / ".mcp.json", REPO / ".vscode" / "extensions.json"]
    check("required workspace assets exist", [path.is_file() for path in expected],
          [True] * len(expected))

    agents = sorted(AGENTS.glob("*.agent.md")) if AGENTS.is_dir() else []
    check("workspace exposes implementation and review agents", len(agents) >= 2)
    agent_data = []
    for path in agents:
        header = frontmatter(path)
        try:
            tools = json.loads(header.get("tools", ""))
        except json.JSONDecodeError:
            tools = None
        check(f"{path.name}: required frontmatter",
              {"name", "description", "tools"} <= set(header))
        check(f"{path.name}: tools are a JSON list", isinstance(tools, list))
        agent_data.append((path.name, header, tools))

    implementation = [tools for _, header, tools in agent_data
                      if "implement" in header.get("name", "").lower()]
    review = [tools for _, header, tools in agent_data
              if "review" in header.get("name", "").lower()]
    check("implementation agent can edit and execute focused checks",
          any(isinstance(tools, list) and {"edit", "execute"} <= set(tools)
              for tools in implementation))
    check("review agent is read-only",
          any(isinstance(tools, list) and {"read", "search"} <= set(tools)
              and not ({"edit", "execute"} & set(tools)) for tools in review))
    check("agents leave model selection to the host",
          [name for name, header, _ in agent_data if "model" in header], [])

    try:
        mcp = json.loads((REPO / ".mcp.json").read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        mcp = None
    check("MCP is optional by default",
          mcp.get("mcpServers") if isinstance(mcp, dict) else None, {})

    try:
        extensions = json.loads((REPO / ".vscode" / "extensions.json").read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        extensions = None
    check("Copilot Chat is recommended", isinstance(extensions, dict)
          and "github.copilot-chat" in extensions.get("recommendations", []))

    instruction_text = instructions.read_text(encoding="utf-8") if instructions.is_file() else ""
    check("instructions name the public test commands",
          all(command in instruction_text for command in (
              "python3 bin/tests/test_repo_shape.py",
              "python3 bin/tests/test_public_customizations.py",
          )))
    forbidden = ["claude", "~/.claude", "copilot cli"]
    check("instructions exclude unsupported private mechanisms",
          [term for term in forbidden if term in instruction_text.lower()], [])

    print()
    if FAILURES:
        print(f"{len(FAILURES)} failure(s): " + ", ".join(FAILURES))
        return 1
    print("0 failure(s)")
    return 0


if __name__ == "__main__":
    sys.exit(main())