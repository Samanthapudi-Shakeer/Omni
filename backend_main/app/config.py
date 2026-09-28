"""
Central configuration for the Aider Console backend.

Everything here can be overridden with environment variables so the same
code works whether Ollama / aider run on the host machine or in a
container.
"""
import os
from pathlib import Path

# Root folder that holds one sub-folder per workspace, e.g.
#   WORKSPACES_ROOT/test/calculator.cpp
#   WORKSPACES_ROOT/test/.ac_sessions/<session_id>/   <- isolated aider work
#   WORKSPACES_ROOT/test/.ac_reports/<timestamp>.txt  <- analysis reports
WORKSPACES_ROOT = Path(os.environ.get("AC_WORKSPACES_ROOT", Path(__file__).resolve().parent.parent / "workspaces"))
WORKSPACES_ROOT.mkdir(parents=True, exist_ok=True)

SESSIONS_DIRNAME = ".ac_sessions"
REPORTS_DIRNAME = ".ac_reports"

# --- Ollama -----------------------------------------------------------
OLLAMA_BASE_URL = os.environ.get("OLLAMA_BASE_URL", "http://localhost:11435").rstrip("/")
OLLAMA_MODEL = os.environ.get("OLLAMA_MODEL", "qwen2.5-coder:32b")

# SonarQube endpoints are selected automatically from the uploaded source
# files.  Keep the Python and native C/C++ credentials independent: many
# installations expose language-specific SonarQube instances, with the native
# instance commonly listening on port 9000.  The legacy SONAR_* names remain
# Python fallbacks so existing deployments continue to work during migration.
SONAR_PYTHON_URL = os.environ.get(
    "SONAR_PYTHON_URL", os.environ.get("SONAR_URL", "")
).rstrip("/")
SONAR_PYTHON_TOKEN = os.environ.get(
    "SONAR_PYTHON_TOKEN", os.environ.get("SONAR_TOKEN", "")
).strip()
SONAR_PYTHON_USERNAME = os.environ.get(
    "SONAR_PYTHON_USERNAME", os.environ.get("SONAR_USERNAME", "")
).strip()
SONAR_PYTHON_PASSWORD = os.environ.get(
    "SONAR_PYTHON_PASSWORD", os.environ.get("SONAR_PASSWORD", "")
).strip()

SONAR_C_CPP_URL = os.environ.get("SONAR_C_CPP_URL", "").rstrip("/")
SONAR_C_CPP_TOKEN = os.environ.get("SONAR_C_CPP_TOKEN", "").strip()
SONAR_C_CPP_USERNAME = os.environ.get("SONAR_C_CPP_USERNAME", "").strip()
SONAR_C_CPP_PASSWORD = os.environ.get("SONAR_C_CPP_PASSWORD", "").strip()

# Compatibility aliases for integrations that only ever scan Python files.
SONAR_URL = SONAR_PYTHON_URL
SONAR_TOKEN = SONAR_PYTHON_TOKEN
SONAR_USERNAME = SONAR_PYTHON_USERNAME
SONAR_PASSWORD = SONAR_PYTHON_PASSWORD
SONAR_SCANNER = os.environ.get(
    "SONAR_SCANNER",
    "/home/test7/sonar-scanner/bin/sonar-scanner",
)
JAVA_EXE = os.environ.get("JAVA_EXE", "/usr/bin/java")
SONAR_TIMEOUT_SECONDS = int(os.environ.get("AC_SONAR_TIMEOUT", "300"))

# --- aider --------------------------------------------------------------
# Model string aider expects when talking to a local Ollama server.
AIDER_MODEL = os.environ.get("AIDER_MODEL", f"ollama/{OLLAMA_MODEL}")

# Per-session/per-fix timeout so a stuck aider process can't hang a request
# forever.
AIDER_TIMEOUT_SECONDS = int(os.environ.get("AC_AIDER_TIMEOUT", "600"))

# --- Linter binaries (override if they're not on PATH) -----------------
PYLINT_BIN = os.environ.get("AC_PYLINT_BIN", "pylint")
OCLINT_BIN = os.environ.get("AC_OCLINT_BIN", "oclint")
HTMLHINT_BIN = os.environ.get("AC_HTMLHINT_BIN", "htmlhint")
PMD_BIN = os.environ.get("AC_PMD_BIN", "pmd")

LINTER_TIMEOUT_SECONDS = int(os.environ.get("AC_LINTER_TIMEOUT", "120"))

# --- Fix with AI (Static Analysis tab) ---------------------------------
# Lines of surrounding source code sent to Ollama as context for a single
# issue fix. Kept small on purpose - this is NOT a full-file/aider session,
# just the issue + a small window, sent as one isolated, stateless request.
FIX_CONTEXT_LINES = int(os.environ.get("AC_FIX_CONTEXT_LINES", "8"))
# If the first attempt errors out (e.g. the model still balks at the
# context size), retry once with a smaller window before giving up.
FIX_CONTEXT_LINES_RETRY = int(os.environ.get("AC_FIX_CONTEXT_LINES_RETRY", "3"))


def workspace_dir(workspace: str) -> Path:
    """Resolve + validate a workspace name to a directory under WORKSPACES_ROOT.

    Rejects path traversal (e.g. "../../etc") - a workspace name must stay
    a single path segment.
    """
    if not workspace or "/" in workspace or "\\" in workspace or workspace in (".", ".."):
        raise ValueError(f"Invalid workspace name: {workspace!r}")
    path = (WORKSPACES_ROOT / workspace).resolve()
    if WORKSPACES_ROOT.resolve() not in path.parents and path != WORKSPACES_ROOT.resolve():
        raise ValueError(f"Invalid workspace name: {workspace!r}")
    path.mkdir(parents=True, exist_ok=True)
    return path


def safe_file_path(workspace: str, filename: str) -> Path:
    """Resolve a filename inside a workspace, rejecting path traversal."""
    if not filename or filename.startswith("/") or ".." in Path(filename).parts:
        raise ValueError(f"Invalid file name: {filename!r}")
    ws = workspace_dir(workspace)
    path = (ws / filename).resolve()
    if ws not in path.parents and path != ws:
        raise ValueError(f"Invalid file name: {filename!r}")
    return path
