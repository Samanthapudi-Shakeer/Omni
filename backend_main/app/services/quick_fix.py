"""
"Fix with AI" for a single static-analysis issue.

Unlike Modularization (which genuinely needs an aider session to reason
about a whole file and create new module files), a single-issue fix only
needs two things: the issue itself, and a small window of the code around
it. So instead of an aider session we make one direct, stateless call to
Ollama's /api/generate with exactly that - no chat history, no `context`
array carried forward, nothing shared with any other fix.

Isolation model: each call to `fix_issue()` below is triggered from its own
background job (see routers/analysis.py + services/jobs.py), and each job
runs on its own daemon thread. So "new thread, new context" falls out
naturally: thread T1 fixing issue A never shares model state with thread T2
fixing issue B, even if both are running at the same time.

The fix is written DIRECTLY into the original file (no fix_<name> copy).
Before the first-ever fix on a file we commit its current content as a
baseline in the workspace's version history (see services/versioning.py),
then every fix is its own commit - so `diff` here is always available both
as "what this specific fix changed" and, via the history endpoints, "what
changed since any earlier version".
"""
from __future__ import annotations
import difflib
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Dict, Optional

from app import config
from app.services import ollama_client, versioning

ProgressCB = Callable[[str], None]


def _noop(_msg: str) -> None:
    pass


@dataclass
class QuickFixResult:
    ok: bool
    diff: str                    # diff for just this fix (also == the git commit's diff)
    model_output: str
    attempts: int = 1
    commit: Optional[str] = None
    error: Optional[str] = None


_CODE_FENCE_RE = re.compile(r"^```[a-zA-Z0-9_+-]*\n(.*?)\n?```$", re.DOTALL)


def _strip_code_fence(text: str) -> str:
    """Models sometimes wrap the answer in ```lang ... ``` despite being told
    not to - strip that if present, otherwise return as-is."""
    m = _CODE_FENCE_RE.match(text.strip())
    return m.group(1) if m else text.strip("\n")


def _window(lines: list[str], line_no: int, context: int) -> tuple[int, int]:
    start = max(1, line_no - context)
    end = min(len(lines), line_no + context)
    return start, end


def fix_issue(
    workspace: Path, original_file: Path, issue: Dict[str, Any], progress_cb: ProgressCB = _noop,
    extra_instructions: Optional[str] = None,
) -> QuickFixResult:
    """Fix one issue and write the result straight into `original_file`.

    Always re-reads the file from disk (rather than caching it), so calling
    this repeatedly for several issues in the same file - e.g. from "Fix
    All" - picks up each previous fix's edits.
    """
    filename = original_file.resolve().relative_to(workspace.resolve()).as_posix()
    versioning.ensure_baseline(workspace, filename)

    progress_cb(f"Reading {original_file.name}…")
    original_text = original_file.read_text(errors="replace")
    lines = original_text.splitlines(keepends=True)
    line_no = issue.get("line") or 1

    attempt = 0
    last_error: Optional[str] = None
    for context in (config.FIX_CONTEXT_LINES, config.FIX_CONTEXT_LINES_RETRY):
        attempt += 1
        start, end = _window(lines, line_no, context)
        snippet = "".join(lines[start - 1:end])

        if attempt == 1:
            progress_cb(f"Sending lines {start}-{end} to Ollama as an isolated fix request…")
        else:
            progress_cb(f"Retrying with a smaller code window (lines {start}-{end})…")

        try:
            raw = ollama_client.fix_snippet(
                issue, snippet, start, end, original_file.name,
                extra_instructions=extra_instructions,
            )
        except Exception as e:  # noqa: BLE001 - network/HTTP errors from the Ollama call
            last_error = str(e)
            progress_cb(f"Ollama request failed: {last_error}")
            continue

        fixed_snippet = _strip_code_fence(raw)
        if not fixed_snippet.strip():
            last_error = "Model returned an empty fix"
            progress_cb(last_error)
            continue

        if not fixed_snippet.endswith("\n") and snippet.endswith("\n"):
            fixed_snippet += "\n"

        new_lines = lines[:start - 1] + [fixed_snippet] + lines[end:]
        new_text = "".join(new_lines)

        if new_text == original_text:
            progress_cb("Model returned no actual change.")
            return QuickFixResult(
                ok=True, diff="", model_output=raw, attempts=attempt, commit=None,
            )

        progress_cb(f"Writing fix directly into {original_file.name}…")
        original_file.write_text(new_text)

        commit_msg = f"AI fix: {issue.get('rule', 'issue')} at line {issue.get('line', '?')} ({issue.get('tool', '')})"
        commit_hash = versioning.commit_file(workspace, filename, commit_msg)
        diff = (
            versioning.diff_for_commit(workspace, original_file.name, commit_hash)
            if commit_hash else
            "".join(difflib.unified_diff(
                lines, new_lines, fromfile=original_file.name, tofile=original_file.name,
            ))
        )

        progress_cb("Fix applied and committed to history.")
        return QuickFixResult(
            ok=True, diff=diff, model_output=raw, attempts=attempt, commit=commit_hash,
        )

    return QuickFixResult(
        ok=False, diff="", model_output="",
        attempts=attempt, error=last_error or "Fix failed for an unknown reason",
    )
