import asyncio
import base64
from pathlib import Path
from typing import List

from fastapi import FastAPI, HTTPException, UploadFile, File, WebSocket, WebSocketDisconnect, Depends, Header, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, Response
from pydantic import BaseModel

from .config import settings
from .workspace_manager import WorkspaceManager
from .workspace_fs import list_workspace_files, list_ignored_files, safe_resolve
from .ollama_client import get_ollama_models
from .ollama_tools import run_file_transform
from .ollama_client import generate_direct
from .pylint_runner import run_pylint
from .semgrep_runner import run_semgrep
from .sonarqube_runner import run_sonarqube
from .commands_library import COMMANDS

app = FastAPI(title="Remote Aider Console")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

wsm = WorkspaceManager(
    root=settings.workspaces_root_path,
    aider_bin=settings.aider_bin,
    ollama_base=settings.ollama_api_base,
    default_model=settings.default_model,
    default_mode=settings.default_mode,
    lint_cmd=settings.lint_cmd,
)


# --------------------------------------------------------------------------- auth
def check_auth(authorization: str = Header(default=""), token: str = Query(default="")):
    if not settings.access_token:
        return
    supplied = authorization[7:] if authorization.startswith("Bearer ") else token
    if supplied != settings.access_token:
        raise HTTPException(status_code=401, detail="Unauthorized")


def get_session(name: str):
    try:
        return wsm.get_session(name)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


# --------------------------------------------------------------------------- schemas
class CreateWorkspaceBody(BaseModel):
    name: str


class PathBody(BaseModel):
    path: str


class ModeBody(BaseModel):
    mode: str


class ModelBody(BaseModel):
    model: str


class PromptBody(BaseModel):
    text: str


class CommandBody(BaseModel):
    command: str


class AnswerBody(BaseModel):
    text: str


class TaskBody(BaseModel):
    text: str
    files: List[str] = []


class LintAnalyzeBody(BaseModel):
    path: str
    engine: str = "semgrep"
    sonarUrl: str = ""
    sonarToken: str = ""
    sonarProject: str = ""


class LintAutofixBody(BaseModel):
    path: str
    model: str = ""  # defaults to whichever model is selected in the Aider Console


class ModularizeBody(BaseModel):
    path: str
    paths: List[str] = []
    prompt: str
    model: str = ""


class TestGenBody(BaseModel):
    path: str
    paths: List[str] = []
    prompt: str
    model: str = ""  # defaults to the session's currently selected model


class WriteFileBody(BaseModel):
    path: str
    content: str


class FindingBody(BaseModel):
    path: str
    model: str = ""
    finding: dict


class RawInputBody(BaseModel):
    data: str


# --------------------------------------------------------------------------- workspaces
@app.get("/api/workspaces", dependencies=[Depends(check_auth)])
async def list_workspaces():
    return {"workspaces": wsm.list_workspaces()}


@app.post("/api/workspaces", dependencies=[Depends(check_auth)])
async def create_workspace(body: CreateWorkspaceBody):
    try:
        return wsm.create_workspace(body.name.strip())
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@app.get("/api/commands", dependencies=[Depends(check_auth)])
async def get_commands():
    return {"commands": COMMANDS}


# --------------------------------------------------------------------------- status
@app.get("/api/ws/{name}/status", dependencies=[Depends(check_auth)])
async def get_status(name: str):
    session = get_session(name)
    ollama = await get_ollama_models(settings.ollama_api_base)
    return {
        "aider": session.get_status(),
        "ollama": {"connected": ollama["connected"], "error": ollama.get("error")},
        "workspace": str(wsm.workspace_path(name)),
        "context": session.get_context_stats(),
        "tokens": session.tokens_summary,
        "modifiedFiles": session.get_modified_files(),
        "fileProgress": session.file_progress,
    }


@app.get("/api/ollama/models", dependencies=[Depends(check_auth)])
async def ollama_models():
    result = await get_ollama_models(settings.ollama_api_base)
    if not result["connected"]:
        raise HTTPException(status_code=503, detail=f"Ollama unavailable: {result.get('error')}")
    return {"models": result["models"]}


# --------------------------------------------------------------------------- uploads
@app.post("/api/ws/{name}/upload", dependencies=[Depends(check_auth)])
async def upload_files(name: str, files: List[UploadFile] = File(...)):
    workspace_path = wsm.workspace_path(name)
    if not files:
        raise HTTPException(status_code=400, detail="No files received")

    max_bytes = settings.max_upload_mb * 1024 * 1024
    uploaded = []
    for f in files:
        safe_name = "".join(c if (c.isalnum() or c in "._-() ") else "_" for c in Path(f.filename).name)
        dest = workspace_path / safe_name
        size = 0
        try:
            with open(dest, "wb") as out:
                while True:
                    chunk = await f.read(1024 * 1024)
                    if not chunk:
                        break
                    size += len(chunk)
                    if size > max_bytes:
                        out.close()
                        dest.unlink(missing_ok=True)
                        raise HTTPException(
                            status_code=400,
                            detail=f"{f.filename} exceeds the {settings.max_upload_mb}MB limit",
                        )
                    out.write(chunk)
        except HTTPException:
            raise
        except OSError as exc:
            raise HTTPException(status_code=500, detail=f"Upload failed for {f.filename}: {exc}")
        uploaded.append({"name": safe_name, "size": size})

    return {"uploaded": uploaded}


# --------------------------------------------------------------------------- files
@app.get("/api/ws/{name}/files/workspace", dependencies=[Depends(check_auth)])
async def workspace_files(name: str):
    try:
        workspace_path = wsm.workspace_path(name)
        ignored = list_ignored_files(workspace_path)
        return {"files": list_workspace_files(workspace_path, ignored=ignored)}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Could not list workspace files: {exc}")


@app.get("/api/ws/{name}/files/attached", dependencies=[Depends(check_auth)])
async def attached_files(name: str):
    return {"files": get_session(name).get_status()["attachedFiles"]}


@app.get("/api/ws/{name}/files/download/{file_path:path}", dependencies=[Depends(check_auth)])
async def download_file(name: str, file_path: str):
    workspace_path = wsm.workspace_path(name)
    try:
        abs_path = safe_resolve(workspace_path, file_path)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    if not abs_path.is_file():
        raise HTTPException(status_code=404, detail=f"File not found: {file_path}")
    return FileResponse(abs_path, filename=abs_path.name, media_type="application/octet-stream")


@app.get("/api/ws/{name}/files/raw/{file_path:path}", dependencies=[Depends(check_auth)])
async def read_raw_file(name: str, file_path: str):
    """Current on-disk content of a file (not a specific git commit) --
    used to preview things like existing CI/CD config files."""
    workspace_path = wsm.workspace_path(name)
    try:
        abs_path = safe_resolve(workspace_path, file_path)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    if not abs_path.is_file():
        raise HTTPException(status_code=404, detail=f"File not found: {file_path}")
    try:
        content = abs_path.read_text(errors="replace")
    except OSError as exc:
        raise HTTPException(status_code=500, detail=f"Could not read file: {exc}")
    return {"content": content}


@app.post("/api/ws/{name}/files/add", dependencies=[Depends(check_auth)])
async def add_file(name: str, body: PathBody):
    session = get_session(name)
    try:
        safe_resolve(wsm.workspace_path(name), body.path)
        session.add_file(body.path)
        return {"ok": True}
    except (ValueError, RuntimeError) as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@app.post("/api/ws/{name}/files/drop", dependencies=[Depends(check_auth)])
async def drop_file(name: str, body: PathBody):
    try:
        get_session(name).drop_file(body.path)
        return {"ok": True}
    except RuntimeError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


# --------------------------------------------------------------------------- native commands
@app.post("/api/ws/{name}/aider/clear", dependencies=[Depends(check_auth)])
async def clear_chat(name: str):
    try:
        get_session(name).clear_chat()
        return {"ok": True}
    except RuntimeError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@app.post("/api/ws/{name}/aider/tokens", dependencies=[Depends(check_auth)])
async def request_tokens(name: str):
    try:
        get_session(name).request_tokens()
        return {"ok": True}
    except RuntimeError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@app.get("/api/ws/{name}/history", dependencies=[Depends(check_auth)])
async def get_history(name: str):
    return {"history": get_session(name).get_history()}


@app.get("/api/ws/{name}/files/versions/{file_path:path}", dependencies=[Depends(check_auth)])
async def get_file_versions(name: str, file_path: str):
    return {"versions": get_session(name).get_file_versions(file_path)}


@app.get("/api/ws/{name}/files/content-at/{file_path:path}", dependencies=[Depends(check_auth)])
async def get_file_content_at(name: str, file_path: str, commit: str):
    content = get_session(name).get_file_content_at(file_path, commit)
    if content is None:
        raise HTTPException(status_code=404, detail=f"No content for {file_path} at {commit}")
    return {"content": content}


@app.post("/api/ws/{name}/aider/undo", dependencies=[Depends(check_auth)])
async def undo_last(name: str):
    try:
        get_session(name).undo_last()
        return {"ok": True}
    except RuntimeError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@app.post("/api/ws/{name}/aider/mode", dependencies=[Depends(check_auth)])
async def set_mode(name: str, body: ModeBody):
    if body.mode not in ("ask", "code", "architect"):
        raise HTTPException(status_code=400, detail="Mode must be ask, code, or architect")
    try:
        get_session(name).set_mode(body.mode)
        return {"ok": True}
    except RuntimeError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@app.post("/api/ws/{name}/aider/model", dependencies=[Depends(check_auth)])
async def set_model(name: str, body: ModelBody):
    if not body.model:
        raise HTTPException(status_code=400, detail="model is required")
    try:
        get_session(name).set_model(body.model)
        return {"ok": True}
    except RuntimeError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@app.post("/api/ws/{name}/aider/prompt", dependencies=[Depends(check_auth)])
async def send_prompt(name: str, body: PromptBody):
    if not body.text or not body.text.strip():
        raise HTTPException(status_code=400, detail="Prompt text is required")
    session = get_session(name)
    if session.get_status()["taskRunning"]:
        raise HTTPException(status_code=409, detail="A task is currently running. Wait for it to finish.")
    try:
        session.send_input(body.text)
        return {"ok": True}
    except RuntimeError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@app.post("/api/ws/{name}/aider/command", dependencies=[Depends(check_auth)])
async def run_command(name: str, body: CommandBody):
    """Generic pass-through for any native Aider command (used by the
    command palette for entries with no dedicated endpoint)."""
    if not body.command or not body.command.strip():
        raise HTTPException(status_code=400, detail="command is required")
    try:
        get_session(name).send_input(body.command)
        return {"ok": True}
    except RuntimeError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@app.post("/api/ws/{name}/aider/answer", dependencies=[Depends(check_auth)])
async def answer_question(name: str, body: AnswerBody):
    try:
        get_session(name).answer_question(body.text)
        return {"ok": True}
    except RuntimeError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


# --------------------------------------------------------------------------- supervised task lifecycle
@app.post("/api/ws/{name}/task/start", dependencies=[Depends(check_auth)])
async def start_task(name: str, body: TaskBody):
    try:
        return get_session(name).start_task(body.text, body.files)
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc))


@app.post("/api/ws/{name}/task/stop", dependencies=[Depends(check_auth)])
async def stop_task(name: str):
    try:
        get_session(name).stop_task()
        return {"ok": True}
    except RuntimeError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


# --------------------------------------------------------------------------- static analysis (pylint, direct -- no Aider)
@app.post("/api/ws/{name}/lint/analyze", dependencies=[Depends(check_auth)])
async def lint_analyze(name: str, body: LintAnalyzeBody):
    """Run only a static analyzer; no LLM or Aider is involved."""
    if body.engine not in ("semgrep", "pylint", "sonarqube"):
        raise HTTPException(status_code=400, detail="engine must be semgrep, pylint, or sonarqube")
    if body.engine == "sonarqube":
        result = await run_sonarqube(body.sonarUrl, body.sonarToken, body.sonarProject)
    else:
        runner = run_semgrep if body.engine == "semgrep" else run_pylint
        result = runner(wsm.workspace_path(name), body.path)
    if result["error"]:
        raise HTTPException(status_code=400, detail=result["error"])
    result["engine"] = body.engine
    return result


@app.post("/api/ws/{name}/lint/autofix", dependencies=[Depends(check_auth)])
async def lint_autofix(name: str, body: LintAutofixBody):
    """Auto-fix, powered directly by Ollama -- NOT Aider. Re-runs pylint,
    builds an instruction from the findings, sends the whole file to Ollama,
    and returns a diff for the user to review before saving anything."""
    workspace_path = wsm.workspace_path(name)
    lint_result = run_pylint(workspace_path, body.path)
    if lint_result["error"]:
        raise HTTPException(status_code=400, detail=lint_result["error"])

    try:
        abs_path = safe_resolve(workspace_path, body.path)
        file_content = abs_path.read_text(errors="replace")
    except (ValueError, OSError) as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    if not lint_result["findings"]:
        return {"ok": True, "original": file_content, "result": file_content, "diff": "",
                "model": body.model, "changed": False, "findings": []}

    # Only error/fatal-severity findings go to the model -- pylint's
    # convention/refactor/warning noise was drowning out the actual errors
    # and the model wasn't reliably fixing them as a result.
    error_findings = [f for f in lint_result["findings"] if f["type"] in ("error", "fatal")]
    if not error_findings:
        return {"ok": True, "original": file_content, "result": file_content, "diff": "",
                "model": body.model, "changed": False, "findings": lint_result["findings"],
                "note": "No error/fatal-level findings to fix (only convention/refactor/warning-level items)."}

    findings_text = "\n".join(
        f"- line {f['line']}: [{f['symbol']}] {f['message']}" for f in error_findings[:40]
    )
    instruction = (
        f"Pylint reported the following ERRORS (not warnings or style suggestions):\n\n{findings_text}\n\n"
        "Fix ONLY these specific errors while preserving the file's existing behavior. "
        "Do not make unrelated style changes."
    )
    model = body.model or get_session(name).status.model
    result = await run_file_transform(settings.ollama_api_base, model, file_content, body.path, instruction)
    if not result["ok"]:
        raise HTTPException(status_code=502, detail=f"Ollama request failed: {result.get('error')}")
    result["findings"] = lint_result["findings"]
    return result


@app.post("/api/ws/{name}/lint/explain", dependencies=[Depends(check_auth)])
async def lint_explain(name: str, body: FindingBody):
    """Ask Ollama about one finding only; never sends a whole lint report."""
    model = body.model or get_session(name).status.model
    finding = body.finding
    prompt = ("Explain this static-analysis finding clearly and concisely. Include why it matters "
              "and a safe way to resolve it. Do not propose unrelated changes.\n\n"
              f"File: {body.path}\nFinding: {finding.get('symbol')}: {finding.get('message')} "
              f"at line {finding.get('line')}, column {finding.get('column')}.")
    result = await generate_direct(settings.ollama_api_base, model, prompt)
    if not result["ok"]:
        raise HTTPException(status_code=502, detail=f"Ollama request failed: {result.get('error')}")
    return {"explanation": result["text"], "model": result["model"]}


@app.post("/api/ws/{name}/lint/fix-finding", dependencies=[Depends(check_auth)])
async def lint_fix_finding(name: str, body: FindingBody):
    """Fix one finding in an isolated Aider session and commit its review copy."""
    workspace_path = wsm.workspace_path(name)
    try:
        original = safe_resolve(workspace_path, body.path)
        if not original.is_file():
            raise OSError("File not found")
        review_path = original.with_name(f"fix_{original.name}")
        review_path.write_text(original.read_text(errors="replace"))
        rel_review = str(review_path.relative_to(workspace_path))
    except (ValueError, OSError) as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    f = body.finding
    prompt = (f"Fix only this {f.get('type', 'analysis')} finding in `{rel_review}`: "
              f"[{f.get('symbol')}] {f.get('message')} at line {f.get('line')}, column {f.get('column')}. "
              "Keep behavior unchanged. Edit the attached review copy and commit the result.")
    result = await _run_tool_task(name, "lintfix", rel_review, prompt)
    result.update({"path": body.path, "reviewPath": rel_review, "committed": bool(result.get("commits"))})
    try:
        result["result"] = review_path.read_text(errors="replace")
    except OSError:
        result["result"] = ""
    return result


@app.get("/api/ws/{name}/lint/pylint-report.pdf", dependencies=[Depends(check_auth)])
async def pylint_report_pdf(name: str, path: str):
    report = run_pylint(wsm.workspace_path(name), path)
    if report["error"]:
        raise HTTPException(status_code=400, detail=report["error"])
    # A compact, dependency-free PDF report; text is escaped for PDF literals.
    def esc(value): return str(value).replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
    lines = [f"Pylint consolidated report", f"Workspace: {name}", f"Project folder: {wsm.workspace_path(name)}", f"Target: {path}", f"Total findings: {len(report['findings'])}", ""]
    lines += [f"{f['path']}:{f['line']}:{f['column']} [{f['type']}] {f['symbol']} — {f['message']}" for f in report['findings']]
    lines = lines[:70]
    stream = "BT /F1 10 Tf 45 780 Td 13 TL " + " ".join(f"({esc(line)}) Tj T*" for line in lines) + " ET"
    objects = ["<< /Type /Catalog /Pages 2 0 R >>", "<< /Type /Pages /Kids [3 0 R] /Count 1 >>", "<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Resources << /Font << /F1 5 0 R >> >> /Contents 4 0 R >>", f"<< /Length {len(stream.encode())} >>\nstream\n{stream}\nendstream", "<< /Type /Font /Subtype /Type1 /BaseFont /Courier >>"]
    pdf = "%PDF-1.4\n"; offsets = [0]
    for i, obj in enumerate(objects, 1):
        offsets.append(len(pdf.encode())); pdf += f"{i} 0 obj\n{obj}\nendobj\n"
    xref = len(pdf.encode()); pdf += f"xref\n0 {len(objects)+1}\n0000000000 65535 f \n" + "".join(f"{o:010d} 00000 n \n" for o in offsets[1:]) + f"trailer << /Size {len(objects)+1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF"
    return Response(pdf.encode(), media_type="application/pdf", headers={"Content-Disposition": 'attachment; filename="pylint-report.pdf"'})


async def _run_tool_task(name: str, purpose: str, path: str, prompt: str, paths: List[str] | None = None) -> dict:
    """Shared plumbing for the Modularization and Test-Gen tools: get (or
    lazily start) this workspace's dedicated hidden session for `purpose`,
    submit the task, and wait for it to finish -- returning the diff
    directly rather than requiring the caller to watch a live status feed."""
    workspace_path = wsm.workspace_path(name)
    paths = paths or [path]
    for item in paths:
        try:
            safe_resolve(workspace_path, item)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        if not (workspace_path / item).is_file():
            raise HTTPException(status_code=404, detail=f"File not found: {item}")

    try:
        session = wsm.get_tool_session(name, purpose)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc))

    if not session.is_running():
        session.start()
        # Do not submit work while Aider is still emitting its startup/chat-mode
        # output: its silence callback can otherwise complete the new task
        # before the model has received it.
        for _ in range(60):
            if session.get_status()["status"] == "idle":
                break
            await asyncio.sleep(0.25)
        else:
            raise HTTPException(status_code=504, detail="Aider did not become ready in time.")

    try:
        session.start_task(prompt, paths)
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc))

    try:
        diff = await session.wait_for_task_done(timeout=300.0)
    except asyncio.TimeoutError:
        raise HTTPException(status_code=504, detail="Task timed out after 5 minutes.")

    diff["model"] = session.status.model
    return diff


# --------------------------------------------------------------------------- modularization (via Aider, isolated session)
@app.post("/api/ws/{name}/tasks/modularize", dependencies=[Depends(check_auth)])
async def task_modularize(name: str, body: ModularizeBody):
    """Modularization goes through Aider -- but a dedicated hidden session
    for this workspace, completely separate from the visible Aider Console
    session, so using this tool never interrupts an active console chat."""
    return await _run_tool_task(name, "modularize", body.path, body.prompt, body.paths)


# --------------------------------------------------------------------------- test generation (via Aider, isolated session)
@app.post("/api/ws/{name}/tasks/testgen", dependencies=[Depends(check_auth)])
async def task_testgen(name: str, body: TestGenBody):
    """Test generation also goes through Aider, via its own dedicated hidden
    session (separate from both the console and the modularize session).
    Asks Aider to create a NEW test file rather than modifying the source."""
    prompt = f"Create NEW test file(s) for the attached source file(s) (do not modify originals). {body.prompt}"
    return await _run_tool_task(name, "testgen", body.path, prompt, body.paths)


@app.get("/api/ws/{name}/tasks/{purpose}/status", dependencies=[Depends(check_auth)])
async def tool_task_status(name: str, purpose: str):
    """Polling endpoint for the hidden tool sessions. The visible console
    socket is intentionally separate, so Modularization and Test Generation
    use this endpoint to render live Aider phases while their request waits."""
    if purpose not in ("modularize", "testgen", "lintfix"):
        raise HTTPException(status_code=400, detail="Unknown tool session.")
    try:
        session = wsm.get_tool_session(name, purpose)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    status = session.get_status()
    status["raw"] = session.get_recent_raw_b64()
    return status


@app.post("/api/ws/{name}/tasks/{purpose}/raw", dependencies=[Depends(check_auth)])
async def tool_task_raw(name: str, purpose: str, body: RawInputBody):
    if purpose not in ("modularize", "testgen", "lintfix"):
        raise HTTPException(status_code=400, detail="Unknown tool session.")
    try:
        data = base64.b64decode(body.data, validate=True)
        wsm.get_tool_session(name, purpose).write_raw_bytes(data)
        return {"ok": True}
    except (ValueError, KeyError, RuntimeError) as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@app.post("/api/ws/{name}/tasks/{purpose}/prompt", dependencies=[Depends(check_auth)])
async def tool_task_prompt(name: str, purpose: str, body: PromptBody):
    if purpose not in ("modularize", "testgen", "lintfix"):
        raise HTTPException(status_code=400, detail="Unknown tool session.")
    try:
        wsm.get_tool_session(name, purpose).send_input(body.text)
        return {"ok": True}
    except (KeyError, RuntimeError) as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@app.post("/api/ws/{name}/tasks/{purpose}/clear", dependencies=[Depends(check_auth)])
async def tool_task_clear(name: str, purpose: str):
    try:
        wsm.get_tool_session(name, purpose).clear_chat()
        return {"ok": True}
    except (KeyError, RuntimeError) as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@app.post("/api/ws/{name}/tasks/{purpose}/tokens", dependencies=[Depends(check_auth)])
async def tool_task_tokens(name: str, purpose: str):
    try:
        wsm.get_tool_session(name, purpose).request_tokens()
        return {"ok": True}
    except (KeyError, RuntimeError) as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@app.post("/api/ws/{name}/tasks/{purpose}/answer", dependencies=[Depends(check_auth)])
async def tool_task_answer(name: str, purpose: str, body: AnswerBody):
    if purpose not in ("modularize", "testgen", "lintfix"):
        raise HTTPException(status_code=400, detail="Unknown tool session.")
    try:
        wsm.get_tool_session(name, purpose).answer_question(body.text)
        return {"ok": True}
    except (KeyError, RuntimeError) as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@app.post("/api/ws/{name}/tasks/{purpose}/undo", dependencies=[Depends(check_auth)])
async def task_undo(name: str, purpose: str):
    if purpose not in ("modularize", "testgen", "lintfix"):
        raise HTTPException(status_code=400, detail="Unknown tool session.")
    try:
        session = wsm.get_tool_session(name, purpose)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    try:
        session.undo_last()
        return {"ok": True}
    except RuntimeError as exc:
        raise HTTPException(status_code=400, detail=str(exc))



@app.post("/api/ws/{name}/files/write", dependencies=[Depends(check_auth)])
async def write_file(name: str, body: WriteFileBody):
    """Writes content directly to a workspace file -- used to save output
    from any of the three Ollama-direct tools above. Bypasses Aider
    entirely, same as the generation steps themselves."""
    workspace_path = wsm.workspace_path(name)
    try:
        abs_path = safe_resolve(workspace_path, body.path)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    try:
        abs_path.parent.mkdir(parents=True, exist_ok=True)
        abs_path.write_text(body.content)
    except OSError as exc:
        raise HTTPException(status_code=500, detail=f"Could not write file: {exc}")
    return {"ok": True, "path": body.path}


# --------------------------------------------------------------------------- lifecycle
@app.post("/api/ws/{name}/aider/start", dependencies=[Depends(check_auth)])
async def start_aider(name: str):
    try:
        return get_session(name).start()
    except RuntimeError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Could not start Aider: {exc}")


@app.post("/api/ws/{name}/aider/stop", dependencies=[Depends(check_auth)])
async def stop_aider(name: str):
    session = get_session(name)
    session.stop()
    return session.get_status()


@app.post("/api/ws/{name}/aider/restart", dependencies=[Depends(check_auth)])
async def restart_aider(name: str):
    try:
        return await get_session(name).restart()
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Could not restart Aider: {exc}")


# --------------------------------------------------------------------------- websocket
@app.websocket("/ws/{name}")
async def ws_endpoint(websocket: WebSocket, name: str, token: str = ""):
    if settings.access_token and token != settings.access_token:
        await websocket.close(code=4001)
        return
    try:
        session = wsm.get_session(name)
    except KeyError:
        await websocket.close(code=4004)
        return

    await wsm.ws_hub.connect(name, websocket)
    for chunk_b64 in session.get_recent_raw_b64():
        await websocket.send_json({"type": "raw", "data": chunk_b64})
    await websocket.send_json({"type": "status", "data": session.get_status()})
    if session.tokens_summary:
        await websocket.send_json({"type": "tokens", "data": session.tokens_summary})
    if session.modified_files:
        await websocket.send_json({"type": "modified_files", "data": session.get_modified_files()})
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        wsm.ws_hub.disconnect(name, websocket)


# --------------------------------------------------------------------------- static frontend
FRONTEND_DIST = Path(__file__).resolve().parent.parent.parent / "frontend" / "dist"
if FRONTEND_DIST.exists():
    app.mount("/", StaticFiles(directory=str(FRONTEND_DIST), html=True), name="frontend")
