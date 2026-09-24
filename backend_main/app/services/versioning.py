"""
Lightweight version history for files edited in place by "Fix with AI" /
"Fix All".

We keep one git repo per workspace (separate from the throwaway repos
aider_runner creates for Modularization sessions). The very first time a
file is touched by an AI fix, its current content is committed as a
"baseline" so there's always something to diff against. Every fix after
that is its own commit, so:

  - the diff for a single fix is exactly `git show <that commit> -- file`
  - the full history of a file is `git log --follow -- file`
  - "diff against the original" is always available via the baseline commit

This is intentionally separate from any VCS the user's project might
already use - it lives in `<workspace>/.ac_history/` as its own repo, so it
never interferes with (or requires) a real project git repo.
"""
from __future__ import annotations
import subprocess
from pathlib import Path
from typing import List, Optional, TypedDict

HISTORY_DIRNAME = ".ac_history"


class CommitInfo(TypedDict):
    hash: str
    short_hash: str
    message: str
    date: str


def _history_dir(workspace: Path) -> Path:
    d = workspace / HISTORY_DIRNAME
    d.mkdir(exist_ok=True)
    return d


def _git(workspace: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", *args], cwd=_history_dir(workspace),
        capture_output=True, text=True, check=check,
    )


def ensure_repo(workspace: Path) -> None:
    hist = _history_dir(workspace)
    if not (hist / ".git").exists():
        _git(workspace, "init", "-q")
        _git(workspace, "config", "user.email", "aider-console@local")
        _git(workspace, "config", "user.name", "Aider Console")


def _sync_file_into_history(workspace: Path, filename: str) -> None:
    """Mirror the current on-disk content of `filename` into the history repo."""
    src = workspace / filename
    dest = _history_dir(workspace) / filename
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(src.read_bytes())


def ensure_baseline(workspace: Path, filename: str) -> None:
    """Commit the file's current content as a baseline if it has no history yet."""
    ensure_repo(workspace)
    existing = _git(workspace, "log", "--oneline", "--", filename, check=False)
    if existing.returncode == 0 and existing.stdout.strip():
        return  # already tracked
    _sync_file_into_history(workspace, filename)
    _git(workspace, "add", "--", filename)
    _git(workspace, "commit", "-q", "-m", f"baseline: {filename}", "--allow-empty")


def commit_file(workspace: Path, filename: str, message: str) -> Optional[str]:
    """Snapshot the file's current on-disk content as a new commit.
    Returns the commit hash, or None if nothing actually changed.
    """
    ensure_repo(workspace)
    _sync_file_into_history(workspace, filename)
    _git(workspace, "add", "--", filename)
    diff = _git(workspace, "diff", "--cached", "--quiet", "--", filename, check=False)
    if diff.returncode == 0:
        return None  # nothing changed
    _git(workspace, "commit", "-q", "-m", message)
    rev = _git(workspace, "rev-parse", "HEAD")
    return rev.stdout.strip()


def diff_for_commit(workspace: Path, filename: str, commit_hash: str) -> str:
    """The diff introduced by a single commit for one file."""
    result = _git(workspace, "show", "--no-color", commit_hash, "--", filename, check=False)
    return result.stdout


def diff_range(workspace: Path, filename: str, from_ref: str, to_ref: str = "HEAD") -> str:
    """Diff between two commits (or a commit and 'HEAD') for one file."""
    result = _git(workspace, "diff", "--no-color", from_ref, to_ref, "--", filename, check=False)
    return result.stdout


def diff_against_baseline(workspace: Path, filename: str) -> str:
    """Diff from the very first tracked version of the file to its current state."""
    log = _git(workspace, "log", "--reverse", "--format=%H", "--", filename, check=False)
    hashes = [h for h in log.stdout.splitlines() if h.strip()]
    if not hashes:
        return ""
    return diff_range(workspace, filename, hashes[0], "HEAD")


def file_history(workspace: Path, filename: str) -> List[CommitInfo]:
    """Newest-first commit list for one file."""
    hist_repo = _history_dir(workspace)
    if not (hist_repo / ".git").exists():
        return []
    result = _git(
        workspace, "log", "--format=%H|%h|%ad|%s", "--date=iso-strict", "--", filename,
        check=False,
    )
    out: List[CommitInfo] = []
    for line in result.stdout.splitlines():
        if not line.strip():
            continue
        full, short, date, msg = line.split("|", 3)
        out.append(CommitInfo(hash=full, short_hash=short, message=msg, date=date))
    return out
