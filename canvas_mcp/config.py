"""Settings, read from ~/.canvas-mcp/config.json and environment variables.

Environment variables win over the file, so the MCP client config can override anything without editing files.
Nothing here is Oxford-specific except the default base URL: point CANVAS_BASE_URL at any Canvas site.
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path

HOME_DIR = Path(os.environ.get("CANVAS_MCP_HOME", Path.home() / ".canvas-mcp")).expanduser()


@dataclass
class Settings:
    # Oxford's Canvas by default; override with CANVAS_BASE_URL for any other site.
    base_url: str = "https://canvas.ox.ac.uk"
    # A Canvas access token (Account → Settings → New access token), if your university allows them. Without one,
    # sign-in goes through the university's SSO in a browser window and the session is reused.
    token: str = ""
    # Where downloaded files land: <root>/<course code>/<module>/<file>. Unless set, that's SlideMate's library (its
    # first slides folder), so synced slides show up there; without SlideMate, ~/CanvasFiles.
    download_dir: Path | None = None
    # The installed Google Chrome is used for the sign-in window; "" = Playwright's bundled Chromium.
    browser_channel: str = "chrome"
    home: Path = HOME_DIR

    @property
    def session_path(self) -> Path:
        return self.home / "session.json"

    @property
    def profile_dir(self) -> Path:
        return self.home / "browser-profile"


def slidemate_library() -> Path | None:
    """The first slides folder in SlideMate's settings, if SlideMate is set up on this Mac."""
    data = Path(os.environ.get("SLIDEMATE_DATA") or Path.home() / "Library/Application Support/SlideMate")
    try:
        roots = json.loads((data / "config.json").read_text()).get("library_roots") or []
    except (OSError, ValueError):
        return None
    return next((Path(r).expanduser() for r in roots if r), None)


def load_settings() -> Settings:
    s = Settings()
    cfg_path = HOME_DIR / "config.json"
    if cfg_path.exists():
        for key, value in json.loads(cfg_path.read_text()).items():
            if key == "download_dir":
                s.download_dir = Path(value).expanduser()
            elif hasattr(s, key):
                setattr(s, key, value)

    env = os.environ
    if env.get("CANVAS_BASE_URL"):
        s.base_url = env["CANVAS_BASE_URL"]
    if env.get("CANVAS_TOKEN"):
        s.token = env["CANVAS_TOKEN"]
    if env.get("CANVAS_DOWNLOAD_DIR"):
        s.download_dir = Path(env["CANVAS_DOWNLOAD_DIR"]).expanduser()
    if env.get("CANVAS_BROWSER_CHANNEL") is not None:
        s.browser_channel = env["CANVAS_BROWSER_CHANNEL"]

    s.base_url = s.base_url.rstrip("/")
    if "://" not in s.base_url:
        s.base_url = "https://" + s.base_url
    if s.download_dir is None:
        s.download_dir = slidemate_library() or Path.home() / "CanvasFiles"
    s.home.mkdir(parents=True, exist_ok=True)
    return s
