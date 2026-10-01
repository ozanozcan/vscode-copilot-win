"""Wrap-up reconcile gate — evidence over recall.

Produces two worklists the agent must clear before /wrap-up continues:

* **unattributed** — paths changed since session start that no open ticket claims
* **stale** — every ``in_progress`` ticket requiring done / still-open / blocked
  with a citation

Exit 1 while either list remains after applying the session receipt.
"""

from __future__ import annotations

import datetime as dt
import gzip
import json
import os
import re
import subprocess
import zlib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from taskman.config import find_project
from taskman.eventlog import store

MARKER_DIRNAME = ".session-markers"
RECEIPT_SUFFIX = ".receipt.json"
MARKER_WARM_SECONDS = 15 * 60
OPEN_STATUSES = frozenset({"backlog", "todo", "in_progress", "blocked"})
STALE_STATUS = "in_progress"
DONE_EXCLUDED = frozenset({"done", "disabled"})
DESIGN_TAG_MARKERS = frozenset(
    {
        "kind:design",
        "design",
        "spike",
        "kind:spike",
        "kind:decision",
    }
)
DESIGN_ROLES = frozenset({"explore", "ui-design"})
VERIFY_LINE_RE = re.compile(
    r"(?m)^\s*(?:[-*]\s*)?(?:`([^`]+)`|((?:\.venv/bin/)?(?:pytest|python\s+-m\s+pytest|make|ruff|mypy|npm\s+test)\b[^\n]*))"
)
IGNORE_PATH_PREFIXES = (
    ".session-markers/",
    "docs/session-reports/",
    "docs/chat-history/",
    "tmp/",
    ".git/",
    "__pycache__/",
    ".pytest_cache/",
    ".mypy_cache/",
    ".ruff_cache/",
    "node_modules/",
    ".venv/",
)


@dataclass
class Marker:
    path: Path
    session_id: str
    start_sha: str
    worktree: Path
    branch: str = ""
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass
class GateResult:
    unattributed: list[str]
    stale: list[dict[str, Any]]
    marker: Marker | None
    receipt_path: Path | None
    ok: bool
    # Board log regressed against HEAD / start_sha / upstream (d#82). No
    # receipt can clear it.
    board_regression: str | None = None
    # Why the board log could not be checked (d#110: never fail silent).
    board_note: str | None = None
    # wrapup-audit-links, bounded (d#108). Informational: never read by `ok`.
    audit: str | None = None
    owner_context: dict[str, int | str] = field(default_factory=dict)


@dataclass
class Evidence:
    committed_paths: list[str]
    dirty_paths: list[str]
    commit_sessions: dict[str, set[str]]


def _cam_entries_from_dir(cam_dir: Path) -> list[dict[str, Any]]:
    live = cam_dir / "journal.jsonl"
    archive = cam_dir / "archive"
    if not live.is_file():
        raise ValueError("CAM evidence incomplete: live journal is missing or unreadable; recover CAM history and re-run (no start_sha..HEAD fallback)")

    try:
        try:
            archive.lstat()
            archive_exists = True
        except FileNotFoundError:
            archive_exists = False
        if archive_exists and not archive.is_dir():
            raise ValueError("archive path is not a directory")
        archive_files = list(archive.iterdir()) if archive_exists else []
        archive_gens = sorted(
            (int(match.group(1)), path)
            for path in archive_files
            if (match := re.fullmatch(r"journal-(\d+)\.jsonl\.gz", path.name))
        )
        generation_path = cam_dir / "generation"
        try:
            generation_text = generation_path.read_text(encoding="utf-8").strip()
            generation = int(generation_text) if generation_text else 0
            if generation < 0:
                generation = None
        except (OSError, ValueError):
            generation = None
    except OSError as exc:
        raise ValueError(f"CAM evidence incomplete: cannot inspect archive history: {exc}; recover CAM history and re-run (no start_sha..HEAD fallback)") from exc

    archive_numbers = [number for number, _ in archive_gens]
    if archive_numbers and archive_numbers != list(range(1, archive_numbers[-1] + 1)):
        raise ValueError("CAM evidence incomplete: archive generation gap; recover CAM history and re-run (no start_sha..HEAD fallback)")
    if generation is not None and generation > len(archive_numbers):
        raise ValueError("CAM evidence incomplete: archive generation is missing; recover CAM history and re-run (no start_sha..HEAD fallback)")

    entries: list[dict[str, Any]] = []
    for path, compressed in [(path, True) for _, path in archive_gens] + [(live, False)]:
        try:
            raw = path.read_bytes()
            if compressed:
                raw = gzip.decompress(raw)
        except (OSError, EOFError, zlib.error) as exc:
            raise ValueError(f"CAM evidence incomplete: cannot read {path.name}: {exc}; recover CAM history and re-run (no start_sha..HEAD fallback)") from exc
        if raw and not raw.endswith(b"\n"):
            raise ValueError(f"CAM evidence incomplete: {path.name} has a partial final record; recover CAM history and re-run (no start_sha..HEAD fallback)")
        for lineno, line in enumerate(raw.split(b"\n")[:-1], start=1):
            try:
                row = json.loads(line.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                raise ValueError(f"CAM evidence incomplete: corrupt {path.name} line {lineno}; recover CAM history and re-run (no start_sha..HEAD fallback)") from exc
            if not isinstance(row, dict) or _parse_cam_ts(row.get("ts")) is None:
                raise ValueError(f"CAM evidence incomplete: malformed {path.name} line {lineno}; recover CAM history and re-run (no start_sha..HEAD fallback)")
            entries.append(row)
    return sorted(entries, key=lambda row: str(row.get("ts") or ""))


def _cam_entries(worktree: Path) -> list[dict[str, Any]]:
    common = _git(worktree, "rev-parse", "--path-format=absolute", "--git-common-dir").strip()
    if not common:
        raise ValueError("CAM evidence incomplete: Git common directory is unavailable; recover CAM history and re-run (no start_sha..HEAD fallback)")
    cam_dir = Path(os.environ.get("CAM_DIR") or Path(common) / "cam")
    return _cam_entries_from_dir(cam_dir)


def _parse_cam_ts(raw: Any) -> dt.datetime | None:
    if not isinstance(raw, str) or not raw.strip():
        return None
    try:
        stamp = dt.datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None
    return stamp if stamp.tzinfo else stamp.replace(tzinfo=dt.timezone.utc)


def _commit_reachable(worktree: Path, ref: str) -> bool:
    _git_evidence(worktree, "rev-parse", "--git-dir")
    resolution = _git_evidence(
        worktree,
        "rev-parse",
        "--verify",
        "--quiet",
        f"{ref}^{{commit}}",
        allowed_returncodes=(0, 1),
    )
    if resolution.returncode == 1:
        return False
    resolved = resolution.stdout.decode("utf-8", errors="replace").strip()
    if not resolved:
        raise ValueError(f"Git evidence incomplete: could not resolve commit ref {ref!r}")
    reachability = _git_evidence(
        worktree,
        "merge-base",
        "--is-ancestor",
        resolved,
        "HEAD",
        allowed_returncodes=(0, 1),
    )
    return reachability.returncode == 0


def _git_evidence(
    worktree: Path,
    *args: str,
    allowed_returncodes: tuple[int, ...] = (0,),
) -> subprocess.CompletedProcess[bytes]:
    command = ["git", "-C", str(worktree), *args]
    try:
        proc = subprocess.run(command, capture_output=True, check=False)
    except OSError as exc:
        raise ValueError(f"Git evidence incomplete: could not run {' '.join(command)}: {exc}") from exc
    if proc.returncode not in allowed_returncodes:
        stderr = proc.stderr
        detail = stderr.decode("utf-8", errors="replace").strip() if isinstance(stderr, bytes) else str(stderr or "").strip()
        suffix = f": {detail}" if detail else ""
        raise ValueError(
            f"Git evidence incomplete: {' '.join(command)} failed with exit {proc.returncode}{suffix}"
        )
    return proc


def _git_nul_paths(worktree: Path, *args: str) -> list[str]:
    proc = _git_evidence(worktree, *args)
    return [os.fsdecode(path) for path in proc.stdout.split(b"\0") if path]


def _commit_paths(worktree: Path, ref: str) -> list[str]:
    return sorted(
        set(
            _git_nul_paths(
                worktree,
                "diff-tree",
                "--no-commit-id",
                "--name-only",
                "-r",
                "-z",
                "--root",
                "-m",
                ref,
            )
        )
    )


def collect_evidence(worktree: Path, marker: Marker) -> Evidence:
    if marker.raw.get("manual"):
        raise ValueError(
            "CAM evidence incomplete: manual --since has no selected-session provenance; "
            "pass --session-id <id> or --marker <path> and recover CAM history if needed "
            "(no start_sha..HEAD fallback)"
        )
    entries = _cam_entries(worktree)
    started = _parse_marker_started_at(marker)
    if started is None:
        raise ValueError("CAM evidence incomplete: selected marker has no valid started_at; recover CAM history and re-run (no start_sha..HEAD fallback)")
    stamps = [stamp for stamp in (_parse_cam_ts(row.get("ts")) for row in entries) if stamp]
    if started and (not stamps or started < min(stamps)):
        raise ValueError(
            "CAM evidence incomplete for selected session: available journal/archive coverage "
            "starts after the selected marker; recover CAM history and re-run (no start_sha..HEAD fallback)"
        )

    committed: set[str] = set()
    commit_sessions: dict[str, set[str]] = {}
    refs: dict[str, list[str] | None] = {}
    for row in entries:
        if row.get("kind") not in {"commit", "sync"} or row.get("status") == "error":
            continue
        session = str(row.get("session") or "")
        ref = str(row.get("ref") or "").strip()
        if session != marker.session_id or not ref:
            continue
        if ref not in refs:
            refs[ref] = (
                [path for path in _commit_paths(worktree, ref) if not path_ignored(path)]
                if _commit_reachable(worktree, ref)
                else None
            )
        paths = refs[ref]
        if paths is None:
            continue
        committed.update(paths)
        for path in paths:
            commit_sessions.setdefault(path, set()).add(session)

    dirty = set(_git_nul_paths(worktree, "diff", "--name-only", "-z", "HEAD"))
    dirty.update(_git_nul_paths(worktree, "ls-files", "--others", "--exclude-standard", "-z"))
    dirty = {path for path in dirty if not path_ignored(path)}
    return Evidence(sorted(committed), sorted(dirty), commit_sessions)


def find_repo_root(start: Path | None = None) -> Path:
    here = (start or Path.cwd()).resolve()
    for d in (here, *here.parents):
        if (d / ".taskman.toml").is_file():
            return d
    raise FileNotFoundError("no .taskman.toml above cwd")


def _git(worktree: Path, *args: str) -> str:
    proc = subprocess.run(
        ["git", "-C", str(worktree), *args],
        capture_output=True,
        text=True,
        check=False,
    )
    if proc.returncode != 0:
        return ""
    return proc.stdout


def load_marker(
    *,
    worktree: Path | None = None,
    marker_path: Path | None = None,
    session_id: str | None = None,
    since: str | None = None,
) -> Marker:
    root = worktree or find_repo_root()
    if marker_path is None and session_id is None:
        if os.environ.get("WRAPUP_SESSION_MARKER"):
            marker_path = Path(os.environ["WRAPUP_SESSION_MARKER"])
        elif os.environ.get("WRAPUP_SESSION_ID"):
            session_id = os.environ["WRAPUP_SESSION_ID"]

    if marker_path is None and session_id:
        candidate = root / MARKER_DIRNAME / f"{session_id}.json"
        if not candidate.is_file():
            raise FileNotFoundError(
                f"session marker for --session-id {session_id!r} was not found; "
                "pass --session-id <id> or --marker <path>"
            )
        marker_path = candidate

    if marker_path is None and since:
        return Marker(
            path=root / MARKER_DIRNAME / "_manual.json",
            session_id=session_id or "manual",
            start_sha=since,
            worktree=root,
            branch=_git(root, "branch", "--show-current").strip(),
            raw={"start_sha": since, "manual": True},
        )

    if marker_path is None:
        # Only a unique warm marker is safe identity evidence; retained markers
        # are forensic records and must not be guessed from by age or mtime.
        marker_dir = root / MARKER_DIRNAME
        warm: list[Path] = []
        now = dt.datetime.now(dt.timezone.utc)
        if marker_dir.is_dir():
            for candidate in marker_dir.glob("*.json"):
                if candidate.name.endswith(RECEIPT_SUFFIX):
                    continue
                try:
                    data = json.loads(candidate.read_text(encoding="utf-8"))
                    if not isinstance(data, dict) or not str(data.get("worktree") or "").strip():
                        continue
                    recorded_worktree = Path(str(data["worktree"])).resolve()
                    stamp = str(data.get("updated_at") or data.get("started_at") or "")
                    heartbeat = dt.datetime.fromisoformat(stamp.replace("Z", "+00:00"))
                except (OSError, TypeError, ValueError, json.JSONDecodeError):
                    continue
                if heartbeat.tzinfo is None:
                    heartbeat = heartbeat.replace(tzinfo=dt.timezone.utc)
                age = (now - heartbeat).total_seconds()
                if recorded_worktree == root.resolve() and 0 <= age <= MARKER_WARM_SECONDS:
                    warm.append(candidate)

        if len(warm) != 1:
            raise FileNotFoundError(
                "implicit session marker selection is unsafe: found "
                f"{len(warm)} warm markers for this worktree; pass --session-id "
                "<id> or --marker <path>"
            )
        marker_path = warm[0]

    if marker_path is None or not marker_path.is_file():
        raise FileNotFoundError(
            "no session marker — session-start hook did not run, "
            "or pass --since <sha> / --marker <path>"
        )

    data = json.loads(marker_path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise FileNotFoundError(f"marker {marker_path} must contain a JSON object")
    recorded_worktree = str(data.get("worktree") or "").strip()
    if not recorded_worktree:
        raise FileNotFoundError(f"marker {marker_path} has no worktree")
    return Marker(
        path=marker_path,
        session_id=str(data.get("session_id") or marker_path.stem),
        start_sha=str(data.get("start_sha") or ""),
        worktree=Path(recorded_worktree),
        branch=str(data.get("branch") or ""),
        raw=data if isinstance(data, dict) else {},
    )


def receipt_path_for(marker: Marker) -> Path:
    return marker.path.with_name(marker.path.stem + RECEIPT_SUFFIX)


def load_receipt(path: Path | None) -> dict[str, Any]:
    if path is None or not path.is_file():
        return {"schema": 1, "unattributed": {}, "stale": {}}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"schema": 1, "unattributed": {}, "stale": {}}
    if not isinstance(data, dict):
        return {"schema": 1, "unattributed": {}, "stale": {}}
    data.setdefault("unattributed", {})
    data.setdefault("stale", {})
    return data


def save_receipt(path: Path, receipt: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def normalize_path(raw: str) -> str | None:
    text = raw.strip().strip("`").strip()
    if not text or " " in text and not text.endswith("/"):
        # Prose with spaces is not a path claim (unless directory trailing slash).
        if " " in text:
            return None
    text = text.lstrip("./")
    if not text or text in {".", "*"}:
        return None
    return text


def path_ignored(path: str) -> bool:
    p = path.lstrip("./")
    return any(p == pref.rstrip("/") or p.startswith(pref) for pref in IGNORE_PATH_PREFIXES)


def path_claimed(path: str, claims: set[str]) -> bool:
    p = path.lstrip("./")
    for claim in claims:
        c = claim.lstrip("./").rstrip("/")
        if not c:
            continue
        if p == c or p.startswith(c + "/"):
            return True
        # Claimed file under a changed directory prefix is not enough to cover
        # sibling files — only exact / descendant matches count.
    return False


def changed_paths(worktree: Path, start_sha: str) -> list[str]:
    dirty = set(_git_nul_paths(worktree, "diff", "--name-only", "-z", "HEAD"))
    dirty.update(_git_nul_paths(worktree, "ls-files", "--others", "--exclude-standard", "-z"))
    return sorted(path for path in dirty if path and not path_ignored(path))


def claims_from_task(task: dict[str, Any]) -> set[str]:
    claims: set[str] = set()
    brief = task.get("brief") if isinstance(task.get("brief"), dict) else {}
    files = brief.get("files") if isinstance(brief.get("files"), list) else []
    for raw in files:
        norm = normalize_path(str(raw))
        if norm:
            claims.add(norm)
    return claims


def open_task_claims(board_dir: Path) -> dict[int, set[str]]:
    tasks = store.state(board_dir)["task"].values()
    return {
        t["id"]: claims_from_task(t)
        for t in tasks
        if t.get("status") in OPEN_STATUSES
    }


def in_progress_tasks(board_dir: Path) -> list[dict[str, Any]]:
    return sorted(
        (
            t
            for t in store.state(board_dir)["task"].values()
            if t.get("status") == STALE_STATUS
        ),
        key=lambda t: t["id"],
    )


def extract_verify_command(task: dict[str, Any]) -> str | None:
    brief = task.get("brief") if isinstance(task.get("brief"), dict) else {}
    explicit = brief.get("verify")
    if isinstance(explicit, str) and explicit.strip():
        return explicit.strip()
    acceptance = brief.get("acceptance") or ""
    if not isinstance(acceptance, str):
        acceptance = str(acceptance)
    matches = VERIFY_LINE_RE.findall(acceptance)
    for a, b in matches:
        cmd = (a or b).strip()
        if cmd:
            return cmd
    return None


def is_design_ticket(task: dict[str, Any]) -> bool:
    tags = {str(t).lower() for t in (task.get("tags") or [])}
    if tags & DESIGN_TAG_MARKERS:
        return True
    brief = task.get("brief") if isinstance(task.get("brief"), dict) else {}
    role = str(brief.get("role") or "").strip().lower()
    if role in DESIGN_ROLES and not extract_verify_command(task):
        return True
    return False


def _board_dir() -> Path:
    """Board for the cwd project (identity via the marker; d-p6)."""
    find_project()  # stops loudly on a missing marker or slug
    board = find_repo_root() / "board"
    if not board.is_dir():
        raise RuntimeError(f"{board} missing — run taskman init")
    return board


def _task_sessions(task: dict[str, Any]) -> set[str]:
    sessions: set[str] = set()
    for key in ("session", "session_id", "owner_session", "linked_session", "committing_session"):
        value = task.get(key)
        if isinstance(value, str) and value.strip():
            sessions.add(value.strip())
    brief = task.get("brief") if isinstance(task.get("brief"), dict) else {}
    for key in ("session", "session_id", "owner_session", "linked_session", "committing_session"):
        value = brief.get(key)
        if isinstance(value, str) and value.strip():
            sessions.add(value.strip())
    for tag in task.get("tags") or []:
        text = str(tag)
        if text.startswith("session:") and text[8:].strip():
            sessions.add(text[8:].strip())
    return sessions


def _task_event_sessions(board_dir: Path) -> dict[int, set[str]]:
    path = board_dir / "events.jsonl"
    try:
        lines = path.read_bytes().split(b"\n")[:-1]
    except FileNotFoundError:
        return {}
    except OSError as exc:
        raise ValueError(f"cannot read task event provenance: {exc}") from exc

    sessions: dict[int, set[str]] = {}
    for lineno, line in enumerate(lines, start=1):
        try:
            event = json.loads(line.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ValueError(f"corrupt task event log line {lineno}: {exc}") from exc
        if not isinstance(event, dict) or not str(event.get("type") or "").startswith("task."):
            continue
        task_id = event.get("id")
        session = event.get("session")
        if isinstance(task_id, int) and not isinstance(task_id, bool) and isinstance(session, str) and session.strip():
            sessions.setdefault(task_id, set()).add(session.strip())
    return sessions


def _mow_stem_ownership(
    worktree: Path,
) -> list[tuple[str, set[str], set[str]]]:
    from taskman.mow.preflight import _split_lanes_table_extended, parse_files_owned

    ownership: list[tuple[str, set[str], set[str]]] = []
    plans = worktree / "docs" / "plans"
    for index_path in sorted(plans.glob("*/dispatch/INDEX.md")):
        tracker_path = index_path.parent / "tracker.json"
        try:
            index_text = index_path.read_text(encoding="utf-8")
            tracker = json.loads(tracker_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if not isinstance(tracker, dict):
            continue
        raw_sessions = tracker.get("sessions")
        if not isinstance(raw_sessions, list) or any(
            not isinstance(session, str) for session in raw_sessions
        ):
            continue
        sessions = {session.strip() for session in raw_sessions if session.strip()}
        claims = {
            path
            for row in _split_lanes_table_extended(index_text)
            for path in parse_files_owned(row.get("files_owned", ""))
        }
        if claims:
            ownership.append((index_path.parent.parent.name, sessions, claims))
    return ownership


def residual_paths(
    evidence: Evidence,
    tasks: dict[int, dict[str, Any]],
    marker: Marker,
    event_sessions: dict[int, set[str]] | None = None,
) -> tuple[list[str], dict[str, int | str]]:
    owners: dict[str, int | str] = {}
    blocking = set(evidence.dirty_paths)
    mow_ownership = _mow_stem_ownership(marker.worktree)
    for path in evidence.committed_paths:
        path_sessions = {marker.session_id} | evidence.commit_sessions.get(path, set())
        for task_id, task in tasks.items():
            if not path_claimed(path, claims_from_task(task)):
                continue
            sessions = _task_sessions(task) | (event_sessions or {}).get(task_id, set())
            if sessions & path_sessions:
                owners[path] = task_id
                break
        if path in owners:
            continue
        historical_stem: str | None = None
        linked_stem: str | None = None
        for stem, sessions, claims in mow_ownership:
            if not path_claimed(path, claims):
                continue
            if sessions & path_sessions:
                linked_stem = stem
                break
            if historical_stem is None:
                historical_stem = stem
        if linked_stem is not None:
            owners[path] = f"MOW stem {linked_stem}"
        else:
            blocking.add(path)
            if historical_stem is not None:
                owners[path] = f"MOW stem {historical_stem} (not session-linked)"
    return sorted(blocking), owners


def unattributed_paths(
    worktree: Path,
    start_sha: str,
    board_dir: Path,
    *,
    tasks: dict[int, dict[str, Any]] | None = None,
    event_sessions: dict[int, set[str]] | None = None,
    evidence: Evidence | None = None,
    marker: Marker | None = None,
) -> list[str]:
    if evidence is not None:
        if marker is None:
            raise ValueError("marker is required when classifying collected evidence")
        task_state = store.state(board_dir)["task"] if tasks is None else tasks
        provenance = _task_event_sessions(board_dir) if event_sessions is None else event_sessions
        return residual_paths(evidence, task_state, marker, provenance)[0]
    changed = [p for p in changed_paths(worktree, start_sha) if not path_ignored(p)]
    claims_by_task = open_task_claims(board_dir)
    all_claims: set[str] = set()
    for claims in claims_by_task.values():
        all_claims |= claims
    return [p for p in changed if not path_claimed(p, all_claims)]


def _parse_marker_started_at(marker: Marker) -> dt.datetime | None:
    raw = marker.raw.get("started_at") if marker.raw else None
    if not isinstance(raw, str) or not raw.strip():
        return None
    text = raw.strip().replace("Z", "+00:00")
    try:
        when = dt.datetime.fromisoformat(text)
    except ValueError:
        return None
    if when.tzinfo is None:
        when = when.replace(tzinfo=dt.timezone.utc)
    return when


def _parse_board_ts(raw: Any) -> dt.datetime | None:
    """Board timestamps are ISO strings; tolerate absent/naive values."""
    if not isinstance(raw, str) or not raw.strip():
        return None
    try:
        when = dt.datetime.fromisoformat(raw.strip())
    except ValueError:
        return None
    if when.tzinfo is None:
        when = when.replace(tzinfo=dt.timezone.utc)
    return when


def task_touched_this_session(
    task: dict[str, Any],
    *,
    marker: Marker,
    changed: set[str],
    all_stale: bool = False,
) -> bool:
    """Scope stale candidates to session-touched work (not ancient board cruft).

    Full-board hygiene: pass ``all_stale=True``.
    """
    if all_stale:
        return True
    started = _parse_marker_started_at(marker)
    claimed_at = _parse_board_ts(task.get("claimed_at"))
    if claimed_at is not None and started is not None and claimed_at >= started:
        return True
    updated_at = _parse_board_ts(task.get("updated_at"))
    if updated_at is not None and started is not None and updated_at >= started:
        return True
    claims = claims_from_task(task)
    if claims and any(path_claimed(p, claims) for p in changed):
        return True
    return False


def stale_candidates(
    board_dir: Path,
    *,
    marker: Marker,
    changed: list[str] | None = None,
    all_stale: bool = False,
    evidence: Evidence | None = None,
) -> list[dict[str, Any]]:
    changed_set = (
        set(evidence.committed_paths) | set(evidence.dirty_paths)
        if evidence is not None
        else set(changed or [])
    )
    out: list[dict[str, Any]] = []
    for task in in_progress_tasks(board_dir):
        if not task_touched_this_session(
            task, marker=marker, changed=changed_set, all_stale=all_stale
        ):
            continue
        verify = extract_verify_command(task)
        design = is_design_ticket(task)
        out.append(
            {
                "id": task["id"],
                "title": task.get("title") or "",
                "status": task.get("status") or "",
                "verify": verify,
                "needs_operator_ack": design and verify is None,
                "files": sorted(claims_from_task(task)),
            }
        )
    return out


def _receipt_clears_unattributed(path: str, receipt: dict[str, Any]) -> bool:
    entries = receipt.get("unattributed") or {}
    if not isinstance(entries, dict):
        return False
    entry = entries.get(path) or entries.get(path.lstrip("./"))
    if not isinstance(entry, dict):
        return False
    action = str(entry.get("action") or "").lower()
    task_id = entry.get("task_id")
    if action in {"attach", "attached", "opened", "open", "ignore"} and task_id:
        return True
    if action == "ignore" and entry.get("reason"):
        return True
    return False


def _receipt_clears_stale(task_id: int, item: dict[str, Any], receipt: dict[str, Any]) -> bool:
    entries = receipt.get("stale") or {}
    if not isinstance(entries, dict):
        return False
    entry = entries.get(str(task_id)) or entries.get(task_id)
    if not isinstance(entry, dict):
        return False
    verdict = str(entry.get("verdict") or "").lower().replace("_", "-")
    citation = str(entry.get("citation") or "").strip()
    if verdict not in {"done", "still-open", "stillopen", "blocked"}:
        return False
    if not citation:
        return False
    if verdict == "done":
        if item.get("needs_operator_ack") and not entry.get("operator_ack"):
            return False
        verify = item.get("verify")
        if verify and not entry.get("verify_ok"):
            return False
    return True


def apply_receipt(
    unattributed: list[str],
    stale: list[dict[str, Any]],
    receipt: dict[str, Any],
) -> tuple[list[str], list[dict[str, Any]]]:
    left_u = [p for p in unattributed if not _receipt_clears_unattributed(p, receipt)]
    left_s = [item for item in stale if not _receipt_clears_stale(item["id"], item, receipt)]
    return left_u, left_s


def run_gate(
    *,
    worktree: Path | None = None,
    marker_path: Path | None = None,
    session_id: str | None = None,
    since: str | None = None,
    receipt_path: Path | None = None,
    all_stale: bool = False,
) -> GateResult:
    root = worktree or find_repo_root()
    marker = load_marker(
        worktree=root,
        marker_path=marker_path,
        session_id=session_id,
        since=since,
    )
    if not marker.start_sha or marker.start_sha == "UNKNOWN":
        raise ValueError(f"marker {marker.path} has no usable start_sha")

    board_dir = _board_dir()
    evidence = collect_evidence(marker.worktree, marker)
    tasks = store.state(board_dir)["task"]
    event_sessions = _task_event_sessions(board_dir)
    changed = sorted(set(evidence.committed_paths) | set(evidence.dirty_paths))
    raw_u = unattributed_paths(
        marker.worktree,
        marker.start_sha,
        board_dir,
        tasks=tasks,
        event_sessions=event_sessions,
        evidence=evidence,
        marker=marker,
    )
    raw_s = stale_candidates(
        board_dir,
        marker=marker,
        changed=changed,
        all_stale=all_stale,
        evidence=evidence,
    )
    rpath = receipt_path or receipt_path_for(marker)
    receipt = load_receipt(rpath)
    left_u, left_s = apply_receipt(raw_u, raw_s, receipt)
    regression, note = board_regression(root, start_sha=marker.start_sha)
    _, owner_context = residual_paths(evidence, tasks, marker, event_sessions)
    return GateResult(
        unattributed=left_u,
        stale=left_s,
        marker=marker,
        receipt_path=rpath,
        ok=not left_u and not left_s and regression is None,
        board_regression=regression,
        board_note=note,
        audit=gate_audit(root, board_dir),
        owner_context=owner_context,
    )


def gate_audit(root: Path, board_dir: Path) -> str:
    """The bounded audit section (d#108). Never raises: it informs, never blocks (d#84)."""
    from taskman.mow import audit_links

    checkpoints = root / "docs" / "checkpoints"
    try:
        report = audit_links.audit(board_dir, checkpoints if checkpoints.is_dir() else None)
    except Exception as exc:  # noqa: BLE001 — an audit failure must not change the verdict
        return f"audit not run: {exc}"
    return audit_links.format_report(report, limit=10)


UPSTREAM_NOTE = "board not compared against @{upstream}: HEAD is behind it — pull, then re-run"


def _board_refs(root: Path, start_sha: str) -> list[str]:
    """HEAD and the session's start_sha — deduped by commit.

    A `git reset --hard` (or a checkout of a shorter branch) moves HEAD back
    *with* the tree, so HEAD's board equals the rolled-back tree and a
    HEAD-only check passes. The start_sha's objects survive that move. Refs
    that do not resolve ("UNKNOWN") are skipped. `@{upstream}` is never a
    finding ref (d#115): after the SessionStart fetch every repo that commits
    its board sits behind it, so it only earns a note (`_behind_upstream`).
    """
    refs: list[str] = []
    seen: set[str] = set()
    for ref in ("HEAD", start_sha):
        if not ref or ref == "UNKNOWN":
            continue
        sha = _git(root, "rev-parse", "--verify", "--quiet", f"{ref}^{{commit}}").strip()
        if sha and sha not in seen:
            seen.add(sha)
            refs.append(ref)
    return refs


def _behind_upstream(root: Path) -> bool:
    """HEAD is a strict ancestor of @{upstream} (d#115): a pull is pending."""
    head = _git(root, "rev-parse", "--verify", "--quiet", "HEAD^{commit}").strip()
    upstream = _git(root, "rev-parse", "--verify", "--quiet", "@{upstream}^{commit}").strip()
    if not head or not upstream or head == upstream:
        return False
    return subprocess.run(
        ["git", "-C", str(root), "merge-base", "--is-ancestor", "HEAD", "@{upstream}"],
        capture_output=True, check=False,
    ).returncode == 0


def board_regression(root: Path, *, start_sha: str = "") -> tuple[str | None, str | None]:
    """(finding + recovery text, or None) and (notes, or None).

    The board log went backwards (d#82): measured against every ref in
    `_board_refs`; the first regression wins and the text names the ref it
    was measured against. Deliberately outside apply_receipt: a receipt
    cannot clear it. A tree the check cannot read against git (no repo, no
    commit yet) has no ref to have regressed from, so it is not a finding —
    but it is never silent either (d#110): the reason comes back as a note.
    So does a HEAD behind @{upstream} (d#115); both notes can appear at once.
    """
    from taskman.mow.check_board_log import CheckError, check_board_log, recovery

    notes: list[str] = []
    if _behind_upstream(root):
        notes.append(UPSTREAM_NOTE)
    try:
        for ref in _board_refs(root, start_sha) or ["HEAD"]:
            finding = check_board_log(root, ref=ref)
            if finding is not None:
                return f"against {ref}: {finding.message}\n{recovery(ref)}", "\n".join(notes) or None
    except CheckError as exc:
        notes.append(f"board log not checked: {exc}")
    return None, "\n".join(notes) or None


def format_gate_report(result: GateResult) -> str:
    lines: list[str] = []
    marker = result.marker
    if marker:
        lines.append(
            f"marker: {marker.path}  session={marker.session_id}  "
            f"start_sha={marker.start_sha[:12]}  branch={marker.branch or '-'}"
        )
    if result.receipt_path:
        lines.append(f"receipt: {result.receipt_path}")
    lines.append("")
    lines.append(f"## Unattributed ({len(result.unattributed)})")
    if result.unattributed:
        for p in result.unattributed:
            lines.append(f"- {p}")
        lines.append(
            "Clear: taskman wrapup record --attach <path> --task <id> "
            "| --opened <path> --task <id> | --ignore <path> --reason '...'"
        )
    else:
        lines.append("- (none)")
    lines.append("")
    if result.owner_context:
        lines.append(
            "## Committed owner context (informational; only session-linked owners auto-clear)"
        )
        for path, owner in sorted(result.owner_context.items()):
            label = f"task #{owner}" if isinstance(owner, int) else owner
            lines.append(f"- {path} -> {label}")
        lines.append("")
    lines.append(f"## Stale in_progress ({len(result.stale)})")
    if result.stale:
        for item in result.stale:
            flags = []
            if item.get("verify"):
                flags.append(f"verify={item['verify']!r}")
            if item.get("needs_operator_ack"):
                flags.append("needs_operator_ack")
            flag_s = f"  [{', '.join(flags)}]" if flags else ""
            lines.append(f"- #{item['id']} {item['title']}{flag_s}")
        lines.append(
            "Clear: taskman wrapup record --stale <id> --verdict done|still-open|blocked "
            "--citation '…' [--verify-ok] [--operator-ack]"
        )
    else:
        lines.append("- (none)")
    lines.append("")
    if result.board_regression:
        lines.append("## Board regression (no receipt clears this)")
        lines.append(result.board_regression)
        lines.append("")
    if result.board_note:
        lines.append(result.board_note)
        lines.append("")
    if result.audit:
        lines.append("## Audit (informational — never blocks)")
        lines.append(result.audit)
        lines.append("")
    if result.ok:
        lines.append("wrapup gate: OK")
    else:
        lines.append("wrapup gate: BLOCKED — clear the findings above, then re-run")
    return "\n".join(lines)
