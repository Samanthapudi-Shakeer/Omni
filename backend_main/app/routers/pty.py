"""
Shared WebSocket endpoint for interactive PTY sessions.

A session is identified purely by session_id in the shared registry in
services/pty_session.py - it doesn't matter whether Test Case Generation
or Modularization started it, so a single WebSocket route serves both
features rather than duplicating this plumbing per feature.

Every send/close here is defensively guarded: a client can disconnect at
any point (network blip, browser tab closed, page navigated away), and
none of that should ever surface as an unhandled exception in the server
log or leave a background task's exception unretrieved.
"""
from __future__ import annotations
import asyncio
import logging

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.services import pty_session

router = APIRouter(prefix="/api/pty", tags=["pty"])
logger = logging.getLogger(__name__)


async def _safe_send_json(websocket: WebSocket, payload: dict) -> bool:
    """Best-effort send - returns False (and swallows the error) if the
    client is already gone rather than raising."""
    try:
        await websocket.send_json(payload)
        return True
    except Exception:
        return False


async def _safe_close(websocket: WebSocket) -> None:
    try:
        await websocket.close()
    except Exception:
        pass  # already closed/disconnected - nothing to do


@router.websocket("/ws/{session_id}")
async def pty_terminal(websocket: WebSocket, session_id: str):
    try:
        await websocket.accept()
    except Exception:
        return  # client disconnected before the handshake even completed

    session = pty_session.get_session(session_id)
    if not session:
        await _safe_send_json(websocket, {"type": "error", "data": "Session not found or already closed."})
        await _safe_close(websocket)
        return

    async def pump_output():
        loop = asyncio.get_event_loop()
        while True:
            data = await loop.run_in_executor(None, session.output_queue.get)
            if data == b"":
                break
            ok = await _safe_send_json(websocket, {"type": "output", "data": data.decode(errors="replace")})
            if not ok:
                break  # client disconnected - stop trying to stream to it

        changed = pty_session.copy_back_changes(session)
        await _safe_send_json(websocket, {
            "type": "exit",
            "changed_files": [p.name for p in changed],
        })
        pty_session.drop_session(session_id)

    async def pump_input():
        try:
            while True:
                msg = await websocket.receive_json()
                if msg.get("type") == "input":
                    session.write(msg.get("data", "").encode())
                elif msg.get("type") == "resize":
                    session.resize(int(msg.get("rows", 24)), int(msg.get("cols", 80)))
        except WebSocketDisconnect:
            pass
        except Exception as e:  # noqa: BLE001 - malformed frame, closed socket, etc. - never crash the connection
            logger.debug("pty pump_input ending for session %s: %s", session_id, e)

    output_task = asyncio.create_task(pump_output())
    input_task = asyncio.create_task(pump_input())
    _, pending = await asyncio.wait(
        [output_task, input_task], return_when=asyncio.FIRST_COMPLETED
    )
    for t in pending:
        t.cancel()
    # Without this, a cancelled task's exception (including plain
    # asyncio.CancelledError) is never retrieved, which asyncio logs as an
    # unhandled "Task exception was never retrieved" warning - harmless
    # functionally, but exactly the kind of noisy console error this
    # endpoint should never produce.
    await asyncio.gather(*pending, return_exceptions=True)
