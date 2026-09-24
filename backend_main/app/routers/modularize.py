from __future__ import annotations
from fastapi import APIRouter, HTTPException

from app import config
from app.models import DefaultPromptResponse, RunModularizeRequest, ModularizeSessionResponse
from app.services import pty_session

router = APIRouter(prefix="/api/modularize", tags=["modularize"])

DEFAULT_MODULARIZE_PROMPT = (
    "Analyze this file and split it into well-organized, cohesive modules "
    "based on single responsibility (e.g. separate data models, business "
    "logic, utilities/helpers, and any I/O or interface layer into their "
    "own files). Preserve all existing functionality and public "
    "interfaces exactly. Create new files as needed, update "
    "imports/includes accordingly, and add a short comment at the top of "
    "each new file explaining its purpose."
)


@router.get("/default-prompt", response_model=DefaultPromptResponse)
async def default_prompt():
    return DefaultPromptResponse(prompt=DEFAULT_MODULARIZE_PROMPT)


@router.post("/start-session", response_model=ModularizeSessionResponse)
async def start_modularize_session(req: RunModularizeRequest):
    """Starts an isolated, interactive aider session attached to a PTY -
    the same mechanism Test Case Generation uses - and returns a
    session_id. Connect to `/api/pty/ws/{session_id}` next to see the live
    terminal and answer any Y/N prompts aider asks yourself (a small list
    of known low-value prompts, like the LLM-warnings documentation link,
    are auto-answered "No" - see services/pty_session.py). This replaces
    the old non-interactive `aider --yes-always` job, which never gave you
    a chance to actually see or answer what aider was asking.
    """
    ws = config.workspace_dir(req.workspace)
    try:
        original = config.safe_file_path(req.workspace, req.file)
    except ValueError as e:
        raise HTTPException(400, str(e))
    if not original.exists():
        raise HTTPException(404, f"{req.file} not found in workspace")
    if not req.prompt.strip():
        raise HTTPException(400, "Prompt cannot be empty")

    session = pty_session.start_session(ws, [req.file], req.prompt, kind="modularize")
    return ModularizeSessionResponse(session_id=session.id)
