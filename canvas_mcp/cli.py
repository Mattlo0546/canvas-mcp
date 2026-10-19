"""Command line: `canvas-mcp login | status | courses | deadlines | sync | serve`."""
from __future__ import annotations

import argparse
import json
import sys
import time

import anyio

from .auth import browser_login
from .config import load_settings


def _print(res) -> int:
    print(json.dumps(res, indent=1, ensure_ascii=False))
    return 2 if isinstance(res, dict) and res.get("login_required") else 1 if isinstance(res, dict) and res.get("error") else 0


def cmd_login(args) -> int:
    s = load_settings()
    print(f"Opening a browser window. Sign in to {s.base_url} with your university account…")
    res = browser_login(s, headless=False, timeout_s=args.timeout)
    print(json.dumps(res, indent=1))
    return 0 if res.get("ok") else 1


def cmd_tool(name):
    def run(args) -> int:
        from . import server
        return _print(anyio.run(getattr(server, name)))
    return run


def cmd_sync(args) -> int:
    from . import server
    rep = anyio.run(server.canvas_sync, args.course or "")
    last = None
    while rep.get("running"):  # every course: follow the background job
        if rep.get("progress") != last:
            print(rep.get("progress"), flush=True)
            last = rep.get("progress")
        time.sleep(1)
        rep = anyio.run(server.canvas_sync_status)
    return _print(rep)


def main() -> None:
    p = argparse.ArgumentParser(prog="canvas-mcp", description="Canvas LMS MCP server")
    sub = p.add_subparsers(dest="cmd")
    sp = sub.add_parser("login", help="sign in (opens a browser window)")
    sp.add_argument("--timeout", type=int, default=300)
    sp.set_defaults(fn=cmd_login)
    sub.add_parser("status", help="who you're signed in as").set_defaults(fn=cmd_tool("canvas_status"))
    sub.add_parser("courses", help="your current courses").set_defaults(fn=cmd_tool("canvas_courses"))
    sub.add_parser("deadlines", help="what's due in the next 14 days").set_defaults(fn=cmd_tool("canvas_deadlines"))
    sp = sub.add_parser("sync", help="download PDFs from every current course, or every file in one course")
    sp.add_argument("course", nargs="?")
    sp.set_defaults(fn=cmd_sync)
    sub.add_parser("serve", help="run the MCP server over stdio (the default)")
    args = p.parse_args()
    if args.cmd in (None, "serve"):
        from .server import main as serve
        serve()
        return
    sys.exit(args.fn(args))


if __name__ == "__main__":
    main()
