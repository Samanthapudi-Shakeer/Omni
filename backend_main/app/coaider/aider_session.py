"""
Owns a single hidden Aider process behind a real pseudo-terminal, using only
stdlib pty/os/fcntl/termios. Aider remains the actual coding engine; this
class spawns it, feeds it the same keystrokes a human would type, and
relays raw output.

Two consumers of the output exist:
  - Terminal Mode: gets the RAW bytes (base64-wrapped) so a real terminal
    emulator (xterm.js) on the frontend can render ANSI colors, cursor
    movement, progress spinners, etc. exactly as a real terminal would.
  - Supervised Mode: gets a derived, ANSI-stripped stream used only for
    heuristic phase/question detection -- never shown to the user directly.
"""

import asyncio
import base64
import fcntl
import os
import pty
import re
import signal
import struct
import termios
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Awaitable, Optional

from . import git_utils

ADDED_RE = re.compile(r"Added\s+(.+?)\s+to the chat", re.IGNORECASE)
REMOVED_RE = re.compile(r"Removed\s+(.+?)\s+from the chat", re.IGNORECASE)
ANSI_RE = re.compile(r"\x1b\[[0-9;?]*[a-zA-Z]|\x1b\].*?\x07|\x1b[=>]")

# Aider's plain-text (non-pretty) confirmation prompts look like:
#   "Add file.py to the chat? (Y)es/(N)o/(A)ll/(S)kip all/(D)on't ask again [Yes]: "
# We detect the *shape*, not a fixed message, so this works for any question
# Aider asks, not a hardcoded list.
QUESTION_RE = re.compile(
    r"(?P<question>[^\n]*\?)\s*"
    r"(?P<opts>(?:\([A-Za-z]\)[A-Za-z' ]+(?:/\s*)?)+)?"
    r"(?:\[[A-Za-z]+\])?\s*:?\s*$"
)
IDLE_PROMPT_RE = re.compile(r"(?:^|\n)>\s*$")
OPTION_RE = re.compile(r"\(([A-Za-z])\)([A-Za-z' ]+)")

# Heuristic phase classifier for Supervised Mode's "what is it doing right
# now" indicator. Order matters -- first match wins.
PHASE_PATTERNS = [
    (re.compile(r"analy[sz]ing|planning|thinking", re.I), "Analyzing requested changes"),
    (re.compile(r"scanning|repo.?map|building.*map", re.I), "Scanning the repository"),
    (re.compile(r"searching web|fetching url", re.I), "Fetching web content"),
    (re.compile(r"add(ed|ing).+to the chat", re.I), "Attaching files"),
    (re.compile(r"applying edit|editing file|writing to", re.I), "Editing files"),
    (re.compile(r"running (tests?|command)|test(s)? (failed|passed)", re.I), "Running tests/commands"),
    (re.compile(r"linting", re.I), "Linting changed files"),
    (re.compile(r"commit", re.I), "Committing changes"),
    (re.compile(r"tokens? (used|remaining)", re.I), "Checking token usage"),
]

# Best-effort mapping from an output line to which of the task's selected
# files it's currently touching, for Supervised Mode's per-file checklist.
# Real Aider's exact wording varies by edit format/model, so this is
# deliberately loose -- it only needs to catch the common cases; the
# authoritative "done" signal is always the git commit, not this regex.
FILE_ACTIVITY_RE = re.compile(r"(?:Editing|Writing|Updating|Applying edit to)\s+([^\s,:]+)", re.I)

# Lines belonging to a diff/patch block, filtered OUT of the Supervised Mode
# transcript (that's prose-only; diffs are shown separately via Code Canvas).
DIFF_LINE_RE = re.compile(
    r"^(diff --git|index |--- |\+\+\+ |@@ |<{7}|={7}|>{7}|[+-])"
)
# Lines that are just Aider's own status chatter (added/removed, phase
# keywords, raw commit-hash log lines, the idle prompt itself) -- also
# filtered out of the transcript, since none of it is the model's prose.
SYSTEM_LINE_RE = re.compile(
    r"^(Added |Removed |Applied edit|Commit(ting|ted)?\b|Chat mode set|Model set|"
    r"[0-9a-f]{7} |>\s*$|>\s+\S|/\S|Scanning|Tokens?:|Approximate context|"
    r"\[[\w/\-]+ [0-9a-f]+\]|\s*\d+ files? changed|\s*(create|delete) mode|\s*rename )",
    re.I,
)


def _strip_ansi(text: str) -> str:
    return ANSI_RE.sub("", text).replace("\r\n", "\n").replace("\r", "")


def _set_winsize(fd: int, rows: int = 40, cols: int = 120):
    winsize = struct.pack("HHHH", rows, cols, 0, 0)
    fcntl.ioctl(fd, termios.TIOCSWINSZ, winsize)


def _parse_question(clean_tail: str) -> Optional[dict]:
    tail = clean_tail.strip("\n")
    if not tail:
        return None
    last_block = tail.splitlines()[-1] if tail.splitlines() else tail
    m = QUESTION_RE.search(last_block)
    if not m:
        return None
    question = m.group("question").strip()
    opts_raw = m.group("opts") or ""
    options = [{"key": k, "label": (k + label).strip()} for k, label in OPTION_RE.findall(opts_raw)]
    return {"question": question, "options": options}


def _parse_tokens(clean_text: str) -> Optional[dict]:
    """Best-effort parse of Aider's /tokens report into structured numbers.
    Falls back gracefully -- callers should always keep the raw text too."""
    low = clean_text.lower()
    if "tokens remaining" not in low and "context window" not in low:
        return None
    used = None
    remaining = None
    breakdown = []
    for line in clean_text.splitlines():
        low_line = line.lower()
        num_match = re.search(r"([\d,]+)", line)
        if not num_match:
            continue
        if "remaining" in low_line:
            remaining = int(num_match.group(1).replace(",", ""))
        elif ("used" in low_line or "total" in low_line) and "remaining" not in low_line:
            used = int(num_match.group(1).replace(",", ""))
        elif line.strip().startswith("$"):
            parts = line.strip().split(None, 2)
            if len(parts) >= 3:
                breakdown.append({"cost": parts[0], "tokens": parts[1], "label": parts[2]})
    if used is None and remaining is None and not breakdown:
        return None
    return {"used": used, "remaining": remaining, "breakdown": breakdown, "raw": clean_text.strip()}


Broadcast = Callable[[dict], Awaitable[None]]


@dataclass
class SessionStatus:
    status: str = "stopped"  # stopped|starting|running|waiting_input|completed|error|crashed
    last_error: Optional[str] = None
    model: str = ""
    mode: str = "code"
    workspace: str = ""
    attached_files: list = field(default_factory=list)
    pending_question: Optional[dict] = None
    supervised: bool = False
    task_running: bool = False

    def to_dict(self):
        return {
            "status": self.status,
            "lastError": self.last_error,
            "model": self.model,
            "mode": self.mode,
            "workspace": self.workspace,
            "attachedFiles": self.attached_files,
            "pendingQuestion": self.pending_question,
            "supervised": self.supervised,
            "taskRunning": self.task_running,
        }


class AiderSession:
    def __init__(
        self,
        name: str,
        aider_bin: str,
        workspace_dir: str,
        ollama_base: str,
        model: str,
        mode: str,
        broadcast: Broadcast,
        lint_cmd: str = "",
        auto_confirm: bool = False,
    ):
        self.name = name
        self.aider_bin = aider_bin
        self.workspace_dir = workspace_dir
        self.ollama_base = ollama_base
        self.lint_cmd = lint_cmd
        self.auto_confirm = auto_confirm
        self.broadcast = broadcast

        self.master_fd: Optional[int] = None
        self.pid: Optional[int] = None
        self.attached_files: set[str] = set()
        self.status = SessionStatus(model=model, mode=mode, workspace=workspace_dir)
        self.tokens_summary: Optional[dict] = None

        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._idle_handle: Optional[asyncio.TimerHandle] = None
        self._raw_buffer: list[bytes] = []
        self._max_buffer = 2000
        self._clean_tail = ""
        self._waiter_thread: Optional[threading.Thread] = None
        self._task_head_before: Optional[str] = None
        self._task_done_event: Optional[asyncio.Event] = None
        self._last_task_diff: Optional[dict] = None
        self._session_head_start: Optional[str] = None
        self._recorded_head: Optional[str] = None
        # Commit ids are recorded at each completion boundary for this
        # particular process. This is deliberately separate from repository
        # history because the three Aider processes share a worktree.
        self._session_commits: list[str] = []
        self.phase_timeline: list[dict] = []
        self._task_files: list[str] = []
        self.file_progress: dict[str, str] = {}  # path -> pending|editing|done
        # True only while Aider is actually working on something we sent it
        # (a prompt, /undo, /tokens, etc). The process being alive is NOT the
        # same as "processing" -- boot chatter, and silence while genuinely
        # idle at the prompt, must never show as "running".
        self._processing = False
        # Cumulative log of files Aider has changed *this session* (reset on
        # every start/restart -- intentionally not tied to the workspace's
        # full git history, just "what happened while this process ran").
        self.modified_files: dict[str, dict] = {}  # path -> {path, status, changedAt, commit}

        git_utils.ensure_repo(Path(workspace_dir))

    # ------------------------------------------------------------------ info
    def is_running(self) -> bool:
        return self.master_fd is not None

    def get_status(self) -> dict:
        self.status.attached_files = sorted(self.attached_files)
        data = self.status.to_dict()
        data["phaseTimeline"] = list(self.phase_timeline)
        return data

    def get_context_stats(self) -> dict:
        total_bytes = 0
        for rel in self.attached_files:
            p = Path(self.workspace_dir) / rel
            try:
                total_bytes += p.stat().st_size
            except OSError:
                pass
        return {"fileCount": len(self.attached_files), "estTokens": round(total_bytes / 4)}

    def get_recent_raw_b64(self) -> list[str]:
        return [base64.b64encode(b).decode("ascii") for b in self._raw_buffer]

    # --------------------------------------------------------------- lifecycle
    def start(self) -> dict:
        if self.master_fd is not None:
            raise RuntimeError("Aider session already running. Stop it first.")

        self._loop = asyncio.get_event_loop()
        self.status.status = "starting"
        self.status.last_error = None
        self.status.pending_question = None
        self.modified_files = {}
        self._task_files = []
        self.file_progress = {}
        self.phase_timeline = []
        self._session_head_start = git_utils.current_head(Path(self.workspace_dir))
        self._recorded_head = self._session_head_start
        self._session_commits = []

        args = [self.aider_bin, "--model", self.status.model, "--no-pretty", "--no-check-update"]
        if self.lint_cmd:
            args += ["--lint-cmd", self.lint_cmd]
        if self.auto_confirm:
            args += ["--yes-always"]

        env = dict(os.environ)
        env["OLLAMA_API_BASE"] = self.ollama_base
        env["TERM"] = "xterm-256color"

        try:
            master_fd, slave_fd = pty.openpty()
            _set_winsize(slave_fd)
            os.set_blocking(master_fd, False)

            pid = os.fork()
            if pid == 0:
                os.setsid()
                os.dup2(slave_fd, 0)
                os.dup2(slave_fd, 1)
                os.dup2(slave_fd, 2)
                os.close(master_fd)
                os.close(slave_fd)
                try:
                    os.chdir(self.workspace_dir)
                    os.execvpe(args[0], args, env)
                except Exception as exc:  # pragma: no cover - child path
                    os.write(2, f"[exec failed] {exc}\n".encode())
                    os._exit(127)
            else:
                os.close(slave_fd)
                self.master_fd = master_fd
                self.pid = pid
        except Exception as exc:
            self.status.status = "error"
            self.status.last_error = f"Failed to launch Aider: {exc}"
            self._schedule(self.broadcast({"type": "status", "data": self.get_status()}))
            raise

        # Status stays "starting" (set above) until boot chatter settles and
        # the silence-based idle timer fires (see _on_idle) -- that's when we
        # treat Aider as actually finished launching.
        self._loop.add_reader(self.master_fd, self._on_readable)

        self._waiter_thread = threading.Thread(target=self._wait_for_exit, daemon=True)
        self._waiter_thread.start()

        self._loop.call_later(1.2, lambda: self._safe_send(f"/chat-mode {self.status.mode}\n"))

        self._schedule(self.broadcast({"type": "status", "data": self.get_status()}))
        return self.get_status()

    def _safe_send(self, text: str):
        if self.master_fd is not None:
            try:
                os.write(self.master_fd, text.encode())
            except OSError:
                pass

    def stop(self):
        if self.pid:
            try:
                os.killpg(os.getpgid(self.pid), signal.SIGTERM)
            except (ProcessLookupError, PermissionError, OSError):
                pass
        if self.master_fd is not None and self._loop:
            try:
                self._loop.remove_reader(self.master_fd)
            except Exception:
                pass
            try:
                os.close(self.master_fd)
            except OSError:
                pass
        self.master_fd = None
        self.pid = None
        self.attached_files.clear()
        self.status.status = "stopped"
        self.status.pending_question = None
        self.status.task_running = False
        self._schedule(self.broadcast({"type": "status", "data": self.get_status()}))

    async def restart(self) -> dict:
        # Make restart self-healing for workspaces restored from disk.
        git_utils.ensure_repo(Path(self.workspace_dir))
        self.stop()
        await asyncio.sleep(0.4)
        return self.start()

    # ---------------------------------------------------------------- input
    def send_input(self, text: str):
        if self.master_fd is None:
            raise RuntimeError("Aider is not running. Start it first.")
        stripped = text.rstrip("\n")
        if "\n" in stripped:
            # A raw keystroke feed can't distinguish "Enter to submit" from
            # "Enter as part of a multi-line message" -- each embedded \n
            # would otherwise submit that line immediately on its own. Aider
            # supports exactly this case via its documented multiline input
            # syntax: a line starting with `{tag` opens multiline entry, and
            # a matching `tag}` line closes and submits it as one message.
            payload = "{aiconsole\n" + stripped + "\naiconsole}\n"
        else:
            payload = stripped + "\n"
        os.write(self.master_fd, payload.encode())
        self._processing = True
        self.status.status = "running"

    def write_raw_bytes(self, data: bytes):
        """Passthrough for real terminal keystrokes typed directly into the
        xterm.js view (arrow keys, Ctrl-C, tab, etc.) -- sent exactly as
        typed, unlike send_input which appends a newline for prompt-style
        submission."""
        if self.master_fd is None:
            return
        os.write(self.master_fd, data)
        # A bare keystroke (e.g. arrow key while browsing history) isn't
        # necessarily a submitted request, so we don't force "processing"
        # here -- only an actual Enter-terminated line reliably means that.
        if data in (b"\r", b"\n"):
            self._processing = True
            self.status.status = "running"

    def send_interrupt(self):
        if self.master_fd is None:
            raise RuntimeError("Aider is not running.")
        os.write(self.master_fd, b"\x03")
        self._processing = False
        self.status.task_running = False
        self.status.pending_question = None
        self.status.status = "idle"

    def add_file(self, rel_path: str):
        self.send_input(f"/add {rel_path}")

    def drop_file(self, rel_path: str):
        self.send_input(f"/drop {rel_path}")

    def clear_chat(self):
        self.send_input("/clear")

    def request_tokens(self):
        self.send_input("/tokens")

    def set_mode(self, mode: str):
        self.status.mode = mode
        self.send_input(f"/chat-mode {mode}")

    def set_model(self, model: str):
        self.status.model = model
        self.send_input(f"/model {model}")

    def answer_question(self, text: str):
        self.status.pending_question = None
        self.send_input(text)  # already sets _processing=True and status='running'
        self._schedule(self.broadcast({"type": "status", "data": self.get_status()}))

    # ------------------------------------------------------------ task lifecycle (supervised)
    def start_task(self, text: str, files: list[str]) -> dict:
        if self.master_fd is None:
            raise RuntimeError("Aider is not running. Start it first.")
        if self.status.task_running:
            raise RuntimeError("A task is already running. Wait for it to finish or stop it.")

        for f in files:
            if f not in self.attached_files:
                self.add_file(f)

        self._task_head_before = git_utils.current_head(Path(self.workspace_dir))
        self._task_files = list(files) if files else list(self.attached_files)
        self.file_progress = {f: "pending" for f in self._task_files}
        self.status.supervised = True
        self.status.task_running = True
        self.status.pending_question = None
        self._task_done_event = asyncio.Event()
        self.send_input(text)  # sets _processing=True and status='running'
        self._schedule(self.broadcast({"type": "status", "data": self.get_status()}))
        self._schedule(self.broadcast({"type": "file_progress", "data": dict(self.file_progress)}))
        return self.get_status()

    async def wait_for_task_done(self, timeout: float = 300.0) -> dict:
        """Blocks until the current task finishes (or a question comes up
        that needs an answer), then returns the diff. Used by the isolated
        Modularization/Test-Gen tool sessions so their HTTP endpoint can
        return the finished result directly, instead of the caller having to
        watch a separate live status feed."""
        if not self._task_done_event:
            raise RuntimeError("No task is running on this session.")
        await asyncio.wait_for(self._task_done_event.wait(), timeout=timeout)
        return self._last_task_diff or {"changedFiles": [], "diff": "", "commits": []}

    def stop_task(self):
        self.send_interrupt()  # sets _processing=False and status='idle'
        self.status.task_running = False
        if self._task_done_event:
            self._last_task_diff = {"changedFiles": [], "diff": "", "commits": [], "stopped": True}
            self._task_done_event.set()
        self._schedule(self.broadcast({"type": "status", "data": self.get_status()}))

    def _update_modified_files_log(self):
        if not self._session_head_start:
            return
        diff = git_utils.diff_since(Path(self.workspace_dir), self._session_head_start)
        if not diff["changedFiles"]:
            return
        changed = False
        now = time.time()
        latest_commit = diff["commits"][0] if diff["commits"] else None
        progress_changed = False
        for entry in diff["changedFiles"]:
            path = entry["path"]
            prev = self.modified_files.get(path)
            if not prev or prev["status"] != entry["status"]:
                changed = True
            self.modified_files[path] = {
                "path": path,
                "status": entry["status"],
                "changedAt": now,
                "commit": latest_commit,
            }
            if path in self.file_progress and self.file_progress[path] != "done":
                self.file_progress[path] = "done"
                progress_changed = True
        if changed:
            self._schedule(self.broadcast({"type": "modified_files", "data": self.get_modified_files()}))
        if progress_changed:
            self._schedule(self.broadcast({"type": "file_progress", "data": dict(self.file_progress)}))

    def _record_session_commits(self):
        """Capture commits produced since this session's last idle boundary.
        Other Aider processes can commit to the same repository, so this
        narrow capture is what gives Code Canvas process/session isolation."""
        if not self._recorded_head:
            return
        commits = git_utils.log_since(Path(self.workspace_dir), self._recorded_head)
        if commits:
            # log_since is newest first; retain chronological insertion order.
            for entry in reversed(commits):
                if entry["hash"] not in self._session_commits:
                    self._session_commits.append(entry["hash"])
        self._recorded_head = git_utils.current_head(Path(self.workspace_dir))

    def get_modified_files(self) -> list[dict]:
        return sorted(self.modified_files.values(), key=lambda e: e["path"])

    def get_file_versions(self, file_path: str) -> list[dict]:
        """Powers Code Canvas: every commit this session that touched
        `file_path`, each with that commit's diff for just this file."""
        if not self._session_head_start:
            return []
        return git_utils.file_versions_for_commits(Path(self.workspace_dir), self._session_commits, file_path)

    def get_file_content_at(self, file_path: str, commit_hash: str) -> Optional[str]:
        return git_utils.file_content_at_commit(Path(self.workspace_dir), commit_hash, file_path)

    def get_history(self) -> list[dict]:
        """Commits made since this Aider process started, most recent first --
        the raw material for the Version History panel's undo-by-stepping-back
        UI (each click of Undo walks one commit further back)."""
        if not self._session_head_start:
            return []
        return git_utils.log_since(Path(self.workspace_dir), self._session_head_start)

    def undo_last(self):
        """Native Aider /undo -- reverts only its own most recent commit.
        Calling it repeatedly steps back through history one change at a
        time, which is the only safe direction (Aider won't undo commits it
        didn't make, and redoing forward isn't something Aider supports)."""
        self.send_input("/undo")

    def _complete_task(self):
        diff = (
            git_utils.diff_since(Path(self.workspace_dir), self._task_head_before)
            if self._task_head_before
            else {"changedFiles": [], "diff": "", "commits": []}
        )
        self.status.task_running = False
        self.status.status = "idle"
        self._record_session_commits()
        self._update_modified_files_log()
        self._last_task_diff = diff
        if self._task_done_event:
            self._task_done_event.set()
        self._schedule(self.broadcast({"type": "task_complete", "data": diff}))
        self._schedule(self.broadcast({"type": "status", "data": self.get_status()}))

    # ---------------------------------------------------------------- internals
    def _on_readable(self):
        try:
            chunk = os.read(self.master_fd, 65536)
        except (OSError, BlockingIOError):
            return
        if not chunk:
            return

        self._push_raw(chunk)
        self._schedule(self.broadcast({"type": "raw", "data": base64.b64encode(chunk).decode("ascii")}))

        clean = _strip_ansi(chunk.decode(errors="replace"))
        self._clean_tail = (self._clean_tail + clean)[-4000:]

        changed = False
        for m in ADDED_RE.finditer(clean):
            f = m.group(1).strip()
            if f not in self.attached_files:
                changed = True
            self.attached_files.add(f)
        for m in REMOVED_RE.finditer(clean):
            f = m.group(1).strip()
            if f in self.attached_files:
                changed = True
            self.attached_files.discard(f)
        if changed:
            self._schedule(self.broadcast({"type": "files", "data": sorted(self.attached_files)}))

        tokens = _parse_tokens(clean)
        if tokens:
            self.tokens_summary = tokens
            self._schedule(self.broadcast({"type": "tokens", "data": tokens}))

        for pattern, label in PHASE_PATTERNS:
            if pattern.search(clean):
                if not self.phase_timeline or self.phase_timeline[-1]["label"] != label:
                    self.phase_timeline.append({"label": label, "at": time.time()})
                    self.phase_timeline = self.phase_timeline[-20:]
                self._schedule(self.broadcast({"type": "phase", "data": label}))
                break

        # Per-file progress: best-effort detection of which task file is
        # currently being touched. The authoritative "done" signal is always
        # the git commit (see _update_modified_files_log) -- this only
        # provides the earlier "editing" state for a live checklist.
        if self._task_files:
            progress_changed = False
            for m in FILE_ACTIVITY_RE.finditer(clean):
                f = m.group(1).strip().rstrip(".:,")
                if f in self.file_progress and self.file_progress[f] == "pending":
                    self.file_progress[f] = "editing"
                    progress_changed = True
            if progress_changed:
                self._schedule(self.broadcast({"type": "file_progress", "data": dict(self.file_progress)}))

        # Transcript: filter out diff hunks and Aider's own system chatter,
        # keep only what looks like the model's actual prose explanation, and
        # stream that to Supervised Mode as chat-style bubbles.
        prose_lines = [
            line for line in clean.split("\n")
            if line.strip() and not DIFF_LINE_RE.match(line) and not SYSTEM_LINE_RE.match(line)
        ]
        if prose_lines:
            prose_text = "\n".join(prose_lines)
            self._schedule(self.broadcast({"type": "transcript", "data": prose_text}))

        if self._idle_handle:
            self._idle_handle.cancel()
        self._idle_handle = self._loop.call_later(0.6, self._on_idle)

        # Only reflect "running" if we're actually processing something we
        # sent. Boot chatter, or any other incidental output, must never
        # make the UI say Aider is busy when nothing was asked of it.
        if self.status.status != "waiting_input" and self._processing:
            self.status.status = "running"

    def _on_idle(self):
        """Fires ~600ms after output stops flowing. This is a silence-based
        signal (like v3): if nothing new has arrived in that window, we treat
        Aider as done with whatever it was doing. We intentionally do NOT
        require matching Aider's literal idle-prompt text here -- real Aider's
        exact prompt formatting varies enough (across versions/modes) that a
        strict regex reliably failed to match it, which left status stuck on
        "starting"/"running" forever and, as a side effect, also prevented the
        modified-files log and version history from ever updating (both are
        only recomputed on this idle transition)."""
        question = _parse_question(self._clean_tail)
        if question:
            self.status.status = "waiting_input"
            self.status.pending_question = question
            self._processing = False
            self._schedule(self.broadcast({"type": "question", "data": question}))
            self._schedule(self.broadcast({"type": "status", "data": self.get_status()}))
            return

        self._processing = False
        if self.status.task_running:
            # A short silent gap is normal while a local model is thinking.
            # Hidden tool tasks must not return "no file generated" merely
            # because that gap happened before Aider finished. A committed
            # edit is authoritative; for a legitimate no-op we also accept
            # Aider's plain idle prompt.
            head_changed = self._task_head_before and git_utils.current_head(Path(self.workspace_dir)) != self._task_head_before
            if head_changed or IDLE_PROMPT_RE.search(self._clean_tail):
                self._complete_task()
            return

        if self.status.status in ("running", "starting"):
            self.status.status = "idle"
            self._record_session_commits()
            self._update_modified_files_log()
        self._schedule(self.broadcast({"type": "status", "data": self.get_status()}))

    def _wait_for_exit(self):
        pid = self.pid
        if not pid:
            return
        try:
            _, exit_status = os.waitpid(pid, 0)
        except ChildProcessError:
            return
        code = os.WEXITSTATUS(exit_status) if os.WIFEXITED(exit_status) else -1
        if self._loop:
            self._loop.call_soon_threadsafe(self._on_exit, code)

    def _on_exit(self, code: int):
        if self.master_fd is not None:
            try:
                self._loop.remove_reader(self.master_fd)
            except Exception:
                pass
            try:
                os.close(self.master_fd)
            except OSError:
                pass
        self.master_fd = None
        self.pid = None
        self.status.task_running = False
        if code == 0:
            self.status.status = "stopped"
        else:
            self.status.status = "crashed"
            self.status.last_error = f"Aider process exited unexpectedly (code {code})"
        msg = f"\r\n\x1b[2m[process] Aider process ended (exit code {code}).\x1b[0m\r\n".encode()
        self._push_raw(msg)
        self._schedule(self.broadcast({"type": "raw", "data": base64.b64encode(msg).decode("ascii")}))
        self._schedule(self.broadcast({"type": "status", "data": self.get_status()}))

    def _push_raw(self, chunk: bytes):
        self._raw_buffer.append(chunk)
        if len(self._raw_buffer) > self._max_buffer:
            self._raw_buffer.pop(0)

    def _schedule(self, coro):
        if self._loop:
            self._loop.create_task(coro)
