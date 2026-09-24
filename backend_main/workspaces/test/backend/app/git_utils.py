"""
Aider auto-commits after each successful edit (unless told not to). We lean
on that: rather than trying to parse "changed files" out of terminal text,
we snapshot the git HEAD before a supervised task starts and diff against
HEAD after it finishes. This is far more reliable than text-scraping.
"""

import subprocess
from pathlib import Path


def _run(args, cwd) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", *args], cwd=cwd, capture_output=True, text=True, timeout=15
    )


def ensure_repo(workspace_dir: Path):
    if (workspace_dir / ".git").exists():
        return
    _run(["init"], workspace_dir)
    _run(["config", "user.email", "aider-console@localhost"], workspace_dir)
    _run(["config", "user.name", "Aider Console"], workspace_dir)
    # Empty initial commit so `git diff <head>..HEAD` always has a valid
    # base to compare against, even before Aider makes its first commit.
    _run(["commit", "--allow-empty", "-m", "Initial commit (workspace created)"], workspace_dir)


def current_head(workspace_dir: Path) -> str | None:
    res = _run(["rev-parse", "HEAD"], workspace_dir)
    if res.returncode != 0:
        return None
    return res.stdout.strip()


def log_since(workspace_dir: Path, before_head: str) -> list:
    """Commits made since `before_head`, most recent first -- each with hash,
    subject, timestamp, and which files it touched. Powers Version History."""
    after_head = current_head(workspace_dir)
    if not before_head or not after_head or before_head == after_head:
        return []
    res = _run(["log", "--pretty=format:%H|%h|%ct|%s", f"{before_head}..{after_head}"], workspace_dir)
    entries = []
    for line in res.stdout.splitlines():
        parts = line.split("|", 3)
        if len(parts) != 4:
            continue
        full_hash, short_hash, ts, subject = parts
        files_res = _run(["show", "--name-status", "--pretty=format:", full_hash], workspace_dir)
        files = []
        for fline in files_res.stdout.splitlines():
            fparts = fline.split("\t")
            if len(fparts) >= 2:
                files.append({"status": fparts[0], "path": fparts[-1]})
        entries.append({
            "hash": full_hash,
            "shortHash": short_hash,
            "timestamp": int(ts),
            "subject": subject,
            "files": files,
        })
    return entries  # already most-recent-first, since `git log` orders that way


def file_versions(workspace_dir: Path, before_head: str, file_path: str) -> list:
    """Every commit since `before_head` that touched `file_path`, most recent
    first, each with that commit's diff for JUST this file. This is the data
    model behind Code Canvas: pick a file, browse its versions, see what
    changed at each step -- all derived from real git history rather than
    scraped from terminal text, same philosophy as the rest of this app's
    diffing."""
    entries = log_since(workspace_dir, before_head)
    versions = []
    for entry in entries:
        touched = any(f["path"] == file_path for f in entry["files"])
        if not touched:
            continue
        diff_res = _run(["show", "--format=", entry["hash"], "--", file_path], workspace_dir)
        versions.append({
            "hash": entry["hash"],
            "shortHash": entry["shortHash"],
            "timestamp": entry["timestamp"],
            "subject": entry["subject"],
            "diff": diff_res.stdout,
        })
    return versions  # already most-recent-first (log_since preserves git log order)


def file_content_at_commit(workspace_dir: Path, commit_hash: str, file_path: str) -> str | None:
    """Full file content as it existed at a specific commit (for Code
    Canvas's "view full snapshot" mode, not just the diff)."""
    res = _run(["show", f"{commit_hash}:{file_path}"], workspace_dir)
    if res.returncode != 0:
        return None
    return res.stdout


def diff_since(workspace_dir: Path, before_head: str) -> dict:
    """Returns changed files (name-status) + full unified diff + commit
    subjects made since `before_head`. Safe to call even if nothing changed."""
    after_head = current_head(workspace_dir)
    if not before_head or not after_head or before_head == after_head:
        return {"changedFiles": [], "diff": "", "commits": [], "headBefore": before_head, "headAfter": after_head}

    name_status = _run(["diff", "--name-status", f"{before_head}..{after_head}"], workspace_dir)
    changed_files = []
    for line in name_status.stdout.splitlines():
        parts = line.split("\t")
        if len(parts) >= 2:
            changed_files.append({"status": parts[0], "path": parts[-1]})

    diff_text = _run(["diff", f"{before_head}..{after_head}"], workspace_dir).stdout

    log = _run(["log", "--oneline", f"{before_head}..{after_head}"], workspace_dir)
    commits = [l for l in log.stdout.splitlines() if l.strip()]

    return {
        "changedFiles": changed_files,
        "diff": diff_text,
        "commits": commits,
        "headBefore": before_head,
        "headAfter": after_head,
    }
