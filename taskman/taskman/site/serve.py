"""The `taskman site` server: read-only, loopback-only, one port per project.

D1 — nothing here writes. Only GET and HEAD are answered; every other method
is 405. D2 — the server binds 127.0.0.1 and serves eight things: `/` (the
Roadmap page), `/board` (the Board page), `/static/<file>` (from this
package's `static/` only), `/api/project`, `/api/roadmap`, `/api/board` and
`/api/live` (each rebuilt from the board and trackers on every request, so a
reload is never stale — D8; the two board endpoints are also sent
`Cache-Control: no-store` for the page's 3 s poll, kanban-board K10) and
`/.site`, the identity marker. D3 — the port is keyed on the
repo's realpath and ownership is settled by asking the server on it, never by
guessing from the port; another project's site is stepped over, never killed.
"""

from __future__ import annotations

import hashlib
import http.server
import json
import mimetypes
import socket
import sys
import tomllib
import urllib.parse
import urllib.request
import webbrowser
from pathlib import Path

from taskman import kanban, roadmap

# Port choice mirrors skills/mow/tracker_port.py (derive / listening / serves /
# pick), reimplemented because a taskman package must not import from skills/.
# The tracker owns 8300-8379 and product-analysis sits on 8420, hence 8500.
BASE, SPAN = 8500, 80
PROBE_TIMEOUT = 0.4  # loopback: a live server answers in ~1ms
MARKER = ".site"
STATIC_DIR = Path(__file__).parent / "static"
_TEXT = "text/plain; charset=utf-8"
# DNS rebinding: a page on evil.example resolving to 127.0.0.1 would reach us
# with its own Host header; only loopback names are answered.
_HOSTS = {"127.0.0.1", "localhost", "::1"}




class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None  # a 3xx on the probe is "not ours", never a hop to someone's marker


# a configured http_proxy must never swallow a loopback probe
_opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), _NoRedirect)


def repo(root: Path) -> str:
    """The project's identity: one resolved path (a symlink or /tmp vs
    /private/tmp on macOS is one site, not two)."""
    return str(Path(root).resolve())


def project(root: Path) -> dict:
    """{slug, name, root} from `root`'s own marker — the served project, never the cwd's."""
    data = tomllib.loads((Path(root) / ".taskman.toml").read_text(encoding="utf-8"))
    proj = data.get("project", data)
    if not proj.get("slug"):
        raise SystemExit(f"taskman: {Path(root) / '.taskman.toml'} has no project.slug — refusing to guess.")
    return {"slug": proj["slug"], "name": proj.get("name", proj["slug"]), "root": repo(root)}


def derive(root: Path) -> int:
    """This project's home port. Same repo, same URL, every run."""
    return BASE + int(hashlib.md5(repo(root).encode()).hexdigest(), 16) % SPAN


def listening(port: int) -> bool:
    with socket.socket() as sock:
        sock.settimeout(PROBE_TIMEOUT)
        return sock.connect_ex(("127.0.0.1", port)) == 0


def serves(port: int, root: Path) -> bool:
    """True when the server on `port` answers `/.site` with THIS project's realpath."""
    try:
        with _opener.open(f"http://127.0.0.1:{port}/{MARKER}", timeout=PROBE_TIMEOUT) as resp:
            return resp.read(65536).decode().strip() == repo(root)
    except Exception:  # 404, refused, dropped, not HTTP at all, not UTF-8
        return False


def pick_port(root: Path) -> tuple[int, str]:
    """(port, "serve" | "reuse") — the first port that is free, or already ours.

    Walks forward from the home port so a collision with another project costs
    one port, not a shared page; whatever holds a port is stepped over (L34).
    """
    home = derive(root)
    for step in range(SPAN):
        port = BASE + (home - BASE + step) % SPAN
        if not listening(port):
            return port, "serve"
        if serves(port, root):
            return port, "reuse"
    raise SystemExit(f"taskman site: no free port in {BASE}-{BASE + SPAN - 1}")


def owned(root: Path) -> int | None:
    """The port this project's site is really live on, or None — `taskman site --owned`,
    the check `serve-detached` polls (#283). Walks the same range `pick_port` does."""
    home = derive(root)
    for step in range(SPAN):
        port = BASE + (home - BASE + step) % SPAN
        if listening(port) and serves(port, root):
            return port
    return None


_NOT_FOUND = (404, _TEXT, b"not found\n")
_WRONG_HOST = (421, _TEXT, b"misdirected request\n")
_BUILD_FAILED = (500, _TEXT,
                 b"taskman site: roadmap failed to build \xe2\x80\x94 run `taskman roadmap` for the error\n")
# Fixed bodies, like _BUILD_FAILED: a store error names the log file's path and line.
_BOARD_FAILED = (500, _TEXT, b"taskman site: board failed to build \xe2\x80\x94 run `taskman board` for the error\n")
_LIVE_FAILED = (500, _TEXT, b"taskman site: live overlay failed to build \xe2\x80\x94 run `taskman board` for the error\n")
_NO_STORE = {"Cache-Control": "no-store"}


def _json(doc: dict, headers: dict[str, str] | None = None) -> tuple:
    return 200, "application/json", json.dumps(doc).encode(), headers or {}


class _Handler(http.server.BaseHTTPRequestHandler):
    server: "_Site"
    server_version = "taskman"
    sys_version = ""

    def version_string(self) -> str:  # the default appends " " + sys_version
        return self.server_version

    def do_GET(self) -> None:
        self._answer(*self._route())

    def do_HEAD(self) -> None:
        self._answer(*self._route(), body_out=False)

    def __getattr__(self, name: str):
        # http.server looks up `do_<METHOD>` per request and answers 501 when it is
        # missing; every method but GET/HEAD is 405 here instead (D1: read-only).
        if name.startswith("do_"):
            return self._method_not_allowed
        raise AttributeError(name)

    def _method_not_allowed(self) -> None:
        self.send_response(405)
        self.send_header("Allow", "GET, HEAD")
        self.send_header("Content-Length", "0")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()

    def _route(self) -> tuple:
        """(status, content type, body[, extra headers])."""
        if not self._host_is_loopback():
            return _WRONG_HOST
        path = urllib.parse.unquote(self.path.split("?", 1)[0])
        if path == "/":
            return self._static("index.html", missing=(
                503, _TEXT, b"taskman site: the site assets are not installed "
                b"(taskman/site/static/index.html is missing).\n"))
        if path == "/board":
            return self._static("board.html", missing=(
                503, _TEXT, b"taskman site: the Board page is not installed "
                b"(taskman/site/static/board.html is missing).\n"))
        if path.startswith("/static/"):
            return self._static(path[len("/static/"):])
        if path == "/" + MARKER:
            return 200, _TEXT, (repo(self.server.root) + "\n").encode()
        if path == "/api/project":
            return _json(self.server.project)
        if path == "/api/roadmap":
            try:
                doc = roadmap.build(self.server.root)  # per request, never cached (D8)
            except Exception:  # store errors carry paths: never echoed to the client
                return _BUILD_FAILED
            return _json(doc)
        if path == "/api/board":
            try:
                doc = kanban.build(self.server.root)  # per request, never cached (D8)
            except Exception:
                return _BOARD_FAILED
            return _json(doc, _NO_STORE)
        if path == "/api/live":
            try:
                doc = kanban.live(self.server.root)
            except Exception:
                return _LIVE_FAILED
            return _json(doc, _NO_STORE)
        return _NOT_FOUND

    def _host_is_loopback(self) -> bool:
        try:
            return urllib.parse.urlsplit("//" + self.headers.get("Host", "")).hostname in _HOSTS
        except ValueError:  # unparseable Host
            return False

    def _static(self, name: str, missing: tuple[int, str, bytes] | None = None) -> tuple[int, str, bytes]:
        """A file from the static dir only: `..`, `%2e%2e` and absolute names resolve
        outside it and are 404, never read."""
        static_dir = self.server.static_dir
        try:
            target = (static_dir / name).resolve()
            if not target.is_relative_to(static_dir):
                return _NOT_FOUND
            if not target.is_file():
                return missing or _NOT_FOUND
        except (ValueError, OSError):  # NUL byte, over-long name: the filesystem's no is a 404
            return _NOT_FOUND
        kind = mimetypes.guess_type(target.name)[0] or "application/octet-stream"
        if kind.startswith("text/") or kind == "application/javascript":
            kind += "; charset=utf-8"
        return 200, kind, target.read_bytes()

    def _answer(self, status: int, content_type: str, body: bytes, headers: dict[str, str] | None = None,
                body_out: bool = True) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("X-Content-Type-Options", "nosniff")
        for name, value in (headers or {}).items():
            self.send_header(name, value)
        self.end_headers()
        if body_out:
            self.wfile.write(body)

    def log_message(self, format: str, *args) -> None:  # quiet: the URL line is the output
        pass


class _Site(http.server.ThreadingHTTPServer):
    def __init__(self, root: Path, port: int, static_dir: Path) -> None:
        self.root = Path(root)
        self.project = project(root)
        self.static_dir = Path(static_dir).resolve()
        super().__init__(("127.0.0.1", port), _Handler)

    def handle_error(self, request, client_address) -> None:  # one line, no traceback
        print(f"taskman site: request from {client_address[0]}:{client_address[1]} failed: "
              f"{type(sys.exc_info()[1]).__name__}", file=sys.stderr)


def make_server(root: Path, port: int, static_dir: Path) -> http.server.ThreadingHTTPServer:
    return _Site(root, port, static_dir)


def main(root: Path, open_browser: bool = False) -> int:
    port, action = pick_port(root)
    url = f"http://127.0.0.1:{port}"
    print(url, flush=True)
    if action == "reuse":
        return 0
    try:
        server = make_server(root, port, STATIC_DIR)
    except OSError:  # taken between the probe and the bind: step over by rerunning, never kill
        raise SystemExit(f"taskman site: port {port} was taken while starting \u2014 rerun") from None
    if open_browser:
        webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0
