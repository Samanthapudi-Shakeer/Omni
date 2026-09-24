import re
from pathlib import Path
from typing import Dict

from .aider_session import AiderSession
from .ws_manager import WSManager

NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")


class WorkspaceManager:
    def __init__(self, root: Path, aider_bin: str, ollama_base: str, default_model: str, default_mode: str, lint_cmd: str = ""):
        self.root = root
        self.aider_bin = aider_bin
        self.ollama_base = ollama_base
        self.default_model = default_model
        self.default_mode = default_mode
        self.lint_cmd = lint_cmd
        self.ws_hub = WSManager()
        self.sessions: Dict[str, AiderSession] = {}
        # Separate, hidden Aider sessions for the Modularization and Test
        # Case Generation tools -- same workspace directory as the main
        # console session, but a completely independent process, so using
        # these tools never interrupts whatever the user is doing in the
        # visible Aider Console. Keyed by "<workspace>::<purpose>".
        self.tool_sessions: Dict[str, AiderSession] = {}
        self._discover_existing()

    def _discover_existing(self):
        """Pick up workspace directories that already exist on disk (e.g.
        from a previous run of the server) so they show up as selectable
        without needing to be re-created."""
        for entry in sorted(self.root.iterdir()) if self.root.exists() else []:
            if entry.is_dir() and NAME_RE.match(entry.name):
                self._get_or_create_session(entry.name)

    @staticmethod
    def validate_name(name: str):
        if not name or not NAME_RE.match(name):
            raise ValueError(
                "Workspace name must be 1-64 characters: letters, numbers, dots, "
                "underscores, or hyphens only."
            )

    def list_workspaces(self) -> list[dict]:
        out = []
        for name, session in self.sessions.items():
            out.append({"name": name, "status": session.get_status()["status"]})
        return sorted(out, key=lambda w: w["name"])

    def create_workspace(self, name: str) -> dict:
        self.validate_name(name)
        path = self.root / name
        if path.exists():
            raise ValueError(f"Workspace '{name}' already exists.")
        path.mkdir(parents=True)
        session = self._get_or_create_session(name)
        return {"name": name, "status": session.get_status()["status"]}

    def _get_or_create_session(self, name: str) -> AiderSession:
        if name in self.sessions:
            return self.sessions[name]
        path = self.root / name
        path.mkdir(parents=True, exist_ok=True)

        async def broadcaster(message: dict, _name=name):
            await self.ws_hub.broadcast(_name, message)

        session = AiderSession(
            name=name,
            aider_bin=self.aider_bin,
            workspace_dir=str(path),
            ollama_base=self.ollama_base,
            model=self.default_model,
            mode=self.default_mode,
            broadcast=broadcaster,
            lint_cmd=self.lint_cmd,
        )
        self.sessions[name] = session
        return session

    def get_session(self, name: str) -> AiderSession:
        if name not in self.sessions:
            raise KeyError(f"Unknown workspace '{name}'")
        return self.sessions[name]

    def get_tool_session(self, workspace_name: str, purpose: str) -> AiderSession:
        """A dedicated, hidden Aider session for one of the standalone tools
        (Modularization, Test Case Generation) -- same workspace directory,
        own independent process. Auto-created on first use per
        (workspace, purpose) pair; reused afterward rather than spawning a
        fresh process every call."""
        path = self.root / workspace_name
        if not path.is_dir():
            raise KeyError(f"Unknown workspace '{workspace_name}'")
        key = f"{workspace_name}::{purpose}"
        if key in self.tool_sessions:
            return self.tool_sessions[key]

        async def broadcaster(message: dict, _key=key):
            await self.ws_hub.broadcast(_key, message)

        session = AiderSession(
            name=key,
            aider_bin=self.aider_bin,
            workspace_dir=str(path),
            ollama_base=self.ollama_base,
            model=self.default_model,
            mode=self.default_mode,
            broadcast=broadcaster,
            lint_cmd=self.lint_cmd,
            auto_confirm=False,
        )
        self.tool_sessions[key] = session
        return session

    def workspace_path(self, name: str) -> Path:
        return self.root / name
