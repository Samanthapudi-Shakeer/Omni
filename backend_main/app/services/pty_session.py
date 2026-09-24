"""
Interactive, PTY-backed aider sessions - shared by Test Case Generation and
Modularization.

Both features genuinely want aider's normal interactive behavior: it may
ask "Add tests/test_foo.py to the chat? (Y)es/(N)o/...", and the developer
should answer that themselves in a real terminal, not have it auto-accepted
the way the old non-interactive `aider --yes-always` path did. So instead
of subprocess.run() with captured stdout, we fork a pseudo-terminal, exec
aider attached to the slave end, and let the frontend stream the master
end's output/input over a WebSocket - a minimal version of what tools like
ttyd/gotty do. See routers/pty.py for the WebSocket endpoint both features
share, and routers/testgen.py / routers/modularize.py for how each starts
a session with its own prompt.

Each session gets its own throwaway git repo under
    <workspace>/.ac_sessions/<kind>_<id>/
so nothing here touches the user's main workspace until the session ends,
at which point any new/changed files are copied back in.

Auto-answered prompts
----------------------
Aider sometimes asks a low-value confirmation that has nothing to do with
the actual task - e.g. "Open documentation url for more info? (Y)es/(N)o/
(D)on't ask again [Yes]:" whenever it prints an LLM warning. Since this is
a background PTY the user can't always be watching in real time, we
auto-answer a short list of known, harmless prompts like this one so the
session never silently stalls waiting on something the user didn't ask to
be bothered with. Anything else - "Add file to chat?", "Proceed?", etc. -
is left entirely to the user, same as running aider by hand.
"""
from __future__ import annotations
import fcntl
import os
import pty
import queue
import re
import select
import signal
import struct
import subprocess
import termios
import threading
import uuid
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from app import config

# (pattern to watch for in recent output, answer to type once matched).
# Matched against raw bytes (including ANSI codes) so keep patterns to a
# stable substring rather than anchoring on the exact prompt formatting.
_AUTO_ANSWERS: List[Tuple[re.Pattern, bytes]] = [
    (re.compile(rb"Open documentation url for more info", re.IGNORECASE), b"n\n"),
]
_AUTO_ANSWER_BUFFER_SIZE = 500  # bytes of recent output kept for matching


class PtySession:
    def __init__(self, session_id: str, workspace_dir: Path, session_dir: Path,
                 master_fd: int, pid: int):
        self.id = session_id
        self.workspace_dir = workspace_dir
        self.session_dir = session_dir
        self.master_fd = master_fd
        self.pid = pid
        self.output_queue: "queue.Queue[bytes]" = queue.Queue()
        self.closed = False
        self._match_buffer = b""
        self._answered = set()  # indices into _AUTO_ANSWERS already triggered this session
        self._reader_thread = threading.Thread(target=self._read_loop, daemon=True)
        self._reader_thread.start()

    def _read_loop(self):
        while not self.closed:
            try:
                ready, _, _ = select.select([self.master_fd], [], [], 0.2)
                if self.master_fd in ready:
                    data = os.read(self.master_fd, 4096)
                    if not data:
                        break
                    self.output_queue.put(data)
                    self._check_auto_answers(data)
            except OSError:
                break
        self.closed = True
        self.output_queue.put(b"")  # sentinel: end of stream

    def _check_auto_answers(self, data: bytes) -> None:
        self._match_buffer = (self._match_buffer + data)[-_AUTO_ANSWER_BUFFER_SIZE:]
        for idx, (pattern, answer) in enumerate(_AUTO_ANSWERS):
            if idx in self._answered:
                continue
            if pattern.search(self._match_buffer):
                self._answered.add(idx)
                try:
                    # Written to the master fd exactly like real user input -
                    # the pty's own line discipline echoes it back, so it's
                    # visible in the terminal (not silently swallowed), just
                    # not something the user had to type themselves.
                    os.write(self.master_fd, answer)
                except OSError:
                    pass

    def write(self, data: bytes) -> None:
        if self.closed:
            return
        try:
            os.write(self.master_fd, data)
        except OSError:
            pass

    def resize(self, rows: int, cols: int) -> None:
        try:
            fcntl.ioctl(self.master_fd, termios.TIOCSWINSZ, struct.pack("HHHH", rows, cols, 0, 0))
        except OSError:
            pass

    def terminate(self) -> None:
        try:
            os.kill(self.pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
        self.closed = True


_sessions: Dict[str, PtySession] = {}
_lock = threading.Lock()


def start_session(workspace_dir: Path, target_files: List[str], message: str, kind: str = "session") -> PtySession:
    session_id = uuid.uuid4().hex[:12]
    session_dir = workspace_dir / config.SESSIONS_DIRNAME / f"{kind}_{session_id}"
    session_dir.mkdir(parents=True, exist_ok=True)

    for rel in target_files:
        src = workspace_dir / rel
        if src.exists():
            (session_dir / Path(rel).name).write_bytes(src.read_bytes())

    subprocess.run(["git", "init", "-q"], cwd=session_dir)
    subprocess.run(["git", "config", "user.email", "aider-console@local"], cwd=session_dir)
    subprocess.run(["git", "config", "user.name", "Aider Console"], cwd=session_dir)
    subprocess.run(["git", "add", "-A"], cwd=session_dir)
    subprocess.run(["git", "commit", "-q", "-m", "baseline", "--allow-empty"], cwd=session_dir)

    file_names = [Path(f).name for f in target_files]

    pid, master_fd = pty.fork()
    if pid == 0:
        # ---- child process: becomes `aider`, attached to the pty slave ----
        try:
            os.chdir(session_dir)
            os.environ["TERM"] = "xterm-256color"
            os.environ["OLLAMA_API_BASE"] = config.OLLAMA_BASE_URL
            cmd = [
                "aider",
                "--model", config.AIDER_MODEL,
                "--no-auto-commits",
                "--no-check-update",
                "--message", message,
                *file_names,
            ]
            os.execvp(cmd[0], cmd)
        except Exception as e:  # noqa: BLE001 - report the failure into the pty before exiting
            try:
                os.write(2, f"Failed to launch aider: {e}\n".encode())
            except OSError:
                pass
            os._exit(1)
    else:
        session = PtySession(session_id, workspace_dir, session_dir, master_fd, pid)
        with _lock:
            _sessions[session_id] = session
        return session


def get_session(session_id: str) -> Optional[PtySession]:
    with _lock:
        return _sessions.get(session_id)


def drop_session(session_id: str) -> None:
    with _lock:
        _sessions.pop(session_id, None)


def changed_files(session: PtySession) -> List[str]:
    status = subprocess.run(
        ["git", "status", "--porcelain"], cwd=session.session_dir,
        capture_output=True, text=True,
    )
    return [line[3:].strip() for line in status.stdout.splitlines() if line.strip()]


def copy_back_changes(session: PtySession) -> List[Path]:
    """Copy every new/changed file from the isolated session repo back into
    the real workspace - this is how generated/modified files end up
    somewhere the user can see them once the session ends.
    """
    copied: List[Path] = []
    for rel in changed_files(session):
        src = session.session_dir / rel
        if not src.exists() or src.is_dir():
            continue
        dest = session.workspace_dir / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(src.read_bytes())
        copied.append(dest)
    return copied
