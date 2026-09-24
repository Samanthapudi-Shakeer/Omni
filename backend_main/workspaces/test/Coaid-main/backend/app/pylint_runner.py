"""
Static analysis via pylint, run directly as a subprocess -- deliberately NOT
routed through Aider's PTY. This is a plain tool invocation with no LLM
involved; only the follow-up "auto-fix" step (if requested) goes through
Aider, since that's the part that actually needs an editing-capable model.
"""

import json
import subprocess
from pathlib import Path

from .workspace_fs import safe_resolve


def run_pylint(workspace_dir: Path, file_path: str, timeout: int = 30) -> dict:
    try:
        abs_path = safe_resolve(workspace_dir, file_path)
    except ValueError as exc:
        return {"findings": [], "raw": "", "error": str(exc)}
    if not abs_path.exists() or not (abs_path.is_file() or abs_path.is_dir()):
        return {"findings": [], "raw": "", "error": f"Path not found: {file_path}"}

    try:
        res = subprocess.run(
            ["pylint", "--output-format=json", "--exit-zero", str(abs_path)],
            cwd=workspace_dir, capture_output=True, text=True, timeout=timeout,
        )
    except FileNotFoundError:
        return {"findings": [], "raw": "", "error": "pylint is not installed on this server."}
    except subprocess.TimeoutExpired:
        return {"findings": [], "raw": "", "error": "pylint timed out."}

    raw = res.stdout or res.stderr
    findings = []
    try:
        data = json.loads(res.stdout) if res.stdout.strip() else []
        for item in data:
            findings.append({
                "path": str(Path(item.get("path", file_path)).relative_to(workspace_dir)) if Path(item.get("path", file_path)).is_absolute() else item.get("path", file_path),
                "line": item.get("line"),
                "column": item.get("column"),
                "type": item.get("type"),       # convention|refactor|warning|error|fatal
                "symbol": item.get("symbol"),
                "message": item.get("message"),
                "messageId": item.get("message-id"),
            })
    except json.JSONDecodeError:
        # pylint prints plain text if something goes wrong before JSON output;
        # still return it as `raw` so the UI can show *something*.
        pass

    return {"findings": findings, "raw": raw, "error": None}
