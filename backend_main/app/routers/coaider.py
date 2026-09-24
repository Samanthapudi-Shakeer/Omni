"""Interactive Coaider sessions for the active Aider Console workspace."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app import config
from app.models import ModularizeSessionResponse
from app.services import pty_session

router = APIRouter(prefix="/api/coaider", tags=["coaider"])


class CoaiderStartRequest(BaseModel):
    workspace: str
    files: list[str] = Field(default_factory=list)
    prompt: str


@router.post("/start", response_model=ModularizeSessionResponse)
async def start_coaider_session(req: CoaiderStartRequest):
    """Open a live, isolated Coaider terminal for files in one workspace.

    The same workspace selected in the main application is validated here and
    supplied to the PTY session. Changes are copied back to that workspace
    when the interactive Aider process exits.
    """
    workspace_dir = config.workspace_dir(req.workspace)
    if not req.files:
        raise HTTPException(400, "Attach at least one workspace file")
    if not req.prompt.strip():
        raise HTTPException(400, "Prompt cannot be empty")

    for file_name in req.files:
        try:
            path = config.safe_file_path(req.workspace, file_name)
        except ValueError as exc:
            raise HTTPException(400, str(exc))
        if not path.is_file():
            raise HTTPException(404, f"{file_name} not found in workspace")

    session = pty_session.start_session(workspace_dir, req.files, req.prompt, kind="coaider")
    return ModularizeSessionResponse(session_id=session.id)
