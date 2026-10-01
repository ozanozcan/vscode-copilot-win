#!/usr/bin/env python3
"""Bootstrap the bundled taskman runtime into a repository-local environment.

Creates (or reuses) `.venv` at the repository root, installs the dependencies that
`taskman/pyproject.toml` declares, and points the environment at the bundled
`taskman/` source. No global taskman CLI is used or installed.

Prerequisite: pip must reach a package index (PyPI by default) or a local
wheelhouse passed with `--find-links DIR`, which also disables index access.

Run with the repository's Python launcher:
  Windows:      bin\\py.cmd bin\\bootstrap-taskman.py [--init-board SLUG]
  macOS/Linux:  sh bin/py bin/bootstrap-taskman.py [--init-board SLUG]
"""

import sys

if sys.version_info < (3, 12):
    print("bootstrap: Python 3.12+ is required to run taskman", file=sys.stderr)
    raise SystemExit(1)

import argparse
import os
import re
import subprocess
import tomllib
import venv
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BUNDLE = ROOT / "taskman"
PTH_NAME = "public-harness-taskman.pth"
SLUG = re.compile(r"[a-z0-9][a-z0-9-]{0,62}")


class BootstrapError(Exception):
    pass


def _metadata():
    try:
        project = tomllib.loads((BUNDLE / "pyproject.toml").read_text(encoding="utf-8"))["project"]
    except (OSError, KeyError, tomllib.TOMLDecodeError) as error:
        raise BootstrapError(f"cannot read bundled taskman metadata: {error}") from None
    floor = re.fullmatch(r">=\s*(\d+)\.(\d+)", project.get("requires-python", ""))
    if floor is None:
        raise BootstrapError(f"unsupported requires-python: {project.get('requires-python')!r}")
    return project["version"], (int(floor[1]), int(floor[2])), list(project.get("dependencies", []))


def _interpreter(environment):
    if os.name == "nt":
        return environment / "Scripts" / "python.exe"
    return environment / "bin" / "python"


def _run(command, **kwargs):
    result = subprocess.run(command, cwd=ROOT, **kwargs)
    if result.returncode != 0:
        raise BootstrapError(f"command failed ({result.returncode}): {' '.join(map(str, command))}")
    return result


def _environment(path):
    if path.exists():
        if not (path / "pyvenv.cfg").is_file():
            raise BootstrapError(f"{path} exists but is not a virtual environment")
        print(f"bootstrap: reusing {path}")
    else:
        print(f"bootstrap: creating {path}")
        venv.EnvBuilder(with_pip=True).create(path)
    ignore = path / ".gitignore"
    if not ignore.exists():
        ignore.write_text("*\n", encoding="utf-8")
    python = _interpreter(path)
    if not python.is_file():
        raise BootstrapError(f"environment has no interpreter: {python}")
    return python


def _install(python, floor, dependencies, find_links):
    probe = _run([str(python), "-c", "import sys; print(*sys.version_info[:2])"],
                 capture_output=True, text=True)
    version = tuple(int(part) for part in probe.stdout.split())
    if version < floor:
        raise BootstrapError(f"environment Python {version} is older than required {floor}")
    if dependencies:
        command = [str(python), "-m", "pip", "install", "--disable-pip-version-check",
                   "--no-input"]
        if find_links:
            command += ["--no-index", "--find-links", str(find_links)]
        _run(command + dependencies)
    purelib = _run([str(python), "-c", "import sysconfig; print(sysconfig.get_path('purelib'))"],
                   capture_output=True, text=True).stdout.strip()
    (Path(purelib) / PTH_NAME).write_text(f"{BUNDLE}\n", encoding="utf-8")
    located = _run([str(python), "-c", "import taskman, taskman.cli; print(taskman.__file__)"],
                   capture_output=True, text=True).stdout.strip()
    if (BUNDLE / "taskman").resolve() not in Path(located).resolve().parents:
        raise BootstrapError(f"environment imports taskman from {located}, not the bundled runtime")


def _init_board(python, slug):
    marker = ROOT / ".taskman.toml"
    if marker.exists():
        try:
            current = tomllib.loads(marker.read_text(encoding="utf-8")).get("project", {}).get("slug")
        except tomllib.TOMLDecodeError as error:
            raise BootstrapError(f"cannot read {marker}: {error}") from None
        if current != slug:
            raise BootstrapError(f"{marker} names project {current!r}, not {slug!r}; refusing to retarget")
    else:
        marker.write_text(f'[project]\nslug = "{slug}"\nname = "{slug}"\n', encoding="utf-8")
    _run([str(python), "-m", "taskman", "init"])


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--venv", type=Path, default=ROOT / ".venv",
                        help="environment directory (default: <repo>/.venv)")
    parser.add_argument("--find-links", type=Path, metavar="DIR",
                        help="install only from this local wheelhouse (no index access)")
    parser.add_argument("--init-board", metavar="SLUG",
                        help="write .taskman.toml if absent and initialize an empty board/")
    args = parser.parse_args(argv)
    if args.init_board is not None and not SLUG.fullmatch(args.init_board):
        parser.error("--init-board needs a lowercase slug: letters, digits and hyphens")
    try:
        version, floor, dependencies = _metadata()
        if sys.version_info[:2] < floor:
            raise BootstrapError(f"Python {floor[0]}.{floor[1]}+ is required to run taskman")
        python = _environment(args.venv.resolve())
        _install(python, floor, dependencies, args.find_links)
        if args.init_board:
            _init_board(python, args.init_board)
    except BootstrapError as error:
        print(f"bootstrap: {error}", file=sys.stderr)
        return 1
    print(f"bootstrap: taskman {version} ready; run it with:")
    shown = python.relative_to(ROOT) if python.is_relative_to(ROOT) else python
    print(f"  {shown} -m taskman --help")
    return 0


if __name__ == "__main__":
    sys.exit(main())
