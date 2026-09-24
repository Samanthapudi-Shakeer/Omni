import json
from collections import defaultdict
from starlette.websockets import WebSocket


class WSManager:
    """Keeps one set of connected websockets per workspace name, so output
    from workspace A never leaks to a browser tab looking at workspace B."""

    def __init__(self):
        self.connections: dict[str, set[WebSocket]] = defaultdict(set)

    async def connect(self, name: str, ws: WebSocket):
        await ws.accept()
        self.connections[name].add(ws)

    def disconnect(self, name: str, ws: WebSocket):
        self.connections[name].discard(ws)

    async def broadcast(self, name: str, message: dict):
        payload = json.dumps(message)
        dead = []
        for ws in list(self.connections.get(name, ())):
            try:
                await ws.send_text(payload)
            except Exception:
                dead.append(ws)
        for ws in dead:
            self.connections[name].discard(ws)
