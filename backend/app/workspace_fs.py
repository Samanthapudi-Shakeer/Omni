import subprocess
from pathlib import Path

IGNORE_DIRS = {".git", "node_modules", "__pycache__", ".venv", ".aider.tags.cache.v3"}


def list_ignored_files(workspace_dir: Path) -> set:
    """Every path git considers ignored in this workspace (per its
    .gitignore, global excludes, etc.), using `git` itself rather than
    reimplementing gitignore pattern matching. Returns an empty set if this
    isn't a git repo or the command fails for any reason -- filtering is a
    nice-to-have, never a hard requirement for listing files."""
    try:
        res = subprocess.run(
            ["git", "ls-files", "--others", "--ignored", "--exclude-standard"],
            cwd=workspace_dir, capture_output=True, text=True, timeout=10,
        )
        if res.returncode != 0:
            return set()
        return {line.strip() for line in res.stdout.splitlines() if line.strip()}
    except (OSError, subprocess.SubprocessError):
        return set()


def list_workspace_files(workspace_dir: Path, max_files: int = 5000, ignored: set = None) -> list[dict]:
    ignored = ignored or set()
    results: list[dict] = []

    def walk(dir_path: Path):
        if len(results) >= max_files:
            return
        try:
            entries = sorted(dir_path.iterdir(), key=lambda p: p.name)
        except OSError:
            return
        for entry in entries:
            if len(results) >= max_files:
                return
            if entry.name.startswith(".") and entry.name != ".env.example":
                if entry.is_dir():
                    continue
            if entry.is_dir():
                if entry.name in IGNORE_DIRS:
                    continue
                walk(entry)
            elif entry.is_file():
                rel = entry.relative_to(workspace_dir)
                rel_str = str(rel).replace("\\", "/")
                if rel_str in ignored:
                    continue
                try:
                    size = entry.stat().st_size
                except OSError:
                    size = 0
                results.append({"path": rel_str, "size": size})

    walk(workspace_dir)
    return results


def safe_resolve(workspace_dir: Path, rel_path: str) -> Path:
    """Resolve a user-supplied path against the workspace root, refusing
    anything that would escape it (absolute paths, .. traversal, symlink
    games). Returns the safe absolute path or raises ValueError."""
    if not rel_path or not isinstance(rel_path, str):
        raise ValueError("Invalid path")

    root = workspace_dir.resolve()
    candidate = (root / rel_path).resolve()

    if candidate != root and root not in candidate.parents:
        raise ValueError("Path escapes workspace directory")
    return candidate
