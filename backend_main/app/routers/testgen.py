from __future__ import annotations
from fastapi import APIRouter, HTTPException

from app import config
from app.models import TestGenDefaultPromptResponse, TestGenStartRequest, TestGenStartResponse
from app.services import pty_session

router = APIRouter(prefix="/api/testgen", tags=["testgen"])

DEFAULT_TESTGEN_PROMPT = (
    "Write a thorough automated test suite for the attached file(s). Use "
    "the idiomatic test framework for this language (e.g. pytest for "
    "Python, JUnit for Java, Jest/Mocha for JavaScript/TypeScript). Cover "
    "normal cases, edge cases, and error handling. Create the test file(s) "
    "following this project's naming convention (e.g. test_<name>.py / "
    "<Name>Test.java / <name>.test.js) rather than editing the source "
    "file(s) directly. If you are unsure whether to add a file to the "
    "chat or overwrite something, ask me first."
)


@router.get("/default-prompt", response_model=TestGenDefaultPromptResponse)
async def default_prompt():
    return TestGenDefaultPromptResponse(prompt=DEFAULT_TESTGEN_PROMPT)


@router.post("/start", response_model=TestGenStartResponse)
async def start_session(req: TestGenStartRequest):
    """Starts an isolated, interactive aider session attached to a PTY and
    returns a session_id. Connect to `/api/pty/ws/{session_id}` next to
    see the live terminal and answer any Y/N prompts aider asks (a small
    list of known low-value prompts, like the LLM-warnings documentation
    link, are auto-answered "No" - see services/pty_session.py).
    """
    ws = config.workspace_dir(req.workspace)
    if not req.files:
        raise HTTPException(400, "No files attached")
    for f in req.files:
        try:
            p = config.safe_file_path(req.workspace, f)
        except ValueError as e:
            raise HTTPException(400, str(e))
        if not p.exists():
            raise HTTPException(404, f"{f} not found in workspace")
    if not req.prompt.strip():
        raise HTTPException(400, "Prompt cannot be empty")

    session = pty_session.start_session(ws, req.files, req.prompt, kind="testgen")
    return TestGenStartResponse(session_id=session.id)
