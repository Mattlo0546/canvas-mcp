"""Offline tests against a fake Canvas: `uv run --with pytest pytest`. No Canvas account or network needed."""
import json
import os
import subprocess
import sys
import tempfile
import threading
import time
import urllib.parse
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import anyio

TMP = Path(tempfile.mkdtemp())
LIBRARY = TMP / "Slides"
SOON = "2099-01-01T00:00:00Z"


def _file(fid, name, folder=1, ctype="application/pdf"):
    return {"id": fid, "display_name": name, "filename": name, "folder_id": folder, "content-type": ctype,
            "size": len(_body(fid)), "url": f"{BASE}/files/{fid}/download?verifier=x"}


def _body(fid):
    return f"%PDF-1.4 fake {fid}".encode()


COURSES = [
    {"id": 21, "course_code": "PPE101", "name": "Introduction to Philosophy", "term": {"name": "MT26", "end_at": SOON}},
    {"id": 22, "course_code": "HIST2", "name": "Modern History", "term": {"name": "MT26"}},
    {"id": 9, "course_code": "OLD", "name": "Last year", "term": {"name": "TT25", "end_at": "2025-06-01T00:00:00Z"}},
]


class FakeCanvas(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _send(self, status, body=b"", ctype="application/json; charset=utf-8", headers=None):
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        for k, v in (headers or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        url = urllib.parse.urlparse(self.path)
        path, q = url.path, urllib.parse.parse_qs(url.query)
        by_token = self.headers.get("Authorization") == "Bearer tok"
        by_cookie = "canvas_session=good" in (self.headers.get("Cookie") or "")
        if path.startswith("/files/"):
            fid = int(path.split("/")[2])
            return self._send(200, _body(fid), "application/pdf")
        if not (by_token or by_cookie):
            return self._send(401, b'{"status":"unauthenticated"}')

        def ok(data, headers=None):
            raw = json.dumps(data).encode()
            self._send(200, raw if by_token else b"while(1);" + raw, headers=headers)

        files21 = [_file(101, "Lecture 1.pdf"), _file(102, "Reading.pdf", 2), _file(103, "Notes.docx", 1, "application/msword")]
        routes = {
            "/api/v1/users/self": {"id": 1, "name": "Test Student"},
            "/api/v1/courses/21/modules": [{"name": "Week 1", "items": [
                {"type": "File", "title": "Lecture 1", "content_id": 101, "html_url": "x"},
                {"type": "Assignment", "title": "Essay 1", "content_details": {"due_at": SOON}}]}],
            "/api/v1/courses/21/files": files21,
            "/api/v1/courses/21/folders": [{"id": 1, "full_name": "course files"}, {"id": 2, "full_name": "course files/Readings"}],
            "/api/v1/courses/22/modules": [{"name": "Week 1: Revolutions", "items": [{"type": "File", "content_id": 201}]}],
            "/api/v1/courses/22/files/201": _file(201, "Slides: 1789.pdf"),
            "/api/v1/courses/21/files/101": files21[0],
            "/api/v1/planner/items": [{"plannable_type": "assignment", "context_name": "PPE101", "html_url": "/courses/21/assignments/5",
                                       "plannable": {"title": "Essay 1", "due_at": SOON}, "submissions": {"submitted": False}}],
            "/api/v1/announcements": [{"title": "Room change", "context_code": "course_21", "posted_at": SOON,
                                       "message": "<p>Lecture moves to <b>LT1</b></p>", "html_url": "y"}],
        }
        if path == "/api/v1/courses":  # two pages, to exercise Link pagination
            if q.get("page") == ["2"]:
                return ok(COURSES[1:])
            return ok(COURSES[:1], {"Link": f'<{BASE}/api/v1/courses?page=2&per_page=100>; rel="next"'})
        if path == "/api/v1/courses/22/files":
            return self._send(403, b'{"status":"unauthorized"}')
        if path in routes:
            return ok(routes[path])
        self._send(404, b"{}")


SERVER = HTTPServer(("127.0.0.1", 0), FakeCanvas)
BASE = f"http://127.0.0.1:{SERVER.server_port}"
threading.Thread(target=SERVER.serve_forever, daemon=True).start()

HOME = TMP / "home"
HOME.mkdir()
(TMP / "slidemate").mkdir()
(TMP / "slidemate" / "config.json").write_text(json.dumps({"library_roots": [str(LIBRARY)]}))
os.environ.update(CANVAS_BASE_URL=BASE, CANVAS_MCP_HOME=str(HOME), SLIDEMATE_DATA=str(TMP / "slidemate"))
for k in ("CANVAS_TOKEN", "CANVAS_DOWNLOAD_DIR"):
    os.environ.pop(k, None)


def _session(value):
    (HOME / "session.json").write_text(json.dumps({"cookies": [
        {"name": "canvas_session", "value": value, "domain": "127.0.0.1", "path": "/"}]}))


from canvas_mcp import server  # noqa: E402  (reads the settings above)


def _sync_all():
    rep = anyio.run(server.canvas_sync)
    while rep.get("running"):
        time.sleep(0.1)
        rep = anyio.run(server.canvas_sync_status)
    return rep


def test_downloads_go_to_slidemate_library():
    assert server._settings.download_dir == LIBRARY


def test_courses_follow_pagination_and_skip_past_terms():
    _session("good")
    names = [c["code"] for c in anyio.run(server.canvas_courses)]
    assert names == ["PPE101", "HIST2"]


def test_sync_every_current_course_pdfs_only():
    _session("good")
    rep = _sync_all()
    files = sorted(str(p.relative_to(LIBRARY)) for p in LIBRARY.rglob("*") if p.is_file())
    # PPE101: module file under the module's name, the rest of Files under its folder; HIST2 hides Files from
    # students, so its module file is fetched by id. The past course is skipped.
    assert files == ["HIST2/Week 1- Revolutions/Slides- 1789.pdf", "PPE101/Readings/Reading.pdf", "PPE101/Week 1/Lecture 1.pdf"]
    assert rep["downloaded"] == 3 and "2 courses" in rep["summary"] and not rep["errors"]
    assert _sync_all()["downloaded"] == 0  # a second run skips what's there


def test_one_course_gets_every_file():
    _session("good")
    rep = anyio.run(server.canvas_sync, "philosophy")
    assert (LIBRARY / "PPE101" / "Notes.docx").exists() and "summary" in rep


def test_deadlines_announcements_and_browse():
    _session("good")
    d = anyio.run(server.canvas_deadlines)
    assert d[0]["title"] == "Essay 1" and d[0]["submitted"] is False and d[0]["url"].endswith("/courses/21/assignments/5")
    a = anyio.run(server.canvas_announcements)
    assert a[0]["message"] == "Lecture moves to LT1" and a[0]["course"] == "PPE101"
    b = anyio.run(server.canvas_browse, "PPE101")
    items = b["modules"][0]["items"]
    assert items[0]["file_id"] == 101 and items[1]["due"]


def test_expired_session_is_reported():
    _session("expired")
    assert _sync_all().get("login_required") is True
    assert anyio.run(server.canvas_courses).get("login_required") is True
    _session("good")


def test_access_token_works_without_a_session():
    (HOME / "session.json").unlink(missing_ok=True)
    server._settings.token = "tok"
    try:
        assert anyio.run(server.canvas_status)["signed_in_as"] == "Test Student"
    finally:
        server._settings.token = ""
        _session("good")


def test_stdio_lists_tools_and_keeps_stdout_clean():
    p = subprocess.Popen([sys.executable, "-m", "canvas_mcp.cli", "serve"], stdin=subprocess.PIPE,
                         stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True)
    try:
        def rpc(mid, method, params=None):
            p.stdin.write(json.dumps({"jsonrpc": "2.0", "id": mid, "method": method, "params": params or {}}) + "\n")
            p.stdin.flush()
            return json.loads(p.stdout.readline())  # fails if anything but JSON-RPC reaches stdout
        rpc(1, "initialize", {"protocolVersion": "2025-06-18", "capabilities": {},
                              "clientInfo": {"name": "test", "version": "0"}})
        p.stdin.write(json.dumps({"jsonrpc": "2.0", "method": "notifications/initialized"}) + "\n")
        names = {t["name"] for t in rpc(2, "tools/list")["result"]["tools"]}
        assert {"canvas_sync", "canvas_sync_status", "canvas_login", "canvas_deadlines", "canvas_announcements"} <= names
    finally:
        p.kill()


def test_login_with_a_working_session_needs_no_window():
    _session("good")
    res = anyio.run(server.canvas_login)
    assert res["ok"] and res["how"] == "already signed in"
