"""
"How to Fix" for a single static-analysis issue - the preview-first
replacement for the old auto-applying "Fix with AI" button. (Fix All still
uses the auto-applying quick_fix.fix_issue for bulk operations - that
behavior is unchanged.)

Unlike quick_fix.fix_issue (small window of context, writes immediately),
this sends Ollama the ENTIRE file as context so the model can reason about
the full picture, but still asks for a small, line-ranged correction so the
diff stays focused. Nothing is written to disk by how_to_fix() - it only
returns an explanation and a diff for the UI to show in a canvas. The
result is only ever applied if/when the user explicitly clicks "Apply this
fix", which calls apply_fix() below with the EXACT previously-shown
start_line/end_line/fixed_code - no second Ollama call, so what gets
written is guaranteed to match what was previewed.
"""
from __future__ import annotations
import difflib
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Optional

from app.services import ollama_client, versioning


@dataclass
class HowToFixResult:
    explanation: str
    diff: str
    start_line: int
    end_line: int
    original_code: str
    fixed_code: str
    error: Optional[str] = None


def how_to_fix(
    original_file: Path, issue: Dict[str, Any], model: Optional[str] = None,
) -> HowToFixResult:
    full_text = original_file.read_text(errors="replace")
    lines = full_text.splitlines(keepends=True)
    fallback_line = max(1, min(issue.get("line") or 1, max(len(lines), 1)))

    try:
        result = ollama_client.explain_how_to_fix(issue, full_text, original_file.name, model=model)
    except Exception as e:  # noqa: BLE001 - surface any Ollama/network failure to the UI, don't crash
        return HowToFixResult(
            explanation="", diff="", start_line=fallback_line, end_line=fallback_line,
            original_code="", fixed_code="", error=str(e),
        )

    explanation = result.get("explanation") or "No explanation returned."
    fixed_code = result.get("fixed_code") or ""

    start_line = result.get("start_line") or fallback_line
    end_line = result.get("end_line") or start_line
    try:
        start_line = int(start_line)
        end_line = int(end_line)
    except (TypeError, ValueError):
        start_line = end_line = fallback_line

    line_count = max(len(lines), 1)
    start_line = max(1, min(start_line, line_count))
    end_line = max(start_line, min(end_line, line_count))

    original_code = "".join(lines[start_line - 1:end_line])

    diff = ""
    if fixed_code.strip():
        fixed_for_diff = fixed_code if fixed_code.endswith("\n") else fixed_code + "\n"
        diff = "".join(difflib.unified_diff(
            original_code.splitlines(keepends=True),
            fixed_for_diff.splitlines(keepends=True),
            fromfile=f"{original_file.name} (current)",
            tofile=f"{original_file.name} (suggested)",
        ))

    return HowToFixResult(
        explanation=explanation, diff=diff, start_line=start_line, end_line=end_line,
        original_code=original_code, fixed_code=fixed_code,
    )


def apply_fix(
    workspace: Path, original_file: Path, start_line: int, end_line: int,
    fixed_code: str, issue_summary: str,
) -> Dict[str, Any]:
    """Writes exactly the previously-previewed fixed_code into
    original_file at [start_line, end_line] (1-indexed, inclusive) and
    commits it to that file's version history - same commit-per-fix model
    as quick_fix.fix_issue, so it shows up in the file's History/diff views
    the same way.
    """
    filename = original_file.resolve().relative_to(workspace.resolve()).as_posix()
    versioning.ensure_baseline(workspace, filename)
    full_text = original_file.read_text(errors="replace")
    lines = full_text.splitlines(keepends=True)
    line_count = max(len(lines), 1)
    start_line = max(1, min(start_line, line_count))
    end_line = max(start_line, min(end_line, line_count))

    fixed = fixed_code if fixed_code.endswith("\n") else fixed_code + "\n"
    new_lines = lines[:start_line - 1] + [fixed] + lines[end_line:]
    new_text = "".join(new_lines)

    if new_text == full_text:
        return {"status": "ok", "diff": "", "commit": None, "error": None}

    original_file.write_text(new_text)
    commit_hash = versioning.commit_file(workspace, filename, f"Applied fix: {issue_summary}")
    diff = (
        versioning.diff_for_commit(workspace, filename, commit_hash)
        if commit_hash else ""
    )
    return {"status": "ok", "diff": diff, "commit": commit_hash, "error": None}
