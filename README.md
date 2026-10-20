# Canvas MCP Server: Canvas LMS for Claude, ChatGPT Codex and Cursor

[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)
[![MCP](https://img.shields.io/badge/MCP-server-8A2BE2)](https://modelcontextprotocol.io)
![Python 3.10+](https://img.shields.io/badge/python-3.10%2B-blue)
[![M8ven Score](https://m8ven.ai/badge/mcp/mattlo0546-canvas-mcp-7p0mkm?v=ba0c00865233db1648f13c3fffef4bb3)](https://m8ven.ai/mcp/mattlo0546-canvas-mcp-7p0mkm?s=readme)

**canvas-mcp** is an open-source [Model Context Protocol (MCP)](https://modelcontextprotocol.io) server for
**Canvas LMS** (by Instructure). It lets AI assistants (Claude Desktop, Claude Code, ChatGPT Codex, Cursor,
VS Code and [SlideMate](https://github.com/Mattlo0546/slidemate)) read a student's Canvas courses, modules,
deadlines and announcements. It can also **download every course's lecture slides** into one folder per course.

- **Works at any university that uses Canvas.** It defaults to the **University of Oxford** (`canvas.ox.ac.uk`),
  and you set `CANVAS_BASE_URL` for anywhere else.
- **No API token needed.** You sign in through your university's normal single sign-on (SSO) and MFA in a real
  browser window. Many universities, Oxford included, don't let students create Canvas access tokens. If yours
  does, `CANVAS_TOKEN` works too.
- **Read-only.** It can't submit work, post or change anything on Canvas.

> Using Moodle or Blackboard instead? See [moodle-mcp](https://github.com/Mattlo0546/moodle-mcp) (UCL, King's,
> LSE, Cambridge, Warwick…) and [blackboard-mcp](https://github.com/Mattlo0546/blackboard-mcp) (Imperial,
> Edinburgh, Bristol, Leeds…).

## What you can ask

- *"What's due on Canvas this week, and what haven't I submitted?"*
- *"Any new announcements in my courses?"*
- *"Show me week 3 of PPE101 and download the lecture slides."*
- *"Pull every lecture PDF from all my current courses."*

## Tools

| Tool | What it does |
| --- | --- |
| `canvas_login` | Opens a browser window for university SSO + MFA and saves the session. It tries a silent refresh first. |
| `canvas_status` | Which site you're on, who you're signed in as, and where files download to |
| `canvas_courses` | Your current courses, with their term, and whether a full sync pulls each one |
| `canvas_set_courses` | Change which courses a full sync pulls (`include` an info site it skips, `exclude` a course) |
| `canvas_browse` | A course's modules: files, pages, links and assignments with due dates |
| `canvas_deadlines` | Assignments, quizzes and discussions due in the next N days, with submission status |
| `canvas_announcements` | Recent announcements in one course, or in all of them |
| `canvas_download` | Save one file (a `file_id` from `canvas_browse`) |
| `canvas_sync` / `canvas_sync_status` | With no course: download the PDFs from every current course, in the background. With a course: download all of its files. |

Courses can be named loosely: `"PPE101"`, `"philosophy"` or the course id all work. A sync files things as
`<course code>/<module name>/<file>`. It skips past courses and files you already have, and it still finds module
files in courses that hide the Files tab from students.

A full sync also skips what isn't for studying: sites that aren't courses (guidance hubs, study-skills sites,
year-group noticeboards) and, inside courses, posters, handbooks, forms, timetables and modules like "Student
support". Its report lists the sites it skipped; `canvas_set_courses` brings one back. Words that are also lecture
topics only count in an admin phrase, so "Mathematical induction" stays and "Induction week schedule" goes
([`relevance.py`](canvas_mcp/relevance.py)).

## Install

### macOS / Linux, one command

This installs [uv](https://docs.astral.sh/uv/), which brings its own Python, so you don't need Xcode or Apple's
Command Line Tools. Then it installs `canvas-mcp` and opens Chrome so you can sign in once:

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh && ~/.local/bin/uv tool install --managed-python https://github.com/Mattlo0546/canvas-mcp/archive/refs/heads/main.zip && CANVAS_BASE_URL=canvas.ox.ac.uk ~/.local/bin/canvas-mcp login
```

Change `canvas.ox.ac.uk` to your university's Canvas address. Sign-in uses Google Chrome. Without Chrome, first
run `~/.local/share/uv/tools/canvas-mcp/bin/playwright install chromium`. To update later, add `--reinstall`
after `tool install`.

### Windows

```powershell
powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
uv tool install --managed-python https://github.com/Mattlo0546/canvas-mcp/archive/refs/heads/main.zip
$env:CANVAS_BASE_URL="canvas.ox.ac.uk"; canvas-mcp login
```

## Connect it to your AI app

Set `CANVAS_BASE_URL` to your university's Canvas address in each config below.

### SlideMate

In [SlideMate](https://github.com/Mattlo0546/slidemate), go to Settings → **Your university**, then pick your
university or **Canvas** and press **Connect**. SlideMate installs this server, signs you in and makes the
library's **Pull** button download new slides. Nothing to type.

### Claude Code

```bash
claude mcp add canvas -e CANVAS_BASE_URL=https://canvas.ox.ac.uk -- ~/.local/bin/canvas-mcp serve
```

### Claude Desktop

Settings → Developer → Edit Config (`claude_desktop_config.json`):

```json
{
  "mcpServers": {
    "canvas": {
      "command": "/Users/YOU/.local/bin/canvas-mcp",
      "args": ["serve"],
      "env": { "CANVAS_BASE_URL": "https://canvas.ox.ac.uk" }
    }
  }
}
```

### ChatGPT Codex CLI

```bash
codex mcp add canvas --env CANVAS_BASE_URL=https://canvas.ox.ac.uk -- ~/.local/bin/canvas-mcp serve
```

### Cursor (`~/.cursor/mcp.json`) and VS Code (`.vscode/mcp.json`, under `"servers"`)

```json
{
  "mcpServers": {
    "canvas": {
      "command": "/Users/YOU/.local/bin/canvas-mcp",
      "args": ["serve"],
      "env": { "CANVAS_BASE_URL": "https://canvas.ox.ac.uk" }
    }
  }
}
```

## Universities that use Canvas

Any Canvas site works. These addresses were checked to be Canvas instances:

| University | `CANVAS_BASE_URL` |
| --- | --- |
| University of Oxford | `canvas.ox.ac.uk` |
| University of Birmingham | `canvas.bham.ac.uk` |
| University of Liverpool | `canvas.liverpool.ac.uk` |
| University of Sussex | `canvas.sussex.ac.uk` |
| Harvard University | `canvas.harvard.edu` |
| Stanford University | `canvas.stanford.edu` |
| MIT | `canvas.mit.edu` |
| UC Berkeley (bCourses) | `bcourses.berkeley.edu` |
| UC San Diego | `canvas.ucsd.edu` |
| University of Michigan | `umich.instructure.com` |
| Columbia University (CourseWorks) | `courseworks2.columbia.edu` |
| Carnegie Mellon University | `canvas.cmu.edu` |
| National University of Singapore | `canvas.nus.edu.sg` |
| University of Newcastle, Australia | `canvas.newcastle.edu.au` |

Your university's Canvas address is the one in your browser's address bar when you open Canvas. Often it's
`canvas.<university domain>` or `<name>.instructure.com`.

## Command line

```bash
canvas-mcp login          # sign in (opens Chrome)
canvas-mcp status         # who you're signed in as
canvas-mcp courses        # your current courses
canvas-mcp deadlines      # what's due in the next 14 days
canvas-mcp sync           # PDFs from every current course
canvas-mcp sync PPE101    # every file in one course
```

## Settings (all optional)

Environment variables win over `~/.canvas-mcp/config.json`.

| Variable | Default | Meaning |
| --- | --- | --- |
| `CANVAS_BASE_URL` | `https://canvas.ox.ac.uk` | Your Canvas site |
| `CANVAS_TOKEN` | none | A Canvas access token (Account → Settings → New access token), if your university allows them. It replaces the browser sign-in. |
| `CANVAS_DOWNLOAD_DIR` | SlideMate's first slides folder, else `~/CanvasFiles` | Where downloads go |
| `CANVAS_BROWSER_CHANNEL` | `chrome` | Browser for sign-in. `""` uses Playwright's own Chromium. |
| `CANVAS_MCP_HOME` | `~/.canvas-mcp` | Where the session and the sign-in browser profile are kept |

## How sign-in works

Canvas at most universities sits behind SAML or Shibboleth single sign-on with MFA, so there's no password a script
can post. `canvas_login` opens your Canvas site in a real Chrome window and you sign in as usual. It waits until the
Canvas REST API (`/api/v1/users/self`) answers, then saves that site's session cookies, readable only by you. The
API client sends those cookies, exactly as the Canvas website does. The browser profile remembers your SSO
session, so when the Canvas session lapses, the server signs back in headlessly with no clicks, for as long as your
university's SSO allows.

## FAQ

**Is there a Canvas MCP server that works without an API token?**
Yes, this one. It signs in through your university's SSO in a browser, so it works where students can't create
access tokens.

**Does it work with ChatGPT?**
It works with OpenAI's Codex CLI and with any app that supports local (stdio) MCP servers. The ChatGPT website
can only use remote MCP servers.

**Can it submit assignments or post on Canvas?**
No. Every tool is read-only, apart from saving files to your own computer.

**Where is my data stored?**
Only on your computer. The session is at `~/.canvas-mcp/session.json`. Delete that file and
`~/.canvas-mcp/browser-profile` to sign out. Data goes straight between your computer and your university's Canvas.

**Is it allowed?**
It only reads what you can already see when you're signed in, at about the pace of a person clicking through
Canvas. Check your university's IT acceptable-use policy if you're unsure.

## Development

```bash
uv run --with pytest pytest     # offline tests against a fake Canvas: pagination, hidden Files, expiry, stdio
```

## Related

- [moodle-mcp](https://github.com/Mattlo0546/moodle-mcp): MCP server for Moodle
- [blackboard-mcp](https://github.com/Mattlo0546/blackboard-mcp): MCP server for Blackboard Learn (Ultra)
- [classroom-mcp](https://github.com/Mattlo0546/classroom-mcp): MCP server for Google Classroom
- [SlideMate](https://github.com/Mattlo0546/slidemate): a free Mac app with an AI tutor that has read your whole
  lecture deck. It sets all of these up in one click.

MIT licensed. Not affiliated with Instructure or the University of Oxford. Canvas is a trademark of Instructure, Inc.
