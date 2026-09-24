"""
Runs the right static analyzer for a given file extension and normalizes
its output into a flat list of `Issue` dicts.

    .py                -> pylint
    .c .cc .cpp .h .hpp -> OCLint
    .html .htm          -> HTMLHint
    .java .js .jsx       -> PMD

Each `run_*` function returns `list[dict]` matching the `Issue` model
fields (file, line, column, severity, rule, message, tool). Callers are
responsible for turning those into `Issue` objects (adding the `id`).
"""
from __future__ import annotations
import json
import shutil
import subprocess
from pathlib import Path
from typing import List, Dict, Any

from app import config

EXT_TO_TOOL = {
    ".py": "pylint",
    ".c": "oclint",
    ".cc": "oclint",
    ".cpp": "oclint",
    ".cxx": "oclint",
    ".h": "oclint",
    ".hpp": "oclint",
    ".html": "htmlhint",
    ".htm": "htmlhint",
    ".java": "pmd",
    ".js": "pmd",
    ".jsx": "pmd",
}


class ToolNotAvailable(RuntimeError):
    """Raised when the required binary isn't installed on PATH."""


def detect_tool(filename: str) -> str:
    ext = Path(filename).suffix.lower()
    tool = EXT_TO_TOOL.get(ext)
    if not tool:
        raise ValueError(f"No static analysis tool configured for extension '{ext}'")
    return tool


def _require(binary: str):
    if shutil.which(binary) is None:
        raise ToolNotAvailable(
            f"'{binary}' was not found on PATH. Install it or set the "
            f"corresponding AC_*_BIN env var to point at it."
        )


# --------------------------------------------------------------- pylint
_PYLINT_SEVERITY = {
    "fatal": "error",
    "error": "error",
    "warning": "warning",
    "convention": "convention",
    "refactor": "refactor",
    "info": "info",
}


def run_pylint(file_path: Path) -> List[Dict[str, Any]]:
    _require(config.PYLINT_BIN)
    cmd = [config.PYLINT_BIN, "--output-format=json", str(file_path)]
    proc = subprocess.run(
        cmd, capture_output=True, text=True, timeout=config.LINTER_TIMEOUT_SECONDS
    )
    # pylint exits non-zero whenever it finds *any* issue - that's expected.
    raw = proc.stdout.strip()
    if not raw:
        return []
    try:
        entries = json.loads(raw)
    except json.JSONDecodeError:
        return []
    issues = []
    for e in entries:
        issues.append({
            "file": file_path.name,
            "line": e.get("line", 0),
            "column": e.get("column", 0),
            "severity": _PYLINT_SEVERITY.get(e.get("type", "warning"), "warning"),
            "rule": e.get("symbol") or e.get("message-id", "pylint"),
            "message": e.get("message", ""),
            "tool": "pylint",
        })
    return issues


# --------------------------------------------------------------- oclint
def run_oclint(file_path: Path) -> List[Dict[str, Any]]:
    _require(config.OCLINT_BIN)
    report_path = file_path.with_suffix(file_path.suffix + ".oclint.json")
    cmd = [
        config.OCLINT_BIN,
        str(file_path),
        f"-report-type=json",
        f"-o={report_path}",
        "--",
        "-c",  # compile only, no linking needed for analysis
    ]
    subprocess.run(
        cmd, capture_output=True, text=True, timeout=config.LINTER_TIMEOUT_SECONDS
    )
    if not report_path.exists():
        return []
    try:
        data = json.loads(report_path.read_text())
    finally:
        report_path.unlink(missing_ok=True)

    issues = []
    for f in data.get("files", []):
        fname = Path(f.get("path", file_path.name)).name
        for v in f.get("violations", []):
            severity = "error" if v.get("priority") == 1 else (
                "warning" if v.get("priority") == 2 else "refactor"
            )
            issues.append({
                "file": fname,
                "line": v.get("startLine", 0),
                "column": v.get("startColumn", 0),
                "severity": severity,
                "rule": v.get("rule", "oclint"),
                "message": v.get("message", ""),
                "tool": "oclint",
            })
    return issues


# ------------------------------------------------------------- htmlhint
def run_htmlhint(file_path: Path) -> List[Dict[str, Any]]:
    _require(config.HTMLHINT_BIN)
    cmd = [config.HTMLHINT_BIN, "--format=json", str(file_path)]
    proc = subprocess.run(
        cmd, capture_output=True, text=True, timeout=config.LINTER_TIMEOUT_SECONDS
    )
    raw = proc.stdout.strip()
    if not raw:
        return []
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return []
    issues = []
    # htmlhint json output: list of {file, messages: [...]}
    for entry in data:
        fname = Path(entry.get("file", file_path.name)).name
        for m in entry.get("messages", []):
            severity = "error" if m.get("type") == "error" else "warning"
            issues.append({
                "file": fname,
                "line": m.get("line", 0),
                "column": m.get("col", 0),
                "severity": severity,
                "rule": m.get("rule", {}).get("id", "htmlhint"),
                "message": m.get("message", ""),
                "tool": "htmlhint",
            })
    return issues


# ------------------------------------------------------------------ pmd
_PMD_LANG = {".java": "java", ".js": "javascript", ".jsx": "javascript"}


def run_pmd(file_path: Path) -> List[Dict[str, Any]]:
    _require(config.PMD_BIN)
    lang = _PMD_LANG.get(file_path.suffix.lower(), "java")
    # "quickstart" ruleset ships with PMD for both java + ecmascript
    ruleset = "rulesets/java/quickstart.xml" if lang == "java" else "rulesets/ecmascript/quickstart.xml"
    cmd = [
        config.PMD_BIN, "check",
        "-d", str(file_path),
        "-R", ruleset,
        "-f", "json",
        "--no-fail-on-violation",
    ]
    proc = subprocess.run(
        cmd, capture_output=True, text=True, timeout=config.LINTER_TIMEOUT_SECONDS
    )
    raw = proc.stdout.strip()
    if not raw:
        return []
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return []
    issues = []
    for f in data.get("files", []):
        fname = Path(f.get("filename", file_path.name)).name
        for v in f.get("violations", []):
            prio = v.get("priority", 3)
            severity = "error" if prio <= 1 else ("warning" if prio <= 3 else "refactor")
            issues.append({
                "file": fname,
                "line": v.get("beginline", 0),
                "column": v.get("begincolumn", 0),
                "severity": severity,
                "rule": v.get("rule", "pmd"),
                "message": v.get("description", ""),
                "tool": "pmd",
            })
    return issues


_RUNNERS = {
    "pylint": run_pylint,
    "oclint": run_oclint,
    "htmlhint": run_htmlhint,
    "pmd": run_pmd,
}


def analyze_file(file_path: Path) -> List[Dict[str, Any]]:
    """Detect the right tool for `file_path` and run it, returning normalized issues.

    Raises ToolNotAvailable / ValueError which the router turns into a
    per-file error instead of failing the whole batch.
    """
    tool = detect_tool(file_path.name)
    return _RUNNERS[tool](file_path)
