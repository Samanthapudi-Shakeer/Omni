from __future__ import annotations
from typing import List, Optional, Literal
from pydantic import BaseModel, Field


# ---------------------------------------------------------------- workspace
class WorkspaceFile(BaseModel):
    name: str
    size_bytes: int
    is_generated: bool = False  # e.g. fix_*.py / report txt files


# ---------------------------------------------------------------- analysis
Severity = Literal["error", "warning", "convention", "refactor", "info"]


class Issue(BaseModel):
    id: str                     # stable id: f"{file}:{line}:{col}:{rule}"
    file: str
    line: int
    column: int = 0
    severity: Severity
    rule: str
    message: str
    tool: str                   # pylint | oclint | htmlhint | pmd


class RunAnalysisRequest(BaseModel):
    workspace: str
    files: List[str] = Field(default_factory=list)


class RunAnalysisResponse(BaseModel):
    issues: List[Issue]
    report_text: str
    report_file: str            # relative filename, downloadable via /api/analysis/report
    project_key: str
    dashboard_url: str


class AskAIRequest(BaseModel):
    workspace: str
    issue: Issue


class AskAIResponse(BaseModel):
    explanation: str


class HowToFixRequest(BaseModel):
    """Preview-only: asks Ollama how to fix one issue, given the FULL file
    as context. Nothing is written to disk by this call - see ApplyFixRequest.
    """
    workspace: str
    issue: Issue
    model: Optional[str] = None


class HowToFixResponse(BaseModel):
    explanation: str
    diff: str                   # unified diff of the suggested change, for display only
    start_line: int
    end_line: int
    original_code: str
    fixed_code: str
    error: Optional[str] = None


class ApplyFixRequest(BaseModel):
    """Writes exactly the previously-previewed fix. No Ollama call happens
    here - start_line/end_line/fixed_code must come from a prior
    HowToFixResponse, guaranteeing what's applied matches what was shown.
    """
    workspace: str
    issue: Issue
    start_line: int
    end_line: int
    fixed_code: str


class ApplyFixResponse(BaseModel):
    status: Literal["ok", "error"]
    diff: str
    commit: Optional[str] = None
    error: Optional[str] = None


class FixAllRequest(BaseModel):
    workspace: str
    issues: List[Issue]


class FixAllIssueResult(BaseModel):
    issue_id: str
    file: str
    status: Literal["ok", "error"]
    diff: str
    commit: Optional[str] = None
    error: Optional[str] = None


class FixAllResult(BaseModel):
    results: List[FixAllIssueResult]
    files_changed: List[str]


# -------------------------------------------------------------- file history
class FileHistoryEntry(BaseModel):
    hash: str
    short_hash: str
    message: str
    date: str


class FileHistoryResponse(BaseModel):
    file: str
    commits: List[FileHistoryEntry]   # newest first


class FileDiffResponse(BaseModel):
    file: str
    diff: str


# -------------------------------------------------------------------- jobs
class JobResponse(BaseModel):
    id: str
    kind: str                   # "fix" | "modularize"
    label: str                  # short human label, e.g. "Fix: bad.py unused-import"
    status: Literal["running", "done", "error"]
    progress: List[str]         # ordered log lines, latest last
    result: Optional[dict] = None
    error: Optional[str] = None


class StartJobResponse(BaseModel):
    job_id: str


# ------------------------------------------------------------- modularize
class DefaultPromptResponse(BaseModel):
    prompt: str


class RunModularizeRequest(BaseModel):
    """Starts an interactive PTY modularization session (same shape used
    for the old job-based /run endpoint, now reused for /start-session)."""
    workspace: str
    file: str
    prompt: str


class ModularizeSessionResponse(BaseModel):
    session_id: str


# ------------------------------------------------------------------ testgen
class TestGenDefaultPromptResponse(BaseModel):
    prompt: str


class TestGenStartRequest(BaseModel):
    workspace: str
    files: List[str]
    prompt: str


class TestGenStartResponse(BaseModel):
    session_id: str


# ---------------------------------------------------------------- translate
class TranslateLanguage(BaseModel):
    code: str
    name: str


class TranslateLanguagesResponse(BaseModel):
    source_languages: List[TranslateLanguage]   # includes "auto"
    target_languages: List[TranslateLanguage]


class OllamaModelInfo(BaseModel):
    name: str
    size_bytes: Optional[int] = None


class TranslateModelsResponse(BaseModel):
    models: List[OllamaModelInfo]
    default_model: str


class TranslateRequest(BaseModel):
    text: str
    source_lang: str            # "auto" or a language code
    target_lang: str            # a language code
    model: Optional[str] = None


class TranslateResponse(BaseModel):
    translation: str
    detected_source_lang: Optional[str] = None   # human-readable name, e.g. "French"
    detected_source_code: Optional[str] = None    # best-guess code for that name, if resolvable
    model: str


class TranslateOfficeDocRequest(BaseModel):
    """Shared request shape for translating a .pptx, .docx, or .xlsx file."""
    workspace: str
    file: str
    source_lang: str
    target_lang: str
    model: Optional[str] = None
    vision_model: Optional[str] = None   # None/omitted => skip images entirely


class ImageTranslateResponse(BaseModel):
    """Result of uploading a standalone image for description + text
    translation (not tied to any document or workspace file)."""
    description: str
    has_text: bool
    detected_text: str
    translation: str
    model: str
