#!/usr/bin/env python3
"""Generate the factual half of a mow stem's action report — the run record.

The action report has two halves. The judgment half (why we did it, vision vs
shipped, decisions, what is still open) is the orchestrator's to write. The factual
half — what the tracker recorded, when things happened, which commits landed, which
files the stem left, which board rows it touched — has sources that can print it,
so it is printed from them, never typed (L58: a hand-written count or sha is wrong
at a rate no reader can detect).

Sources, and nothing else:
  - Tracker   `dispatch/tracker.json`, as stored. No active-time arithmetic: a
              duration that cannot be read straight off the file is omitted (TRACKER.md).
  - Timeline  `git log --follow` of `plan.md`, merged with the tracker's run/wave
              timestamps, all shown in UTC.
  - Commits   every backticked sha in the report's own text (outside this block),
              resolved in the stem's repo and every `~/Desktop/<repo>/` named in the
              dispatch INDEX `Files owned` cells. Unresolvable ones are listed, not dropped.
  - Files     what exists under the stem folder, dotfiles skipped.
  - Board     `#N` in the INDEX lanes' PBI / Feature cells, tracker todos and
              findings, and the report's Open / deferred section; `--board` adds status
              from the stem repo's `board/`.

Usage:
  python -m taskman.mow.run_report docs/plans/<stem> [--write] [--board]

Without --write the block is printed. With --write it is inserted into (or replaces
the existing block in) `action-report.md`; text outside the markers is untouched.
"""

from __future__ import annotations

import datetime
import json
import os
import re
import subprocess
import sys
from pathlib import Path

from taskman.mow.preflight import parse_files_owned, paths_overlap

BEGIN = "<!-- run-report:begin -->"
END = "<!-- run-report:end -->"
HEADING = "## Run record"

# A sha is a 7–40 hex word inside a backtick span. The span may carry a command
# (`git show --shortstat 5aaf01e`) — part1-reveal cites every commit that way — so
# the word is searched inside the span, not required to be the whole span. At least
# one digit, so a backticked English word made of a–f letters is not mistaken for one.
# An all-digit word (`20260927`) is usually a date, but ~4% of real 7-char short shas
# are all digits too, so those are kept only when a repo resolves them (_ALL_DIGITS).
_SPAN = re.compile(r"`([^`\n]+)`")
_SHA = re.compile(r"(?<![0-9A-Za-z])(?=[0-9a-f]*\d)[0-9a-f]{7,40}(?![0-9A-Za-z])")
_ALL_DIGITS = re.compile(r"\d+")
_HEADING2 = re.compile(r"##\s+(.*)$")
_OWNED_REPO = re.compile(r"~/Desktop/([^/`\s]+)/")
_TASK_ID = re.compile(r"(?<![\w&])#(\d+)\b")
_OPEN = re.compile(r"(?i)open\s*(/|and|,)?\s*deferred|deferred|open follow-?ups?")


def _git(repo: Path, *args: str) -> tuple[int, str]:
    proc = subprocess.run(
        ["git", "-C", str(repo), *args], capture_output=True, text=True, encoding="utf-8"
    )
    return proc.returncode, proc.stdout.strip()


def _cell(text: str) -> str:
    return text.replace("|", "\\|").replace("\n", " ")


def _utc(stamp: str) -> str:
    try:
        return (
            datetime.datetime.fromisoformat(str(stamp).replace("Z", "+00:00"))
            .astimezone(datetime.timezone.utc)
            .strftime("%Y-%m-%dT%H:%M:%SZ")
        )
    except ValueError:
        return f"(unparseable) {stamp}"


def _tracker(stem: Path) -> dict | None:
    """The tracker, None when absent, or {"_error": …} when it cannot be read as an object."""
    path = stem / "dispatch" / "tracker.json"
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except ValueError:
        return {"_error": "tracker.json is not valid JSON"}
    return data if isinstance(data, dict) else {"_error": "tracker.json is not a JSON object"}


def _marker_lines(text: str) -> tuple[list[tuple[int, int]], list[tuple[int, int]]]:
    """(start, end-before-newline) of every whole-line BEGIN / END marker outside ``` fences.

    Whole-line only: a marker quoted in a sentence is prose, and matching from it to
    the real block's END is exactly how a greedy search deleted a report's sections.
    """
    begins: list[tuple[int, int]] = []
    ends: list[tuple[int, int]] = []
    fenced = False
    pos = 0
    for line in text.splitlines(keepends=True):
        bare = line.rstrip("\r\n")
        if bare.lstrip().startswith("```"):
            fenced = not fenced
        elif not fenced and bare == BEGIN:
            begins.append((pos, pos + len(bare)))
        elif not fenced and bare == END:
            ends.append((pos, pos + len(bare)))
        pos += len(line)
    return begins, ends


def _unclosed_fence(text: str) -> bool:
    """An odd number of ``` lines: everything after the last one reads as fenced."""
    return sum(line.lstrip().startswith("```") for line in text.splitlines()) % 2 == 1


def block_span(text: str) -> tuple[int, int] | None:
    """(start, end) of the one generated block, or None unless exactly one well-ordered pair exists."""
    begins, ends = _marker_lines(text)
    if len(begins) == 1 and len(ends) == 1 and begins[0][0] < ends[0][0]:
        return begins[0][0], ends[0][1]
    return None


def _report_text(stem: Path) -> str:
    path = stem / "action-report.md"
    if not path.is_file():
        return ""
    text = path.read_text(encoding="utf-8")
    span = block_span(text)
    return text[: span[0]] + text[span[1] :] if span else text


def _index_rows(stem: Path) -> list[dict[str, str]]:
    """The dispatch INDEX lanes table as header → cell dicts."""
    path = stem / "dispatch" / "INDEX.md"
    if not path.is_file():
        return []
    rows: list[dict[str, str]] = []
    header: list[str] | None = None
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.startswith("|"):
            header = None
            continue
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if header is None:
            header = cells
        elif not all(set(c) <= set("-: ") for c in cells):
            rows.append(dict(zip(header, cells)))
    return [r for r in rows if "Lane" in r]


# --- sections -----------------------------------------------------------------


def _tracker_section(stem: Path) -> list[str]:
    data = _tracker(stem)
    out = ["### Tracker", ""]
    if data is None:
        return out + ["*No `dispatch/tracker.json` — nothing recorded.*", ""]
    if "_error" in data:
        return out + [f"*{data['_error']} — nothing read from it.*", ""]
    out.append(
        f"Run status **{data.get('run_status', '?')}** · started {data.get('started', '?')} "
        f"· updated {data.get('updated', '?')} (UTC, as stored in `dispatch/tracker.json`)"
    )
    if "tokens" in data:
        out.append(f"Tokens recorded on the tracker: {data['tokens']}")
    out.append("")
    for wave in data.get("waves", []):
        gate = wave.get("gate") or {}
        line = f"**Wave {wave.get('wave')}** — {wave.get('status', '?')} · {wave.get('parallelism', '?')}"
        if gate:
            line += f" · gate {gate.get('status', '?')}"
            if gate.get("detail"):
                line += f": {gate['detail']}"
        out += [line, ""]
        out += ["| Lane | Brief | Todos | Agents (calling order) | Status | Findings |", "|---|---|---|---|---|---|"]
        for lane in wave.get("lanes", []):
            todos = ", ".join(str(t.get("id", "?")) for t in lane.get("todos", [])) or "-"
            agents = " → ".join(
                f"{a.get('name', '?')} ({a.get('status', '?')})" for a in lane.get("agents", [])
            ) or "-"
            findings = ", ".join(
                f"{f.get('task', '?')} ({f.get('severity', '?')})" for f in lane.get("findings", [])
            ) or "-"
            out.append(
                f"| {_cell(str(lane.get('lane', '?')))} | {_cell(str(lane.get('brief', '-')))} | {_cell(todos)} "
                f"| {_cell(agents)} | {lane.get('status', '?')} | {_cell(findings)} |"
            )
        out.append("")
    return out


def _timeline_section(stem: Path, repo: Path | None) -> list[str]:
    events: list[tuple[str, str, str]] = []  # (utc stamp, sha or "", what)
    if repo is not None and (stem / "plan.md").is_file():
        code, log = _git(repo, "log", "--follow", "--format=%cI%x09%h%x09%s", "--", str(stem / "plan.md"))
        if code == 0:
            for line in log.splitlines():
                stamp, sha, subject = line.split("\t", 2)
                events.append((_utc(stamp), f"`{sha}`", f"plan.md: {subject}"))
    data = _tracker(stem) or {}
    if data.get("started"):
        events.append((_utc(data["started"]), "", "run started"))
    for wave in data.get("waves", []):
        for key in ("started", "ended"):
            if wave.get(key):
                events.append((_utc(wave[key]), "", f"wave {wave.get('wave')} {key}"))
    if data.get("updated"):
        events.append((_utc(data["updated"]), "", f"run updated (status: {data.get('run_status', '?')})"))
    out = [
        "### Timeline",
        "",
        "Times are UTC — plan.md commits at committer time from `git log --follow`, run and wave "
        "events from the tracker.",
        "",
    ]
    if not events:
        return out + ["*Nothing to show — no plan.md history and no tracker timestamps.*", ""]
    out += ["| When (UTC) | Commit | Event |", "|---|---|---|"]
    for stamp, sha, what in sorted(events, key=lambda e: e[0]):
        out.append(f"| {stamp} | {sha or '-'} | {_cell(what)} |")
    return out + [""]


def _repos(stem: Path, repo: Path | None) -> list[Path]:
    found: list[Path] = [repo] if repo is not None else []
    for row in _index_rows(stem):
        for name in _OWNED_REPO.findall(row.get("Files owned", "")):
            if name in {".", ".."}:
                continue
            candidate = Path(os.path.expanduser(f"~/Desktop/{name}"))
            if candidate.is_dir() and candidate.resolve() not in {r.resolve() for r in found}:
                if _git(candidate, "rev-parse", "--git-dir")[0] == 0:
                    found.append(candidate)
    return found


def _repo_key(path: Path) -> Path | None:
    """The resolved common git dir: a linked worktree and its main checkout are one repo."""
    code, common = _git(path, "rev-parse", "--git-common-dir")
    return (Path(path) / common).resolve() if code == 0 and common else None


def _owned_paths(stem: Path, repo: Path | None) -> dict[Path, list[str]]:
    """Repo key (see _repo_key) → repo-relative paths the stem's lanes own there.

    A plain `Files owned` path belongs to the stem's repo; `~/Desktop/<repo>/rest` to
    that repo as `rest`. The stem's own folder counts as owned: its plan, briefs and
    report commits are this run's too.
    """
    owned: dict[Path, list[str]] = {}
    stem_key = _repo_key(repo) if repo is not None else None
    if repo is not None and stem_key is not None:
        owned.setdefault(stem_key, []).append(stem.resolve().relative_to(repo.resolve()).as_posix())
    for row in _index_rows(stem):
        for path in parse_files_owned(row.get("Files owned", "")):
            m = re.match(r"~/Desktop/([^/]+)/?(.*)$", path)
            if m is None:
                if stem_key is not None:
                    owned.setdefault(stem_key, []).append(path)
            elif m.group(1) not in {".", ".."}:
                root = Path(os.path.expanduser(f"~/Desktop/{m.group(1)}"))
                key = _repo_key(root) if root.is_dir() else None
                if key is not None:
                    owned.setdefault(key, []).append(m.group(2) or ".")
    return owned


def _first_parent(home: Path, sha: str, *args: str) -> str:
    """`git diff <args> sha^ sha` — a merge's own change against its first parent — or,
    for a root commit (no `sha^`), `git show <args> --root`. Names and shortstat share it."""
    if _git(home, "rev-parse", "--verify", "--quiet", f"{sha}^")[0] == 0:
        return _git(home, "diff", *args, f"{sha}^", sha)[1]
    return _git(home, "show", *args, "--format=", "--root", sha)[1]


def _lane_note(home: Path, sha: str, owned: dict[Path, list[str]]) -> str | None:
    """None when the commit touches an owned path (the overlap gate's matching: equal,
    or one a directory prefix of the other); otherwise the note that says why not."""
    mine = owned.get(_repo_key(home), [])
    if not mine:
        return f"no owned paths in {home.name}"
    if "." in mine:
        return None
    names = _first_parent(home, sha, "--name-only")
    if any(paths_overlap(f, o) for f in names.splitlines() if f for o in mine):
        return None
    return "not a lane path"


def _cited_shas(stem: Path) -> dict[str, str]:
    """sha → the `##` section it is first cited in, in citation order."""
    seen: dict[str, str] = {}
    section = "(top)"
    for line in _report_text(stem).splitlines():
        heading = _HEADING2.match(line)
        if heading:
            section = heading.group(1).strip()
            continue
        for span in _SPAN.findall(line):
            for sha in _SHA.findall(span):
                seen.setdefault(sha, section)
    return seen


def _run_window(stem: Path) -> tuple[str, str] | None:
    data = _tracker(stem) or {}
    if not data.get("started") or not data.get("updated"):
        return None
    window = (_utc(data["started"]), _utc(data["updated"]))
    return None if any(w.startswith("(") for w in window) else window


def _commits_section(stem: Path, repo: Path | None) -> list[str]:
    out = ["### Commits", ""]
    shas = _cited_shas(stem)
    if not shas:
        return out + ["*No commit shas cited in the report.*", ""]
    repos = _repos(stem, repo)
    window = _run_window(stem)
    owned = _owned_paths(stem, repo)
    out += [
        "Every backticked sha cited anywhere in this report (context citations included — see "
        "Cited in), resolved against "
        + (", ".join(f"`{r.name}`" for r in repos) or "no repo")
        + ". When = committer time, UTC. Notes: `outside run window` (before tracker.started or "
        "after tracker.updated), `not a lane path` (touches none of the INDEX `Files owned` paths "
        "nor this stem's folder, diffed against the first parent), `no owned paths in <repo>` "
        "(no lane owns anything there). Diffstat: `--shortstat` against the first parent "
        "(`git diff sha^ sha`; root commits via `git show --root`); pushed = ancestor of the repo's upstream ref as last fetched "
        "(no fetch is run).",
        "",
        "| Repo | Commit | Cited in | When (UTC) | Notes | Subject | `--shortstat` (first parent) | Pushed |",
        "|---|---|---|---|---|---|---|---|",
    ]
    unresolved: list[tuple[str, str]] = []
    for sha, cited in shas.items():
        home = next(
            (r for r in repos if _git(r, "rev-parse", "--verify", "--quiet", f"{sha}^{{commit}}")[0] == 0),
            None,
        )
        if home is None:
            if not _ALL_DIGITS.fullmatch(sha):
                unresolved.append((sha, cited))
            continue
        _, subject = _git(home, "show", "-s", "--format=%s", sha)
        _, stamp = _git(home, "show", "-s", "--format=%cI", sha)
        when = _utc(stamp)
        notes = []
        if window and not (window[0] <= when <= window[1]):
            notes.append("outside run window")
        lane_note = _lane_note(home, sha, owned)
        if lane_note:
            notes.append(lane_note)
        stat = _first_parent(home, sha, "--shortstat").strip() or "no file changes"
        if _git(home, "rev-parse", "--is-shallow-repository")[1] == "true":
            pushed = "unknown (shallow)"
        elif _git(home, "rev-parse", "--verify", "--quiet", "@{u}")[0] != 0:
            pushed = "unknown (no upstream)"
        else:
            pushed = "yes" if _git(home, "merge-base", "--is-ancestor", sha, "@{u}")[0] == 0 else "no"
        out.append(
            f"| {home.name} | `{sha}` | {_cell(cited)} | {when} | {' · '.join(notes) or '-'} | {_cell(subject)} "
            f"| {_cell(stat)} (--shortstat) | {pushed} |"
        )
    for sha, cited in unresolved:
        out.append(f"| - | `{sha}` | {_cell(cited)} | - | - | unresolved in any repo above | - | - |")
    return out + [""]


def _files_section(stem: Path) -> list[str]:
    files = sorted(
        p.relative_to(stem).as_posix()
        for p in stem.rglob("*")
        if p.is_file() and not any(part.startswith(".") for part in p.relative_to(stem).parts)
    )
    out = ["### Files", ""]
    if not files:
        return out + ["*None on disk.*", ""]
    return out + [f"- `{f}`" for f in files] + [""]


def _open_section(stem: Path) -> str:
    text = _report_text(stem)
    heads = list(re.finditer(r"^##\s+(.*)$", text, re.M))
    for i, m in enumerate(heads):
        if _OPEN.fullmatch(m.group(1).strip()):
            end = heads[i + 1].start() if i + 1 < len(heads) else len(text)
            return text[m.end() : end]
    return ""


def _board_ids(stem: Path) -> list[tuple[int, str, str]]:
    """(id, entity, where it was first cited), in citation order."""
    ids: dict[int, tuple[str, str]] = {}

    def add(n: str, entity: str, where: str) -> None:
        ids.setdefault(int(n), (entity, where))

    for row in _index_rows(stem):
        cell = row.get("PBI / Feature", "")
        pbi, _, feature = cell.partition("/")
        for n in _TASK_ID.findall(pbi):
            add(n, "pbi", f"INDEX lane {row.get('Lane', '?')}")
        for n in _TASK_ID.findall(feature):
            add(n, "feature", f"INDEX lane {row.get('Lane', '?')}")
    for wave in (_tracker(stem) or {}).get("waves", []):
        for lane in wave.get("lanes", []):
            for todo in lane.get("todos", []):
                for n in _TASK_ID.findall(str(todo.get("id", ""))):
                    add(n, "task", f"tracker lane {lane.get('lane', '?')} todo")
            for f in lane.get("findings", []):
                for n in _TASK_ID.findall(str(f.get("task", ""))):
                    add(n, "task", f"tracker lane {lane.get('lane', '?')} finding")
    for n in _TASK_ID.findall(_open_section(stem)):
        add(n, "task", "report Open / deferred")
    return [(n, e, w) for n, (e, w) in ids.items()]


def _board_section(stem: Path, repo: Path | None, lookup: bool) -> list[str]:
    ids = _board_ids(stem)
    out = ["### Board", ""]
    if not ids:
        return out + ["*No board ids cited.*", ""]
    state = None
    if lookup and repo is not None and (repo / "board").is_dir():
        from taskman.eventlog import store

        state = store.state(repo / "board")
    if state is None:
        out += ["| Id | Kind | Cited in |", "|---|---|---|"]
        out += [f"| #{n} | {e} | {w} |" for n, e, w in ids]
    else:
        out += ["| Id | Kind | Cited in | Status | Title |", "|---|---|---|---|---|"]
        for n, e, w in ids:
            row = state.get(e, {}).get(n)
            status, title = (row.get("status", "?"), row.get("title", "")) if row else ("not on board", "")
            out.append(f"| #{n} | {e} | {w} | {status} | {_cell(title)} |")
    return out + [""]


# --- assembly -----------------------------------------------------------------


def _repo_root(stem: Path) -> Path | None:
    code, top = _git(stem, "rev-parse", "--show-toplevel")
    return Path(top) if code == 0 and top else None


def _stem_dir(path: Path) -> Path:
    path = Path(path).resolve()
    return path.parent if path.name == "dispatch" else path


class MarkerError(Exception):
    """The report's markers are not a clean (0, 0) or (1, 1) pair — writing would guess."""


def render(stem: Path, *, board: bool = False) -> str:
    """The `## Run record` heading plus the marker-wrapped block, ending in a newline."""
    stem = _stem_dir(stem)
    repo = _repo_root(stem)
    body = (
        _tracker_section(stem)
        + _timeline_section(stem, repo)
        + _commits_section(stem, repo)
        + _files_section(stem)
        + _board_section(stem, repo, board)
    )
    note = "*Generated by `python -m taskman.mow.run_report` — re-run it, do not edit by hand.*"
    return "\n".join([HEADING, "", BEGIN, note, "", *body]).rstrip("\n") + "\n" + END + "\n"


def write(stem: Path, *, board: bool = False) -> Path:
    """Insert the block into action-report.md, or replace the one already there.

    Refuses (MarkerError, nothing written) unless the report has no whole-line
    markers or exactly one begin followed by one end. Line endings are kept as found.
    """
    stem = _stem_dir(stem)
    report = stem / "action-report.md"
    with open(report, encoding="utf-8", newline="") as fh:
        text = fh.read()
    if _unclosed_fence(text):
        # The fence would hide a real block, and the append below would then add a second.
        raise MarkerError(f"{report.name} has an unclosed ``` fence — close it, nothing written")
    begins, ends = _marker_lines(text)
    span = block_span(text)
    if span is None and (begins or ends):
        raise MarkerError(
            f"{report.name} has {len(begins)} begin / {len(ends)} end markers — remove the "
            "stray one, nothing written"
        )
    eol = "\r\n" if "\r\n" in text else "\n"
    rendered = render(stem, board=board)
    if span:
        block = rendered[rendered.index(BEGIN) :].rstrip("\n").replace("\n", eol)
        new = text[: span[0]] + block + text[span[1] :]
    else:
        new = text.rstrip("\r\n") + eol + eol + rendered.replace("\n", eol)
    with open(report, "w", encoding="utf-8", newline="") as fh:
        fh.write(new)
    return report


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    flags = {a for a in args if a.startswith("--")}
    paths = [a for a in args if not a.startswith("--")]
    if len(paths) != 1 or flags - {"--write", "--board"}:
        print(__doc__.strip(), file=sys.stderr)
        return 2
    stem = _stem_dir(Path(paths[0]).resolve())
    if not stem.is_dir():
        print(f"not found: {stem}", file=sys.stderr)
        return 2
    board = "--board" in flags
    if "--write" in flags:
        if not (stem / "action-report.md").is_file():
            print(f"missing {stem / 'action-report.md'} — write the report first", file=sys.stderr)
            return 1
        try:
            print(f"run record written: {write(stem, board=board)}")
        except MarkerError as exc:
            print(exc, file=sys.stderr)
            return 1
    else:
        sys.stdout.write(render(stem, board=board))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
