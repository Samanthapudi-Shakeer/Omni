from __future__ import annotations
import json
import time
from urllib.parse import quote
from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import PlainTextResponse

from app import config
from app.models import (
    RunAnalysisRequest, RunAnalysisResponse, Issue,
    AskAIRequest, AskAIResponse,
    HowToFixRequest, HowToFixResponse, ApplyFixRequest, ApplyFixResponse,
    FixAllRequest, StartJobResponse,
    FileHistoryResponse, FileHistoryEntry, FileDiffResponse,
)
from app.services import (
    ollama_client, quick_fix, how_to_fix as how_to_fix_service,
    jobs, versioning, sonar_analysis,
)

router = APIRouter(prefix="/api/analysis", tags=["analysis"])


def _issue_id(file: str, line: int, col: int, rule: str) -> str:
    return f"{file}:{line}:{col}:{rule}"


@router.post("/run", response_model=RunAnalysisResponse)
async def run_analysis(req: RunAnalysisRequest):
    ws = config.workspace_dir(req.workspace)
    all_issues: list[Issue] = []
    errors: list[str] = []
    files = list(req.files)
    if not files:
        manifest_path = ws / ".ac_project_files.json"
        if not manifest_path.exists():
            raise HTTPException(400, "Upload a project ZIP in the SCA tab before scanning")
        try:
            files = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as e:
            raise HTTPException(400, f"Uploaded project manifest is invalid: {e}")
        if not isinstance(files, list) or not all(isinstance(file, str) for file in files):
            raise HTTPException(400, "Uploaded project manifest is invalid")
    if not files:
        raise HTTPException(400, "Upload a project ZIP to the workspace before scanning")
    project_name = req.workspace
    metadata_path = ws / ".ac_project_metadata.json"
    if metadata_path.exists():
        try:
            metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
            zip_name = metadata.get("zip_name")
            uploaded_date = metadata.get("uploaded_date")
            if isinstance(zip_name, str) and isinstance(uploaded_date, str):
                project_name = f"{zip_name}_{uploaded_date}"
        except (OSError, json.JSONDecodeError):
            pass
    if not sonar_analysis.configured():
        raise HTTPException(503, "SonarQube is not configured. Set SONAR_URL and SONAR_TOKEN.")
    try:
        raw_issues = sonar_analysis.analyze_workspace(project_name, ws, files)
        for ri in raw_issues:
            all_issues.append(Issue(
                id=_issue_id(ri["file"], ri["line"], ri["column"], ri["rule"]),
                **ri,
            ))
    except Exception as e:  # noqa: BLE001 - surface scanner/API errors to the report
        errors.append(f"SonarQube analysis failed: {e}")

    try:
        report_text = ollama_client.summarize_issues(
            [i.model_dump() for i in all_issues], analyzed_files=files
        )
    except Exception as e:  # noqa: BLE001 - keep Sonar findings if Ollama is unavailable
        errors.append(f"Report summary unavailable: {e}")
        report_text = (
            f"SonarQube analysis completed. {len(all_issues)} issue(s) found, "
            "but the AI summary could not be generated."
        )
    if errors:
        report_text += "\n\n--- Tool Errors " + "-" * 58 + "\n" + "\n".join(errors) + "\n"

    reports_dir = ws / config.REPORTS_DIRNAME
    reports_dir.mkdir(exist_ok=True)
    report_name = f"report_{int(time.time())}.txt"
    (reports_dir / report_name).write_text(report_text)

    project_key = sonar_analysis._project_key(project_name)
    dashboard_url = (
        f"{config.SONAR_URL}/dashboard?id={quote(project_key, safe='')}"
    )
    return RunAnalysisResponse(
        issues=all_issues,
        report_text=report_text,
        report_file=report_name,
        project_key=project_key,
        dashboard_url=dashboard_url,
    )


@router.get("/report/{workspace}/{report_name}", response_class=PlainTextResponse)
async def get_report(workspace: str, report_name: str):
    try:
        ws = config.workspace_dir(workspace)
    except ValueError as e:
        raise HTTPException(400, str(e))
    path = ws / config.REPORTS_DIRNAME / report_name
    if ".." in report_name or not path.exists():
        raise HTTPException(404, "Report not found")
    return path.read_text()


@router.post("/ask", response_model=AskAIResponse)
async def ask_ai(req: AskAIRequest):
    try:
        fpath = config.safe_file_path(req.workspace, req.issue.file)
    except ValueError as e:
        raise HTTPException(400, str(e))

    snippet = None
    if fpath.exists():
        lines = fpath.read_text(errors="replace").splitlines()
        start = max(0, req.issue.line - 4)
        end = min(len(lines), req.issue.line + 3)
        snippet = "\n".join(lines[start:end])

    explanation = ollama_client.explain_issue(req.issue.model_dump(), file_snippet=snippet)
    return AskAIResponse(explanation=explanation)


@router.post("/how-to-fix", response_model=HowToFixResponse)
async def how_to_fix_endpoint(req: HowToFixRequest):
    """Preview-only: asks Ollama how to fix one issue, supplying the ENTIRE
    file as context (not just a snippet), and returns an explanation plus a
    diff for display in a canvas. Nothing is written to disk here - see
    /apply-fix for the explicit, separate action that actually writes it.
    This replaces the old auto-applying single-issue "Fix with AI" button.
    """
    try:
        original = config.safe_file_path(req.workspace, req.issue.file)
    except ValueError as e:
        raise HTTPException(400, str(e))
    if not original.exists():
        raise HTTPException(404, f"{req.issue.file} not found in workspace")

    result = how_to_fix_service.how_to_fix(original, req.issue.model_dump(), model=req.model)
    if result.error:
        raise HTTPException(502, f"Could not reach Ollama: {result.error}")

    return HowToFixResponse(
        explanation=result.explanation, diff=result.diff,
        start_line=result.start_line, end_line=result.end_line,
        original_code=result.original_code, fixed_code=result.fixed_code,
    )


@router.post("/apply-fix", response_model=ApplyFixResponse)
async def apply_fix_endpoint(req: ApplyFixRequest):
    """Writes exactly the fix previously shown by /how-to-fix into the
    original file and commits it to that file's version history. No Ollama
    call happens here - the caller must pass back the same
    start_line/end_line/fixed_code they were shown, so what gets applied is
    guaranteed to match what was previewed.
    """
    ws = config.workspace_dir(req.workspace)
    try:
        original = config.safe_file_path(req.workspace, req.issue.file)
    except ValueError as e:
        raise HTTPException(400, str(e))
    if not original.exists():
        raise HTTPException(404, f"{req.issue.file} not found in workspace")

    issue_summary = f"{req.issue.rule} at line {req.issue.line} ({req.issue.tool})"
    result = how_to_fix_service.apply_fix(
        ws, original, req.start_line, req.end_line, req.fixed_code, issue_summary,
    )
    return ApplyFixResponse(**result)


@router.post("/fix-all", response_model=StartJobResponse)
async def fix_all_with_ai(req: FixAllRequest):
    """Fixes every given issue, in place, one background job for the whole
    batch. Issues are grouped by file and, within each file, applied from
    the LAST line to the FIRST - so a fix that shifts line counts never
    invalidates the line numbers of issues still waiting to be fixed above
    it in the same file. Every successful fix is its own commit in that
    file's version history, same as a single Fix with AI call.
    """
    if not req.issues:
        raise HTTPException(400, "No issues to fix")

    ws = config.workspace_dir(req.workspace)
    by_file: dict[str, list[Issue]] = {}
    for issue in req.issues:
        by_file.setdefault(issue.file, []).append(issue)

    job = jobs.create_job(kind="fix_all", label=f"Fix All ({len(req.issues)} issue{'s' if len(req.issues) != 1 else ''})")

    def _work(progress_cb):
        results = []
        files_changed: set[str] = set()
        total = len(req.issues)
        done_count = 0

        for fname, file_issues in by_file.items():
            try:
                original = config.safe_file_path(req.workspace, fname)
            except ValueError as e:
                for issue in file_issues:
                    done_count += 1
                    results.append({
                        "issue_id": issue.id, "file": fname, "status": "error",
                        "diff": "", "commit": None, "error": str(e),
                    })
                continue
            if not original.exists():
                for issue in file_issues:
                    done_count += 1
                    results.append({
                        "issue_id": issue.id, "file": fname, "status": "error",
                        "diff": "", "commit": None, "error": "file not found in workspace",
                    })
                continue

            # Bottom-up so already-applied edits never shift the line
            # numbers of issues still waiting to be processed in this file.
            for issue in sorted(file_issues, key=lambda i: i.line, reverse=True):
                done_count += 1
                progress_cb(f"[{done_count}/{total}] Fixing {fname}:{issue.line} ({issue.rule})…")
                result = quick_fix.fix_issue(ws, original, issue.model_dump())
                results.append({
                    "issue_id": issue.id, "file": fname,
                    "status": "ok" if result.ok else "error",
                    "diff": result.diff, "commit": result.commit, "error": result.error,
                })
                if result.ok:
                    files_changed.add(fname)

        progress_cb("All fixes applied.")
        return {"results": results, "files_changed": sorted(files_changed)}

    jobs.run_in_background(job.id, _work)
    return StartJobResponse(job_id=job.id)


@router.get("/history/{workspace}/{filename}", response_model=FileHistoryResponse)
async def get_file_history(workspace: str, filename: str):
    """Full AI-fix history for one file, newest first."""
    try:
        ws = config.workspace_dir(workspace)
        config.safe_file_path(workspace, filename)  # validates filename, raises if unsafe
    except ValueError as e:
        raise HTTPException(400, str(e))
    commits = versioning.file_history(ws, filename)
    return FileHistoryResponse(
        file=filename,
        commits=[FileHistoryEntry(**c) for c in commits],
    )


@router.get("/diff/{workspace}/{filename}", response_model=FileDiffResponse)
async def get_file_diff(workspace: str, filename: str, commit: str | None = None,
                        against: str | None = None, from_ref: str | None = None,
                        to_ref: str | None = None):
    """Diff for one file.
    - `commit` given: the diff introduced by that single commit.
    - `against` given: diff from that commit/ref to the file's current state.
    - neither given: diff from the very first tracked version (baseline) to now.
    """
    try:
        ws = config.workspace_dir(workspace)
        config.safe_file_path(workspace, filename)
    except ValueError as e:
        raise HTTPException(400, str(e))

    if from_ref:
        diff = versioning.diff_range(ws, filename, from_ref, to_ref or "HEAD")
    elif commit:
        diff = versioning.diff_for_commit(ws, filename, commit)
    elif against:
        diff = versioning.diff_range(ws, filename, against, "HEAD")
    else:
        diff = versioning.diff_against_baseline(ws, filename)

    return FileDiffResponse(file=filename, diff=diff)
