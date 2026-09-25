"""
Shared plumbing for the three Ollama-direct tools (Static Code Analysis
auto-fix, Modularization, Test Case Generation). All three call Ollama's
HTTP API directly -- no Aider, no PTY, no chat session, no auto-commit.
Results are diffed/shown to the user, who decides whether to save them.
"""

import difflib
import re

from .ollama_client import generate_direct


def strip_markdown_fences(text: str) -> str:
    """Models often wrap output in ```lang ... ``` even when told not to.
    Strip a single leading/trailing fence if present."""
    stripped = text.strip()
    if stripped.startswith("```"):
        stripped = re.sub(r"^```[a-zA-Z0-9_+-]*\n?", "", stripped)
        stripped = re.sub(r"\n?```\s*$", "", stripped)
    return stripped


def unified_text_diff(original: str, updated: str, path: str) -> str:
    original_lines = original.splitlines(keepends=True)
    updated_lines = updated.splitlines(keepends=True)
    diff = difflib.unified_diff(original_lines, updated_lines, fromfile=f"a/{path}", tofile=f"b/{path}")
    return "".join(diff)


async def run_file_transform(ollama_base: str, model: str, file_content: str, path: str, instruction: str) -> dict:
    """Sends the file + an instruction to Ollama directly, asking for the
    complete resulting file content back (not a diff -- models are much more
    reliable producing a full file than a hand-rolled patch format). We
    compute the diff ourselves afterward with difflib, which is exact."""
    full_prompt = (
        f"Here is the complete content of the file `{path}`:\n\n"
        f"```\n{file_content}\n```\n\n"
        f"{instruction}\n\n"
        "Return ONLY the complete resulting file content, ready to save exactly as-is. "
        "Do not include any explanation, commentary, or markdown code fences."
    )
    result = await generate_direct(ollama_base, model, full_prompt)
    if not result["ok"]:
        return {"ok": False, "error": result.get("error"), "model": result.get("model")}

    new_content = strip_markdown_fences(result["text"])
    diff = unified_text_diff(file_content, new_content, path)
    return {
        "ok": True,
        "original": file_content,
        "result": new_content,
        "diff": diff,
        "model": result["model"],
        "changed": new_content.strip() != file_content.strip(),
    }
