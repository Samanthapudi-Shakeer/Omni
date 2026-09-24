# Remote Aider Console — React + FastAPI + Python `pty` (v3)

```
React (Vite) UI  →  FastAPI + WebSocket backend  →  real Unix PTY (stdlib pty)
                                                          →  real Aider CLI  →  Ollama
```

Every UI action still just writes the same native Aider command a human would
type (`/add`, `/drop`, `/clear`, `/tokens`, `/chat-mode`, `/model`, or a plain
prompt) into the hidden PTY. Aider is never reimplemented.

## What's new in this version (v10)

- **Modularization and Test-Gen now go through Aider, on isolated sessions.**
  Both tools attach the file(s) and submit the prompt as a real Aider task —
  but on a **dedicated hidden Aider process per workspace**, completely
  separate from whatever's running in the visible Aider Console. Verified
  live with three simultaneously-running Aider processes (console +
  modularize + testgen), confirmed by distinct PIDs, and confirmed the
  console session stays untouched (`idle`, no attached files) the whole
  time. These hidden sessions launch with `--yes-always` so they can never
  hang on a confirmation prompt nobody can see. The endpoint blocks until
  Aider actually finishes and returns the real diff directly — no polling
  needed. An "↶ Undo last change" button is available on both pages.
- **Pylint auto-fix now only sends genuine errors to the model**, not
  style/convention/warning noise — verified both the negative case (only
  warnings present → correctly skips the fix) and positive case (a real
  syntax error → correctly sent and fixed).
- **Shared workspace across all four pages.** Static Code Analysis,
  Modularization, and Test Case Generation no longer have their own
  workspace picker — they all use whatever workspace is currently selected
  in the Aider Console (state now lives in `Shell.jsx`, passed down as
  props). Per-tab isolation (via `sessionStorage`) still applies at the
  Shell level.
- **Fixed a real bug**: Supervised Mode's transcript (Aider's actual response
  text) used to disappear the instant a task finished, since it was only
  rendered inside the `taskRunning`-gated block — leaving just the changed
  files and diff, with none of what Aider actually said. The transcript now
  persists and stays visible after completion.
- **Dashboard-style layout** for the three tool pages: full width instead of
  a narrow centered column, with result cards (e.g. findings + fix-diff)
  flowing into a responsive grid that sits side by side on wide screens.

## What's new in v8: Navbar + three standalone Ollama-direct tools

A top navbar now sits above everything, switching between four sections:

- **◈ Aider Console** — everything from before (workspaces, Terminal/Supervised
  mode, Code Canvas, etc.), unchanged.
- **🧹 Static Code Analysis** — runs **pylint directly** as a subprocess (no
  LLM, no Aider) and lists real findings. An **Auto-fix with Ollama** button
  sends the file + findings straight to Ollama's HTTP API — bypassing Aider
  entirely — and shows the proposed fix as a diff before you decide whether
  to save it.
- **🧩 Modularization** — upload a file (or pick one already in the
  workspace), write any prompt you want (or use the default "break this into
  smaller, well-organized modules" prompt), and get a diff back from Ollama
  directly.
- **🧪 Test Case Generation** — pick a file, describe what tests you want,
  and get generated test code back from Ollama directly. Since this produces
  new content rather than modifying the source file, there's no diff — just
  the generated text, with a save dialog defaulting to a sensible
  `test_<name>` filename.

**All three tools are deliberately independent of Aider** — no PTY, no chat
session, no auto-commit. Each one is a single direct HTTP call to Ollama's
`/api/generate`, with the diff (where applicable) computed locally via
Python's `difflib` for an exact comparison. Nothing is written to disk until
you explicitly click Save, which goes through a rename-before-save dialog.

They share a small set of new backend pieces:
- `pylint_runner.py` — direct subprocess call to pylint, JSON output parsed
  into structured findings.
- `ollama_client.generate_direct()` — plain HTTP call to Ollama, independent
  of the Aider session (translates the app's `ollama/<name>` model format to
  the bare name Ollama's own API expects).
- `ollama_tools.py` — shared diffing (`difflib`-based) and markdown-fence
  stripping (models often wrap output in ``` fences despite being told not
  to) used by all three.
- New endpoints: `POST /lint/analyze`, `POST /lint/autofix`,
  `POST /ollama/modularize`, `POST /ollama/testgen`, `POST /files/write`.

**A real bug fixed along the way:** multi-line prompts sent through the PTY
were being split into separate submissions, since each embedded newline acts
like pressing Enter on a raw keystroke feed. Fixed by wrapping multi-line
input in Aider's documented `{tag ... tag}` multiline-entry syntax. This
affects any multi-paragraph prompt sent to Aider (including Supervised
Mode tasks), not just today's changes — worth specifically re-testing
against real Aider, since I could only verify the wrapping logic itself, not
how Aider's actual prompt_toolkit-based input reader responds to it.

Also fixed: workspace file listings now respect `.gitignore` (via
`git ls-files --others --ignored --exclude-standard`), so ignored files
(`.env`, `build/`, etc.) never show up in the file browser.

## What's new in v7: Supervised Mode upgrades + Code Canvas

- **Chat-style transcript.** Supervised Mode now streams Aider's actual prose
  explanations as chat bubbles, not just a rotating phase label. The backend
  classifies each output line as diff/system-chatter/prose and only forwards
  genuine prose — diffs and log noise never leak into the transcript.
- **Per-file progress checklist.** Each file selected for a task shows a live
  ○ pending → ◐ editing → ✓ done indicator. "Editing" is a best-effort text
  match; "done" is only ever set once a real git commit confirms the file
  actually changed — so the checklist can't lie about completion.
- **Phase timeline.** Instead of overwriting a single "what's happening now"
  label, phases now accumulate into a small scrolling timeline (with
  consecutive-repeat dedup, since Aider can re-trigger the same phase many
  times in a row).
- **Elapsed timer** on every running task, so a long local-model generation
  reads as "42s and counting" instead of an ambiguous spinner.
- **Notifications.** A browser notification + short beep fire when Aider asks
  a question or a task completes — useful since Supervised Mode is designed
  for you to tab away while it works. Falls back to an in-app toast if
  notification permission isn't granted.
- **Follow-up shortcut.** The result panel's "Follow up on this" button
  pre-fills a new task with a reference to what you just asked for.
- **Code Canvas** — a Gemini-style version browser. Pick a file, see every
  commit that touched it this session (numbered, most recent first), and
  view either the diff or the full file snapshot at that version. Reachable
  from the task result panel ("◪ Code Canvas" or per-file "Versions"
  button). Built entirely on the same git-diffing approach as the rest of
  the app's history features — no fragile terminal-output scraping.

## What's new in v6

- **Reverted the idle-detection regression.** v5's stricter "only idle when
  the literal prompt text reappears" logic doesn't reliably match real
  Aider's actual output shape, so status got stuck on "Starting…" or
  "Processing…" forever. Reverted to v3's simpler, more robust rule: after
  ~600ms of silence, treat Aider as done with whatever it was doing. This
  also fixes a side effect that wasn't obvious at first — the modified-files
  log and version history only ever recompute on that same idle transition,
  so with status stuck, both silently never updated either. Verified all
  three (status, modified-files log, version history) update correctly now.
- **Light theme, full UI pass.** Switched from the dark instrument-panel
  look to a clean light theme (white/off-white panels, indigo accent,
  neutral-gray shadows instead of glows) across the sidebar, top bar,
  composer, popovers, command palette, and Supervised Mode. The terminal
  pane itself stays dark — that's a deliberate choice, not an oversight:
  ANSI color palettes and virtually every terminal/IDE convention are
  calibrated for a dark terminal background even inside an otherwise light
  UI (e.g. VS Code's default light theme still ships a dark integrated
  terminal). Say the word if you'd actually like the terminal pane itself
  light too — it's a bigger lift because the ANSI 16-color palette needs
  re-tuning for legibility on white, but doable.
- **Colored diff view.** Both the Supervised Mode result panel and the
  `diff_viewer_local.html` stub now render unified diffs with per-line
  coloring (green additions, red deletions, indigo hunk headers) instead of
  a flat monochrome block.

## What's new in v5

- **Fixed status semantics.** "Running" now means Aider is genuinely
  processing something you sent it — not just that the process is alive.
  Boot chatter, idle silence, and incidental output no longer show as
  "running"; the status only flips to Processing when you actually submit
  input, and back to Idle only once Aider's real prompt reappears (never on
  a timeout, so a slow local model "thinking" silently doesn't get
  misreported as done).
- **One shared answer flow, both modes.** Terminal Mode and Supervised Mode
  now use the exact same `QuestionPrompt` component for interactive
  questions — same buttons, same free-text fallback, same submission path.
  In Terminal Mode it docks just above the composer (which disables itself
  while a question is pending, so there's only one place to answer from).
- **Connection popover, tokens moved to a tab.** The info button next to the
  model name now opens a small popover defaulting to **Connection** status
  (Aider + Ollama), with a **Tokens** tab alongside it. The sidebar's old
  three-lamp manifold (Aider/Ollama/Link) is gone — the Link/WebSocket
  indicator was dropped entirely, and Aider/Ollama status now live in this
  one popover instead.
- **Workspace path moved.** No longer a sidebar field — it's now a small
  badge in the middle of the top bar (workspace name, full path on hover).
- **Version History + Undo.** A new sidebar panel lists every commit made
  during the current Aider session (numbered from the latest down to `0`
  for session start), each with its subject, short hash, time, and files
  touched. An **Undo latest** button calls Aider's native `/undo` — since
  Aider can only undo its own most recent commit, clicking it repeatedly is
  how you step backward through history one change at a time.
- **Download with rename.** Clicking download (on any modified-file entry)
  opens a small dialog pre-filled with the original name; you can rename it
  before the browser save-dialog fires.
- **Diff Viewer handoff.** A "Open in Diff Viewer ↗" button in Supervised
  Mode's task result hands the diff off (via `sessionStorage`) to
  `diff_viewer_local.html`, a deliberately minimal stub page served
  alongside the app — a working `<pre>` fallback is already wired up, with
  clear TODOs for building a proper viewer.

## What's new in the base version (v3/v4)

- **Independent workspaces.** Create a named workspace from the sidebar; each
  gets its own directory under `WORKSPACES_ROOT` and its own fully independent
  Aider process/PTY. Switching workspaces switches the whole session — files,
  terminal history, attached files, everything. **Each browser tab/window is
  independent too**: the current workspace choice lives in `sessionStorage`
  (per-tab), not `localStorage`, and a fresh tab never auto-joins whatever
  workspace happens to be first in the list — it always asks you to select or
  create one. Two people (or two windows) never silently end up sharing a
  workspace by accident.
- **Correct busy detection.** Status no longer flips to "idle/completed" just
  because output paused — a local model can think silently for a long time.
  We only consider Aider done when its actual idle prompt reappears; a plain
  silent gap keeps the status (and the UI) showing "running".
- **Richer status, top right.** A status chip (`idle` / `running` / `waiting
  for input` / `completed` / `error` / `stopped`) sits next to the current
  model name, with a 📚 library icon (opens the command palette) and an **i**
  info button (token-usage popover: used vs remaining in the context window,
  parsed live from Aider's own `/tokens` output).
- **A real terminal.** Terminal Mode renders through **xterm.js**, fed the
  *raw* PTY bytes over the WebSocket — ANSI colors, cursor movement, progress
  spinners, scrollback, and native copy/paste all work like a real terminal.
  A "working" banner appears above it whenever Aider is actively generating,
  so it's clear the session isn't just stuck.
- **Prompt lifecycle.** Send is disabled while Aider is `starting`/`running`/
  mid-task, and re-enables once it's idle or waiting on you.
- **Enhanced, polished sidebar.** Sections are grouped into cards with subtle
  depth; workspace and attached-file lists are cross-highlighted (a file
  already attached shows an amber dot + highlight in the workspace list, with
  a **Drop** button right there) so both views can never drift apart — they're
  both driven by Aider's own "Added/Removed ... chat" confirmations. A context
  pill shows attached file count and an estimated token count.
- **Per-session modified-files log + downloads.** Every file Aider changes —
  whether newly created or edited in place — is tracked for the lifetime of
  the current Aider process (computed from real git commits, reset on every
  restart) and listed with a **⭳ download** button, so you can pull a changed
  file straight to your machine without leaving the browser.
- **Command library + palette.** `Ctrl/Cmd+K` (or the 📚 icon) opens a
  searchable palette of Aider's native commands with descriptions — picking
  one either runs it immediately or inserts it into the composer.
- **Supervised Mode.** Pick files, type a task, hit **Start Task**. While it
  runs you see only a derived progress indicator — never the raw terminal —
  and Send is disabled. Interactive questions surface as option buttons with
  a free-text fallback. On completion you get changed files, commit log, and
  a full unified diff computed from real git commits. **Stop Task** sends a
  real Ctrl-C; **Switch to Terminal Mode** works any time and replays what
  happened while you were away.

## Project layout

```
backend/app/
  main.py               FastAPI app: workspace-scoped REST + /ws/{name}
  workspace_manager.py   Registry of named workspaces, each with its own
                         AiderSession; auto-discovers existing dirs on boot
  aider_session.py        The PTY-owning session: raw byte streaming, status
                         state machine, question/phase detection, token
                         parsing, supervised task lifecycle
  git_utils.py             git init + before/after diff for task results
  commands_library.py     Static reference of Aider's slash commands
  workspace_fs.py          Safe file listing + path-traversal guard
  ollama_client.py          Ollama /api/tags health check + model listing
  ws_manager.py             Per-workspace WebSocket broadcast

frontend/src/
  App.jsx                 Top-level state/orchestration
  components/
    WorkspaceBar.jsx       Create/select workspace
    Sidebar.jsx             Controls + file lists (context-aware, bidirectional)
    StatusBar.jsx            Status chip + model + token popover
    TerminalView.jsx          xterm.js real terminal
    SupervisedView.jsx        Task composer, progress, question card, diff result
    CommandPalette.jsx         Ctrl/Cmd+K command search
    Composer.jsx               Prompt input with lifecycle-aware disabling
    Toasts.jsx                  Notifications
```

## Prerequisites

- Python 3.10+ (uses `os.fork`/`os.execvpe` — **Linux/Unix only** for the
  backend; the browser UI works from anywhere including Windows).
- `git` on `PATH` (used for the diff-based Supervised Mode results — a repo
  is auto-initialized per workspace if one doesn't exist).
- Node.js 18+ and npm, to build the frontend.
- [Aider](https://aider.chat/) on `PATH` (or set `AIDER_BIN`).
- [Ollama](https://ollama.com/) running with at least one model pulled.

## Setup

```bash
# Backend
cd backend
pip install -r requirements.txt --break-system-packages   # or use a venv
cp .env.example .env
# edit .env: WORKSPACES_ROOT, AIDER_BIN, OLLAMA_API_BASE, DEFAULT_MODEL

# Frontend (build once; FastAPI serves the static output)
cd ../frontend
npm install
npm run build

# Run — from the backend/ directory (important, see note below)
cd ../backend
python -m uvicorn app.main:app --host 0.0.0.0 --port 8080
# or: python run.py
```

Open `http://<server-ip>:8080`. Create your first workspace from the sidebar
— everything else (start Aider, attach files, chat) happens per-workspace
from there.

> **Run it as a package, not a script.** Always start from the `backend/`
> directory with `python -m uvicorn app.main:app ...` (or `python run.py`).
> Running `python app/main.py` or `uvicorn main:app` from inside `app/`
> breaks the relative imports (`from .config import settings`, etc.) with
> `ImportError: attempted relative import with no known parent package`.

### Frontend dev mode (optional)

```bash
cd backend && python -m uvicorn app.main:app --port 8080   # terminal 1
cd frontend && npm run dev                                 # terminal 2
```
Vite (port 5173) proxies `/api` and `/ws` to the backend for hot-reload.

### Optional access control

Set `ACCESS_TOKEN` in `.env`; the UI reads the same value from
`localStorage.setItem('aider_token', '...')`. For anything beyond a trusted
LAN, put a reverse proxy with TLS and real auth in front.

## What was verified

No visual screenshot (I can't render a browser in the environment I built
this in), but the full backend contract every new UI feature depends on was
exercised end to end against a stand-in `aider` script that speaks the same
protocol (ANSI colors, confirmation prompts, `/tokens` reports, and — most
importantly — actually writes files and makes real `git` commits so the
diff logic has something real to compute against):

- Workspace creation, name validation, duplicate/traversal rejection, and
  auto-discovery of pre-existing workspace directories on restart
- Status state machine transitions (`stopped→starting→running→waiting_input
  →completed`), including over the live WebSocket feed
- Raw ANSI-containing PTY bytes replay correctly to a fresh WebSocket
  connection (confirmed byte-for-byte via the backlog), which is what
  `TerminalView`'s xterm.js instance renders
- `/tokens` output parsed into structured used/remaining numbers
- Interactive question detection + clean option labels (`Yes`, `No`, `All`,
  `Skip all`, `Don't ask again`) extracted from Aider's confirmation prompt
  shape, and answering it correctly resumes the session
- A full Supervised Mode task: start → question appears → answer → task
  completes → `task_complete` event carries a real git diff (changed files,
  unified diff, commit log) computed from actual commits made during the task
- Stop Task (Ctrl-C) correctly aborts a running task and re-enables the UI
- The backend rejects a new prompt with 409 while a task is already running
- `npm run build` succeeds with 0 errors across all new components
- The built frontend is served correctly by FastAPI from the same origin

Please run it against real Aider + Ollama and let me know what needs
adjusting — particularly how well the question-detection regex holds up
against Aider's actual (not simulated) confirmation prompt wording, since
that's the one piece I could only approximate without the real CLI.
