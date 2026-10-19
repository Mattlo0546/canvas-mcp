"""MCP server exposing a Canvas LMS site (Oxford by default) to AI assistants."""
from __future__ import annotations

import json
import re
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path

import anyio
from mcp.server.fastmcp import FastMCP

from . import relevance
from .auth import browser_login
from .canvas import Canvas, CanvasError, LoginRequired
from .config import load_settings

mcp = FastMCP(
    "canvas",
    instructions=(
        "Tools for the user's Canvas LMS (University of Oxford by default; CANVAS_BASE_URL sets another site). "
        "canvas_courses lists current courses; canvas_browse shows a course's modules with files, pages and "
        "assignments; canvas_deadlines lists what's due soon; canvas_announcements shows recent course announcements; "
        "canvas_download / canvas_sync save files locally (canvas_sync with no course pulls every current course's "
        "PDFs in the background, skipping guidance sites, posters and forms; check canvas_sync_status; "
        "canvas_set_courses changes which courses it pulls). If a tool reports that sign-in is needed, call "
        "canvas_login, which opens a browser window for the university SSO + MFA."
    ),
)

_settings = load_settings()


def _silent_refresh() -> bool:
    """Sign back in headlessly with the saved browser profile (works while the university SSO session is valid)."""
    if _settings.token or not any(_settings.profile_dir.glob("*")):
        return False
    try:
        return bool(browser_login(_settings, headless=True).get("ok"))
    except Exception:
        return False


def _with_canvas(fn):
    """Run fn(canvas); if the session has lapsed, refresh it silently once and try again."""
    try:
        return fn(Canvas(_settings))
    except LoginRequired:
        if not _silent_refresh():
            raise
        return fn(Canvas(_settings))


async def _run(fn):
    try:
        return await anyio.to_thread.run_sync(lambda: _with_canvas(fn))
    except LoginRequired as e:
        return {"login_required": True, "message": str(e)}
    except CanvasError as e:
        return {"error": str(e)}


def _text(html: str | None, limit: int = 500) -> str | None:
    if not html:
        return None
    try:
        from bs4 import BeautifulSoup
        s = BeautifulSoup(html, "html.parser").get_text(" ", strip=True)
    except Exception:
        s = re.sub(r"<[^>]+>", " ", html).strip()
    return s[:limit] or None


def _when(iso: str | None) -> str | None:
    if not iso:
        return None
    try:
        return datetime.fromisoformat(iso.replace("Z", "+00:00")).astimezone().strftime("%Y-%m-%d %H:%M")
    except ValueError:
        return iso


def _iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _abs(url: str | None) -> str | None:
    return f"{_settings.base_url}{url}" if url and url.startswith("/") else url


def _safe(name: str) -> str:
    return re.sub(r'[/\\:*?"<>|]', "-", name or "").strip(" .") or "untitled"


def _folder(c: dict) -> str:
    return _safe(c.get("course_code") or c.get("name") or str(c["id"]))


def _current(c: dict, now: datetime) -> bool:
    """Skip courses that have ended (by course or term dates) or that Canvas only lists by name."""
    if c.get("access_restricted_by_date") or c.get("workflow_state") == "deleted":
        return False
    for end in (c.get("end_at"), (c.get("term") or {}).get("end_at")):
        if end and datetime.fromisoformat(end.replace("Z", "+00:00")) < now:
            return False
    return True


@mcp.tool()
async def canvas_login(timeout_seconds: int = 300) -> dict:
    """Sign in to Canvas. Opens a Chrome window on the user's computer at the university sign-in page; the user
    completes SSO + MFA there and the session is saved for the other tools. Tries a silent refresh first, so it often
    finishes without any window."""
    def go():
        try:  # the token or saved session still works: nothing to do
            me = Canvas(_settings).me()
            return {"ok": True, "name": me.get("name"), "how": "access token" if _settings.token else "already signed in"}
        except (LoginRequired, CanvasError):
            pass
        res = browser_login(_settings, headless=True)
        if res.get("ok"):
            return {**res, "how": "refreshed silently"}
        return {**browser_login(_settings, headless=False, timeout_s=timeout_seconds), "how": "interactive sign-in"}
    try:
        return await anyio.to_thread.run_sync(go)
    except Exception as e:  # noqa: BLE001 - e.g. no browser could be opened
        return {"ok": False, "reason": str(e)}


@mcp.tool()
async def canvas_status() -> dict:
    """Check the Canvas session: which site, signed in as whom, and the download folder."""
    def go(cv: Canvas):
        me = cv.me()
        return {"base_url": _settings.base_url, "signed_in_as": me.get("name"), "user_id": me.get("id"),
                "auth": "access token" if _settings.token else "browser session",
                "download_dir": str(_settings.download_dir)}
    return await _run(go)


def _prefs_path() -> Path:
    return _settings.home / "courses.json"


def _prefs() -> dict:
    try:
        return json.loads(_prefs_path().read_text())
    except (OSError, ValueError):
        return {}


def _info(c: dict) -> dict:
    """The fields relevance.choose looks at."""
    return {"id": c["id"], "name": c.get("name") or "", "shortname": c.get("course_code") or "",
            "idnumber": c.get("sis_course_id") or "", "students": c.get("total_students") or 0, "raw": c}


def _choose(courses: list[dict]) -> tuple[list[dict], list[dict]]:
    keep, skipped = relevance.choose([_info(c) for c in courses], _prefs())
    return [k["raw"] for k in keep], skipped


@mcp.tool()
async def canvas_courses(include_past: bool = False) -> list[dict] | dict:
    """List the user's Canvas courses (current ones, unless include_past). `synced` says whether a full canvas_sync
    pulls it; `why_not` explains a course it skips (an info site, ended, or turned off)."""
    def go(cv: Canvas):
        now = datetime.now(timezone.utc)
        cs = cv.courses()
        _, skipped = _choose([c for c in cs if _current(c, now)])
        why = {s["id"]: s["why"] for s in skipped}
        return [{"id": c["id"], "code": c.get("course_code"), "name": c.get("name"),
                 "term": (c.get("term") or {}).get("name"), "url": f"{_settings.base_url}/courses/{c['id']}",
                 "synced": _current(c, now) and c["id"] not in why,
                 "why_not": why.get(c["id"]) or ("" if _current(c, now) else "ended")}
                for c in cs if include_past or _current(c, now)]
    return await _run(go)


@mcp.tool()
async def canvas_set_courses(include: list[str] | None = None, exclude: list[str] | None = None) -> dict:
    """Choose which courses a full canvas_sync pulls, overriding its guess. `include`: course ids (or codes or
    names) to pull even though they look like an info site; `exclude`: ones to stop pulling. Saved for every later
    sync. Passing a course in one list removes it from the other."""
    def go(cv: Canvas):
        prefs = _prefs()
        inc, exc = set(map(str, prefs.get("include") or [])), set(map(str, prefs.get("exclude") or []))
        for q in include or []:
            cid = str(cv.find_course(q)["id"])
            inc.add(cid)
            exc.discard(cid)
        for q in exclude or []:
            cid = str(cv.find_course(q)["id"])
            exc.add(cid)
            inc.discard(cid)
        _prefs_path().write_text(json.dumps({"include": sorted(inc), "exclude": sorted(exc)}, indent=1))
        return {"ok": True, "include": sorted(inc), "exclude": sorted(exc)}
    return await _run(go)


@mcp.tool()
async def canvas_browse(course: str) -> dict:
    """Show a course's modules with their files, pages, links and assignments (with due dates). `course` can be a
    course id, course code, or part of the name. File items include a `file_id` for canvas_download."""
    def go(cv: Canvas):
        c = cv.find_course(course)
        modules = []
        for m in cv.modules(c["id"]):
            items = []
            for it in m.get("items") or []:
                item = {"title": it.get("title"), "type": it.get("type"), "url": it.get("html_url") or it.get("external_url")}
                if it.get("type") == "File":
                    item["file_id"] = it.get("content_id")
                due = (it.get("content_details") or {}).get("due_at")
                if due:
                    item["due"] = _when(due)
                items.append({k: v for k, v in item.items() if v})
            modules.append({"module": m.get("name"), "items": items})
        return {"course": c.get("course_code") or c.get("name"), "id": c["id"], "modules": modules}
    return await _run(go)


@mcp.tool()
async def canvas_deadlines(days: int = 14) -> list[dict] | dict:
    """Assignments, quizzes and discussions due in the next `days` days (default 14), soonest first, with whether
    each has been submitted."""
    def go(cv: Canvas):
        now = datetime.now(timezone.utc)
        out = []
        for p in cv.planner(_iso(now), _iso(now + timedelta(days=days))):
            pl = p.get("plannable") or {}
            subs = p.get("submissions")
            out.append({k: v for k, v in {
                "title": pl.get("title") or pl.get("name"),
                "course": p.get("context_name"),
                "type": p.get("plannable_type"),
                "due": _when(pl.get("due_at") or p.get("plannable_date")),
                "submitted": subs.get("submitted") if isinstance(subs, dict) else None,
                "url": _abs(p.get("html_url")),
            }.items() if v is not None})
        return sorted(out, key=lambda d: d.get("due") or "")
    return await _run(go)


@mcp.tool()
async def canvas_announcements(course: str = "", days: int = 14) -> list[dict] | dict:
    """Announcements posted in the last `days` days, newest first: in one course (id, code or part of the name), or
    in every current course when `course` is empty."""
    def go(cv: Canvas):
        now = datetime.now(timezone.utc)
        courses = [cv.find_course(course)] if course else [c for c in cv.courses() if _current(c, now)]
        names = {f"course_{c['id']}": c.get("course_code") or c.get("name") for c in courses}
        if not courses:
            return []
        out = [{"title": a.get("title"), "course": names.get(a.get("context_code")), "posted": _when(a.get("posted_at")),
                "message": _text(a.get("message")), "url": a.get("html_url")}
               for a in cv.announcements([c["id"] for c in courses], _iso(now - timedelta(days=days)))]
        return sorted(out, key=lambda d: d.get("posted") or "", reverse=True)
    return await _run(go)


@mcp.tool()
async def canvas_download(course: str, file_id: int, subdir: str = "") -> dict:
    """Download one Canvas file (a `file_id` from canvas_browse) into <download folder>/<course>/ (or `subdir`)."""
    def go(cv: Canvas):
        c = cv.find_course(course)
        f = cv.file(c["id"], file_id)
        dest = _settings.download_dir / (subdir or _folder(c)) / _safe(f.get("display_name") or f.get("filename"))
        return {"saved": str(dest), "bytes": cv.download(f["url"], dest)}
    return await _run(go)


def _course_files(cv: Canvas, c: dict, study_only: bool = False) -> tuple[list[tuple[dict, str]], int]:
    """(file, folder inside the course) pairs: files linked from modules, filed under the module's name, then anything
    else in the course's Files area (when students can see it), filed under its folder. With `study_only`, leaves out
    admin modules and folders ("Student support") and files that aren't for studying (posters, handbooks, forms),
    and also returns how many such files it left out."""
    by_id: dict[int, dict] = {}
    folders: dict[int, str] = {}
    try:
        by_id = {f["id"]: f for f in cv.files(c["id"])}
        folders = cv.folders(c["id"])
    except CanvasError:
        pass  # Files hidden from students: fetch each module file by id instead
    out, seen, noise = [], set(), 0
    for m in cv.modules(c["id"]):
        admin = study_only and not relevance.is_study_section(m.get("name"))
        for it in m.get("items") or []:
            fid = it.get("content_id")
            if it.get("type") != "File" or not fid or fid in seen:
                continue
            seen.add(fid)
            if admin:
                continue
            if study_only and not relevance.is_study_file(it.get("title")):
                noise += 1  # a poster, handbook or form
                continue
            try:
                f = by_id.get(fid) or cv.file(c["id"], fid)
            except CanvasError:
                continue  # locked or unpublished
            if study_only and not relevance.is_study_file(f.get("display_name") or f.get("filename")):
                noise += 1
                continue
            out.append((f, _safe(m.get("name") or "")))
    for fid, f in by_id.items():
        if fid in seen:
            continue
        path = re.sub(r"^course files/?", "", folders.get(f.get("folder_id"), ""))
        parts = [p for p in path.split("/") if p]
        if study_only and not all(relevance.is_study_section(p) for p in parts):
            continue
        if study_only and not relevance.is_study_file(f.get("display_name") or f.get("filename"), *parts):
            noise += 1
            continue
        out.append((f, "/".join(_safe(p) for p in parts)))
    return out, noise


def _is_pdf(f: dict) -> bool:
    return (f.get("content-type") or "").endswith("/pdf") or (f.get("display_name") or f.get("filename") or "").lower().endswith(".pdf")


def _sync_course(cv: Canvas, c: dict, *, skip_existing: bool, pdfs_only: bool) -> dict:
    root = _settings.download_dir / _folder(c)
    downloaded, skipped, errors = [], 0, []
    files, noise = _course_files(cv, c, study_only=pdfs_only)
    for f, sub in files:
        if f.get("locked_for_user") or not f.get("url") or (pdfs_only and not _is_pdf(f)):
            continue
        dest = root / sub / _safe(f.get("display_name") or f.get("filename"))
        if skip_existing and dest.exists() and dest.stat().st_size == (f.get("size") or 0):
            skipped += 1
            continue
        try:
            cv.download(f["url"], dest)
            downloaded.append(str(dest))
        except LoginRequired:
            raise
        except Exception as e:  # noqa: BLE001 - report per file, keep going
            errors.append(f"{dest.name}: {e}")
    return {"course": _folder(c), "folder": str(root), "downloaded": len(downloaded), "skipped": skipped,
            "not_study": noise, "files": downloaded, "errors": errors}


# A sync of every course runs in the background (it can take a while); canvas_sync_status reports on it.
_job: dict = {"running": False}
_job_lock = threading.Lock()


def _sync_all(skip_existing: bool) -> None:
    def go(cv: Canvas):
        now = datetime.now(timezone.utc)
        courses, passed = _choose([c for c in cv.courses() if _current(c, now)])
        reports = []
        for i, c in enumerate(courses, 1):
            _job["progress"] = f"Course {i} of {len(courses)}: {_folder(c)}…"
            try:
                reports.append(_sync_course(cv, c, skip_existing=skip_existing, pdfs_only=True))
            except CanvasError as e:  # one course failing (e.g. no access) shouldn't stop the rest
                reports.append({"course": _folder(c), "downloaded": 0, "skipped": 0, "files": [], "errors": [str(e)]})
        return courses, passed, reports
    try:
        courses, passed, reports = _with_canvas(go)
        new = sum(r["downloaded"] for r in reports)
        noise = sum(r.get("not_study", 0) for r in reports)
        errors = [f"{r['course']}: {e}" for r in reports for e in r["errors"]]
        where = str(_settings.download_dir).replace(str(Path.home()), "~", 1)
        summary = (f"{new} new PDF{'s' if new != 1 else ''} from {len(courses)} course{'s' if len(courses) != 1 else ''}"
                   f" into {where}" + (f" ({len(errors)} couldn't be downloaded)" if errors else "") + "."
                   + (f" Skipped {len(passed)} site{'s' if len(passed) != 1 else ''} that aren't courses"
                      f" ({', '.join(p['name'] for p in passed[:3])}{'…' if len(passed) > 3 else ''})." if passed else ""))
        _job.update(report={"summary": summary, "folder": str(_settings.download_dir), "downloaded": new,
                            "courses": reports, "errors": errors, "not_study_files": noise,
                            "skipped_courses": [{"id": p["id"], "name": p["name"], "why": p["why"]} for p in passed]})
    except LoginRequired as e:
        _job.update(report={"login_required": True, "message": str(e)})
    except Exception as e:  # noqa: BLE001 - surfaced through canvas_sync_status
        _job.update(report={"error": str(e)})
    finally:
        _job["running"] = False


def _status() -> dict:
    if _job["running"]:
        return {"running": True, "progress": _job.get("progress", "Starting…")}
    return _job.get("report") or {"error": "No sync has run yet. Call canvas_sync first."}


@mcp.tool()
async def canvas_sync(course: str = "", skip_existing: bool = True) -> dict:
    """Download course files to <download folder>/<course code>/<module>/ (SlideMate's library if it's set up, else
    ~/CanvasFiles).

    With a `course` (id, code or part of the name), downloads every file in it and returns the result. Without one,
    downloads the PDFs (lecture slides, handouts, readings) from every current course in the background, skipping
    sites that aren't courses and files that aren't for studying (posters, handbooks, forms), and returns
    {"running": true}; call canvas_sync_status until it reports the result. Files already there are skipped."""
    if course:
        def go(cv: Canvas):
            r = _sync_course(cv, cv.find_course(course), skip_existing=skip_existing, pdfs_only=False)
            r["summary"] = f"{r['downloaded']} new file{'s' if r['downloaded'] != 1 else ''} in {r['folder']}."
            return r
        return await _run(go)
    with _job_lock:
        if not _job["running"]:
            _job.clear()
            _job.update(running=True, progress="Finding your courses…")
            threading.Thread(target=_sync_all, args=(skip_existing,), daemon=True).start()
    return _status()


@mcp.tool()
async def canvas_sync_status() -> dict:
    """Progress of a sync started by canvas_sync without a course: {"running": true, "progress": …} while it runs,
    then the result (a summary, files per course and any errors)."""
    return _status()


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()
