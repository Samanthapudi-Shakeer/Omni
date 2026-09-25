"""Semgrep static analysis runner.

Semgrep is intentionally invoked without a style formatter or a long-line
rule.  Its findings are semantic/security findings from the selected ruleset,
not generic formatting noise.
"""

import json
import subprocess
from pathlib import Path

from .workspace_fs import safe_resolve


def run_semgrep(workspace_dir: Path, target: str, timeout: int = 90) -> dict:
    try:
        abs_target = safe_resolve(workspace_dir, target)
    except ValueError as exc:
        return {"findings": [], "raw": "", "error": str(exc)}
    if not abs_target.exists():
        return {"findings": [], "raw": "", "error": f"Path not found: {target}"}

    try:
        result = subprocess.run(
            ["semgrep", "scan", "--config", "auto", "--json", "--quiet", str(abs_target)],
            cwd=workspace_dir, capture_output=True, text=True, timeout=timeout,
        )
    except FileNotFoundError:
        return {"findings": [], "raw": "", "error": "semgrep is not installed on this server."}
    except subprocess.TimeoutExpired:
        return {"findings": [], "raw": "", "error": "semgrep timed out."}

    raw = result.stdout or result.stderr
    try:
        report = json.loads(result.stdout) if result.stdout.strip() else {"results": []}
    except json.JSONDecodeError:
        return {"findings": [], "raw": raw, "error": "Semgrep returned invalid JSON."}

    findings = []
    for item in report.get("results", []):
        extra = item.get("extra", {})
        start = item.get("start", {})
        findings.append({
            "path": str(Path(item.get("path", "")).relative_to(workspace_dir)) if Path(item.get("path", "")).is_absolute() else item.get("path", target),
            "line": start.get("line"), "column": start.get("col"),
            "type": (extra.get("severity") or "warning").lower(),
            "symbol": item.get("check_id", "semgrep"),
            "message": extra.get("message", "Semgrep finding"),
            "messageId": item.get("check_id"),
        })
    return {"findings": findings, "raw": raw, "error": None}
