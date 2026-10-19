"""Signing in to Canvas through the university's single sign-on.

Most universities put Canvas behind SAML/Shibboleth SSO with MFA, and many don't let students create access tokens,
so there's no password or key a script can use. Instead we open the Canvas site in a real browser window, the user
signs in as they normally would, and we wait until the Canvas API answers `/api/v1/users/self`. Then the session
cookies for the Canvas site are saved (readable only by you) and reused by the API client. The browser profile
remembers the SSO session, so when the Canvas session lapses a headless refresh usually signs back in with no clicks.
"""
from __future__ import annotations

import json
import time
from urllib.parse import urlparse

from .config import Settings

DESKTOP_UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) "
              "Chrome/154.0.0.0 Safari/537.36")


def save_session(settings: Settings, cookies: list[dict], user: dict) -> None:
    p = settings.session_path
    p.write_text(json.dumps({"saved": time.time(), "base_url": settings.base_url,
                             "user": {"id": user.get("id"), "name": user.get("name")}, "cookies": cookies}, indent=1))
    p.chmod(0o600)


def _for_host(domain: str, host: str) -> bool:
    """Whether a cookie for `domain` is sent to `host` (only the Canvas site's cookies are kept, not the SSO's)."""
    d = domain.lstrip(".")
    return bool(d) and (host == d or host.endswith("." + d))


def _launch(pw, settings: Settings, headless: bool):
    settings.profile_dir.mkdir(parents=True, exist_ok=True)
    kwargs = dict(user_data_dir=str(settings.profile_dir), headless=headless, viewport={"width": 1100, "height": 820})
    if headless:
        kwargs["user_agent"] = DESKTOP_UA
    if settings.browser_channel:
        try:
            return pw.chromium.launch_persistent_context(channel=settings.browser_channel, **kwargs)
        except Exception:
            pass  # Chrome not installed -> fall back to Playwright's bundled Chromium
    return pw.chromium.launch_persistent_context(**kwargs)


def _signed_in(ctx, settings: Settings) -> dict | None:
    try:
        r = ctx.request.get(f"{settings.base_url}/api/v1/users/self", headers={"Accept": "application/json"},
                            max_redirects=0)
        if r.status != 200:
            return None
        text = r.text()
        return json.loads(text[len("while(1);"):] if text.startswith("while(1);") else text)
    except Exception:
        return None


def browser_login(settings: Settings, *, headless: bool = False, timeout_s: int = 300) -> dict:
    """Open Canvas in a browser window and wait until the user is signed in.

    headless=True is the silent refresh: it only works if the SSO session saved in the browser profile is still valid.
    """
    from playwright.sync_api import sync_playwright

    host = urlparse(settings.base_url).hostname or ""
    deadline = time.time() + (45 if headless else timeout_s)
    with sync_playwright() as pw:
        ctx = _launch(pw, settings, headless)
        try:
            page = ctx.pages[0] if ctx.pages else ctx.new_page()
            try:
                page.goto(f"{settings.base_url}/login", wait_until="domcontentloaded")
            except Exception:
                pass
            if not headless:
                try:
                    page.bring_to_front()
                except Exception:
                    pass
            user = None
            while time.time() < deadline:
                user = _signed_in(ctx, settings)
                if user:
                    break
                page.wait_for_timeout(1500)
            if not user:
                return {"ok": False, "reason": "timed out waiting for sign-in"}
            cookies = [{k: c[k] for k in ("name", "value", "domain", "path")} for c in ctx.cookies()
                       if _for_host(c.get("domain") or "", host)]
            save_session(settings, cookies, user)
            return {"ok": True, "name": user.get("name"), "site": settings.base_url}
        finally:
            ctx.close()
