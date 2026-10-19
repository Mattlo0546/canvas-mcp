"""A thin client over the Canvas LMS REST API (/api/v1).

Two ways in, tried in this order:
  1. An access token (CANVAS_TOKEN), sent as `Authorization: Bearer …`.
  2. The browser session saved by `canvas-mcp login` (auth.py): the same cookies the Canvas website uses.
     Canvas prefixes cookie-authenticated JSON with `while(1);` (a JSON-hijacking guard), which is stripped here.
Lists are paginated with `Link: <…>; rel="next"` headers, which `get_all` follows.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import httpx

from .config import Settings


class LoginRequired(RuntimeError):
    """Raised when there's no session or token, or Canvas rejects it."""

    def __init__(self, msg: str = ""):
        super().__init__(
            msg
            or "Not signed in to Canvas (or the session expired). Run the `canvas_login` tool (or `canvas-mcp login` "
            "in a terminal) and complete the university sign-in in the window that opens."
        )


class CanvasError(RuntimeError):
    """An API call failed for a reason other than sign-in."""


_NEXT = re.compile(r'<([^>]+)>;\s*rel="next"')


def load_session(settings: Settings) -> list[dict]:
    try:
        return json.loads(settings.session_path.read_text()).get("cookies") or []
    except (OSError, ValueError):
        return []


class Canvas:
    def __init__(self, settings: Settings, token: str | None = None, cookies: list[dict] | None = None):
        self.settings = settings
        self.token = settings.token if token is None else token
        headers = {"User-Agent": "canvas-mcp/0.1", "Accept": "application/json"}
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        jar = httpx.Cookies()
        if not self.token:
            for c in load_session(settings) if cookies is None else cookies:
                jar.set(c["name"], c["value"], domain=c.get("domain", ""), path=c.get("path", "/"))
            if not jar:
                raise LoginRequired()
        self._client = httpx.Client(timeout=60.0, follow_redirects=True, headers=headers, cookies=jar)

    def _url(self, path: str) -> str:
        return path if path.startswith("http") else f"{self.settings.base_url}/api/v1/{path.lstrip('/')}"

    def _get(self, path: str, params: Any = None) -> httpx.Response:
        r = self._client.get(self._url(path), params=params)
        # A lapsed browser session redirects to the SSO login page instead of returning 401.
        if r.status_code == 401 or (r.status_code == 200 and "json" not in r.headers.get("content-type", "")):
            raise LoginRequired()
        if r.status_code == 403:
            raise CanvasError(f"Canvas says you don't have access to {path} (403).")
        if r.status_code == 404:
            raise CanvasError(f"Not found on Canvas: {path}")
        if r.status_code >= 400:
            raise CanvasError(f"{path}: Canvas returned {r.status_code}")
        return r

    @staticmethod
    def _json(r: httpx.Response) -> Any:
        text = r.text
        if text.startswith("while(1);"):
            text = text[len("while(1);"):]
        return json.loads(text) if text.strip() else None

    def get(self, path: str, **params: Any) -> Any:
        return self._json(self._get(path, params or None))

    def get_all(self, path: str, limit: int = 2000, **params: Any) -> list:
        params.setdefault("per_page", 100)
        out: list = []
        r = self._get(path, params)
        while True:
            page = self._json(r) or []
            out += page if isinstance(page, list) else [page]
            m = _NEXT.search(r.headers.get("link", ""))
            if not m or len(out) >= limit:
                return out[:limit]
            r = self._get(m.group(1))

    # --- high-level helpers ---
    def me(self) -> dict:
        return self.get("users/self")

    def courses(self) -> list[dict]:
        """Courses the user is actively enrolled in, with their term (for start/end dates)."""
        return self.get_all("courses", enrollment_state="active", **{"include[]": ["term"]})

    def modules(self, course_id: int) -> list[dict]:
        return self.get_all(f"courses/{course_id}/modules", **{"include[]": ["items"]})

    def files(self, course_id: int) -> list[dict]:
        """Every file in the course's Files area. Many courses hide it from students: then this raises CanvasError."""
        return self.get_all(f"courses/{course_id}/files")

    def folders(self, course_id: int) -> dict[int, str]:
        return {f["id"]: f.get("full_name") or "" for f in self.get_all(f"courses/{course_id}/folders")}

    def file(self, course_id: int, file_id: int) -> dict:
        return self.get(f"courses/{course_id}/files/{file_id}")

    def planner(self, start: str, end: str | None = None) -> list[dict]:
        """To-dos with due dates (assignments, quizzes, discussions), from the student planner."""
        p = {"start_date": start}
        if end:
            p["end_date"] = end
        return self.get_all("planner/items", limit=200, **p)

    def announcements(self, course_ids: list[int], start: str) -> list[dict]:
        return self.get_all("announcements", limit=100, start_date=start, active_only="true",
                            **{"context_codes[]": [f"course_{c}" for c in course_ids]})

    def download(self, url: str, dest: Path) -> int:
        """Stream a file to `dest` (Canvas redirects to its file store, which needs no sign-in); returns bytes."""
        dest.parent.mkdir(parents=True, exist_ok=True)
        tmp = dest.with_name(dest.name + ".part")
        written = 0
        with self._client.stream("GET", url) as r:
            if r.status_code in (401, 403):
                raise LoginRequired()
            r.raise_for_status()
            with tmp.open("wb") as fh:
                for chunk in r.iter_bytes():
                    fh.write(chunk)
                    written += len(chunk)
        tmp.replace(dest)
        return written

    def find_course(self, course: str) -> dict:
        """Resolve a course by id, course code, or a substring of its name."""
        courses = self.courses()
        q = str(course).strip().lower()
        for test in (lambda c: str(c.get("id")) == q,
                     lambda c: (c.get("course_code") or "").lower() == q,
                     lambda c: q in (c.get("name") or "").lower() or q in (c.get("course_code") or "").lower()):
            for c in courses:
                if test(c):
                    return c
        raise CanvasError(f"No current course matches {course!r}.")
