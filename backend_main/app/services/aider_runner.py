"""
Runs isolated, non-interactive `aider` CLI sessions.

"Isolated" here means: each call gets its own scratch git repo under
    <workspace>/.ac_sessions/<session_id>/
so aider's own auto-commits, .aider.chat.history.md, etc. never touch the
user's real workspace folder or its main terminal session state. We copy
only the file(s) the session needs into that scratch repo, run aider
non-interactively with --message / --yes, then copy the result back out.

For "Fix with AI": aider is pointed at a COPY of the file named
`fix_<original_name>` so the original is never touched, per the product
requirement.

For "Modularization": aider is pointed at the original filename inside the
scratch repo (so it can freely create new module files alongside it with
correct relative naming), and any new/changed files it produces are copied
back into the real workspace.

Token-limit handling
---------------------
Local models served via Ollama have a fixed context window. A long file +
repo map + growing chat history can blow past it mid-session. When that
happens we:
  1. Detect the token/context-limit error in aider's output.
  2. Report progress ("token limit hit, clearing context...") via the
     `progress_cb` callback so the caller (a background job) can surface it.
  3. Delete aider's on-disk chat history for that session - the on-disk
     equivalent of typing `/clear` - and re-run the same --message once
     more with a fresh context, up to `max_retries` times.
This never touches the target file's on-disk content, only aider's own
conversation state, so retries are safe to repeat.
"""
from __future__ import annotations
import re
import shutil
import subprocess
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, List, Optional

from app import config

ProgressCB = Callable[[str], None]


def _noop(_msg: str) -> None:
    pass


@dataclass
class AiderResult:
    ok: bool
    log: str
    diff: str
    changed_files: List[str]
    error: Optional[str] = None
    attempts: int = 1
    hit_token_limit: bool = False


_TOKEN_LIMIT_PATTERNS = [
    r"context length",
    r"context_length_exceeded",
    r"maximum context",
    r"context window",
    r"token limit",
    r"too many tokens",
    r"exceeds the model'?s? (max|maximum)",
    r"input length exceeds",
    r"reduce the length of the messages",
    r"prompt is too long",
]
_TOKEN_LIMIT_RE = re.compile("|".join(_TOKEN_LIMIT_PATTERNS), re.IGNORECASE)


def _looks_like_token_limit(text: str) -> bool:
    return bool(_TOKEN_LIMIT_RE.search(text))


def _new_session_dir(workspace: Path) -> Path:
    session_id = uuid.uuid4().hex[:12]
    session_dir = workspace / config.SESSIONS_DIRNAME / session_id
    session_dir.mkdir(parents=True, exist_ok=True)
    return session_dir


def _init_scratch_repo(session_dir: Path):
    subprocess.run(["git", "init", "-q"], cwd=session_dir, check=True)
    subprocess.run(["git", "config", "user.email", "aider-console@local"], cwd=session_dir, check=True)
    subprocess.run(["git", "config", "user.name", "Aider Console"], cwd=session_dir, check=True)


def _clear_aider_context(session_dir: Path):
    """On-disk equivalent of aider's `/clear` command: wipe its chat
    history / input history so the next run starts with a fresh context
    window, while leaving the target file(s) exactly as they are.
    """
    for name in (".aider.chat.history.md", ".aider.input.history", ".aider.tags.cache.v4"):
        p = session_dir / name
        if p.is_file():
            p.unlink()
        elif p.is_dir():
            shutil.rmtree(p, ignore_errors=True)


def _run_aider_once(session_dir: Path, target_files: List[str], message: str) -> tuple[int, str]:
    cmd = [
        "aider",
        "--model", config.AIDER_MODEL,
        "--yes-always",
        "--no-auto-commits",
        "--no-check-update",
        "--message", message,
        *target_files,
    ]
    try:
        proc = subprocess.run(
            cmd,
            cwd=session_dir,
            capture_output=True,
            text=True,
            timeout=config.AIDER_TIMEOUT_SECONDS,
        )
    except subprocess.TimeoutExpired as e:
        return -1, (e.stdout or "") + (e.stderr or "") + "\n[aider session timed out]"
    except FileNotFoundError:
        return -2, "'aider' CLI not found on PATH. Install with: pip install aider-chat"

    return proc.returncode, (proc.stdout or "") + "\n" + (proc.stderr or "")


def _run_aider(
    session_dir: Path,
    target_files: List[str],
    message: str,
    progress_cb: ProgressCB = _noop,
    max_retries: int = 2,
) -> AiderResult:
    _init_scratch_repo(session_dir)
    # Commit the starting state so `git diff` afterwards shows exactly what
    # aider changed.
    subprocess.run(["git", "add", "-A"], cwd=session_dir, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "baseline", "--allow-empty"], cwd=session_dir, check=True)

    full_log_parts: List[str] = []
    hit_token_limit = False
    attempt = 0
    returncode = 0

    while True:
        attempt += 1
        if attempt == 1:
            progress_cb("Starting isolated aider session…")
        else:
            progress_cb(f"Retrying (attempt {attempt}/{max_retries + 1}) with a cleared context…")

        returncode, log = _run_aider_once(session_dir, target_files, message)
        full_log_parts.append(f"----- attempt {attempt} -----\n{log}")

        if returncode == -2:
            progress_cb("aider CLI not found.")
            break

        if _looks_like_token_limit(log) and attempt <= max_retries:
            hit_token_limit = True
            progress_cb("Token limit hit — running /clear equivalent and retrying…")
            _clear_aider_context(session_dir)
            continue

        break

    if returncode == 0:
        progress_cb("aider session finished successfully.")
    elif returncode == -2:
        pass
    else:
        progress_cb(f"aider session finished with errors (exit code {returncode}).")

    full_log = "\n\n".join(full_log_parts)

    diff_proc = subprocess.run(
        ["git", "diff", "--no-color"], cwd=session_dir, capture_output=True, text=True
    )
    status_proc = subprocess.run(
        ["git", "status", "--porcelain"], cwd=session_dir, capture_output=True, text=True
    )
    changed_files = [
        line[3:].strip() for line in status_proc.stdout.splitlines() if line.strip()
    ]

    ok = returncode == 0
    error = None
    if returncode == -2:
        error = "'aider' CLI not found on PATH. Install with: pip install aider-chat"
    elif not ok:
        error = f"aider exited with code {returncode}" + (
            " after hitting the model's token limit repeatedly" if hit_token_limit else ""
        )

    return AiderResult(
        ok=ok, log=full_log, diff=diff_proc.stdout, changed_files=changed_files,
        error=error, attempts=attempt, hit_token_limit=hit_token_limit,
    )


def fix_issue(
    workspace: Path, original_file: Path, issue_summary: str,
    extra_instructions: str | None = None, progress_cb: ProgressCB = _noop,
) -> tuple[AiderResult, Path]:
    """Copy `original_file` to fix_<name> inside an isolated session repo,
    ask aider to fix the specific issue, then copy the result back into the
    real workspace (still named fix_<name>, original file is untouched).
    """
    progress_cb(f"Preparing isolated copy of {original_file.name}…")
    session_dir = _new_session_dir(workspace)
    fixed_name = f"fix_{original_file.name}"
    scratch_target = session_dir / fixed_name
    shutil.copy2(original_file, scratch_target)

    message = (
        "Fix ONLY the following static analysis finding in this file. "
        "Make the minimal correct change - do not refactor unrelated code, "
        "do not change the public behavior/interface unless required to fix "
        "the issue.\n\n"
        f"{issue_summary}\n"
    )
    if extra_instructions:
        message += f"\nAdditional instructions from the developer:\n{extra_instructions}\n"

    result = _run_aider(session_dir, [fixed_name], message, progress_cb=progress_cb)

    dest = workspace / fixed_name
    if scratch_target.exists():
        shutil.copy2(scratch_target, dest)
        progress_cb(f"Wrote result to {fixed_name} in the workspace.")

    return result, dest


def modularize_file(
    workspace: Path, original_file: Path, prompt: str, progress_cb: ProgressCB = _noop,
) -> tuple[AiderResult, List[Path]]:
    """Run a user-authored modularization prompt against a copy of the file
    inside an isolated session repo, then copy every new/changed file back
    into the real workspace (original file is left untouched; aider is
    instructed to create new module files rather than edit it in place, but
    we copy back whatever it actually produced so nothing is lost).
    """
    progress_cb(f"Preparing isolated copy of {original_file.name}…")
    session_dir = _new_session_dir(workspace)
    scratch_target = session_dir / original_file.name
    shutil.copy2(original_file, scratch_target)

    result = _run_aider(session_dir, [original_file.name], prompt, progress_cb=progress_cb)

    copied_back: List[Path] = []
    for rel in result.changed_files:
        src = session_dir / rel
        if not src.exists() or src.is_dir():
            continue
        # Never silently overwrite the original file in the real workspace -
        # if aider edited it in place, save that version as modularized_<name>
        # instead of clobbering the source of truth.
        if rel == original_file.name:
            dest = workspace / f"modularized_{original_file.name}"
        else:
            dest = workspace / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dest)
        copied_back.append(dest)

    if copied_back:
        progress_cb(f"Copied {len(copied_back)} new/changed file(s) back into the workspace.")

    return result, copied_back


DEFAULT_MODULARIZE_PROMPT = (
    "Analyze this file and split it into well-organized, cohesive modules "
    "based on single responsibility (e.g. separate data models, business "
    "logic, utilities/helpers, and any I/O or interface layer into their "
    "own files). Preserve all existing functionality and public "
    "interfaces exactly. Create new files as needed, update "
    "imports/includes accordingly, and add a short comment at the top of "
    "each new file explaining its purpose."
)
