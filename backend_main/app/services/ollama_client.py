"""
Thin wrapper around a local Ollama server's /api/generate endpoint.

Used for:
  1. Turning a batch of raw lint issues into a human-readable .txt report.
  2. Answering "Ask AI what is it" for a single issue.
  3. Single-issue code fixes (see quick_fix.py, which calls fix_snippet).
  4. Translation (translate_text below) - the one place a caller can pick a
     different model than the configured default, since the Translate tab
     lets the user choose which installed Ollama model to use.

None of these touch the user's files directly - they only ever see
already-extracted text - so calling Ollama here is safe, unlike
aider_runner/pty_session which actually run code-editing sessions.
"""
from __future__ import annotations
import json
import re
import requests
from typing import Any, Dict, List, Optional

from app import config


def _generate(prompt: str, system: str | None = None, model: str | None = None) -> str:
    payload = {
        "model": model or config.OLLAMA_MODEL,
        "prompt": prompt,
        "stream": False,
        "options": {
            "temperature": 0.1,
        },
    }
    if system:
        payload["system"] = system
    resp = requests.post(f"{config.OLLAMA_BASE_URL}/api/generate", json=payload, timeout=300)
    resp.raise_for_status()
    data = resp.json()
    if not isinstance(data, dict):
        raise ValueError("Ollama returned a non-object response")
    return str(data.get("response") or "").strip()


def summarize_issues(issues: List[Dict[str, Any]], analyzed_files: List[str]) -> str:
    """Produce the plain-text report shown/downloaded in the Static Analysis tab."""
    if not issues:
        return (
            "Static Code Analysis Report\n"
            "============================\n\n"
            f"Files analyzed: {', '.join(analyzed_files)}\n\n"
            "No issues found. Nice and clean!"
        )

    lines = []
    for i in issues:
        lines.append(
            f"[{i['severity'].upper()}] {i['file']}:{i['line']} "
            f"({i['tool']}/{i['rule']}) - {i['message']}"
        )
    raw_block = "\n".join(lines)

    system = (
        "You are a senior code reviewer. You will be given a raw list of "
        "static analysis findings. Write a concise plain-text summary report "
        "for a developer: group by severity, call out the most important "
        "issues first, mention recurring patterns, and end with a short "
        "prioritized action list. Do not use markdown formatting, just plain "
        "text with simple headings and dashes."
    )
    prompt = (
        f"Files analyzed: {', '.join(analyzed_files)}\n"
        f"Total findings: {len(issues)}\n\n"
        f"Raw findings:\n{raw_block}\n\n"
        "Write the summary report now."
    )
    try:
        summary = _generate(prompt, system=system)
    except (requests.RequestException, ValueError) as e:
        summary = f"(Ollama unavailable, showing raw findings instead: {e})\n\n{raw_block}"

    header = (
        "Static Code Analysis Report\n"
        "============================\n\n"
        f"Files analyzed: {', '.join(analyzed_files)}\n"
        f"Total findings: {len(issues)}\n\n"
        "--- AI Summary "
        + "-" * 60 + "\n"
    )
    footer = (
        "\n\n--- Raw Findings " + "-" * 58 + "\n" + raw_block + "\n"
    )
    return header + summary + footer


def explain_issue(issue: Dict[str, Any], file_snippet: str | None = None) -> str:
    system = (
        "You are a helpful senior engineer explaining a static analysis "
        "finding to a teammate. Be concise (4-8 sentences): explain what the "
        "rule means, why it's flagged here, and what real-world risk or bad "
        "practice it points to. Plain text, no markdown."
    )
    prompt = (
        f"Tool: {issue['tool']}\n"
        f"Rule: {issue['rule']}\n"
        f"Severity: {issue['severity']}\n"
        f"File: {issue['file']}, line {issue['line']}\n"
        f"Message: {issue['message']}\n"
    )
    if file_snippet:
        prompt += f"\nRelevant code around that line:\n{file_snippet}\n"
    prompt += "\nExplain this finding."
    try:
        return _generate(prompt, system=system)
    except (requests.RequestException, ValueError) as e:
        return f"Could not reach Ollama at {config.OLLAMA_BASE_URL}: {e}"


def fix_snippet(
    issue: Dict[str, Any], snippet: str, start_line: int, end_line: int, filename: str,
    extra_instructions: str | None = None,
) -> str:
    """Ask Ollama to fix ONLY a small window of code around a single issue.

    This is a single stateless call - no `context` array is passed and
    nothing here is reused between calls, so every fix gets a completely
    fresh model context. Combined with each fix running on its own
    background thread (see jobs.run_in_background), concurrent fixes never
    share state with one another.
    """
    system = (
        "You are an expert software engineer fixing one static analysis "
        "finding. You will be given the finding and a small window of "
        "surrounding source code. Return ONLY the corrected version of that "
        "exact code window, with the same number of lines where possible, "
        "fixing just the reported issue. Preserve indentation, whitespace "
        "style, and all unrelated code exactly. Do not add explanations, "
        "comments about the fix, or markdown code fences - return raw code "
        "only."
    )
    prompt = (
        f"File: {filename}\n"
        f"Tool: {issue['tool']}, Rule: {issue['rule']}, Severity: {issue['severity']}\n"
        f"Reported at line {issue['line']}\n"
        f"Message: {issue['message']}\n\n"
        f"Code window (lines {start_line}-{end_line}):\n"
        f"{snippet}\n"
    )
    if extra_instructions:
        prompt += f"\nAdditional instructions from the developer:\n{extra_instructions}\n"
    prompt += "\nReturn the corrected code window now."
    return _generate(prompt, system=system)


_JSON_OBJECT_RE = re.compile(r"\{.*\}", re.DOTALL)


def _parse_translate_response(raw: str, fallback_text: str) -> Dict[str, Optional[str]]:
    """The translate prompt asks for strict JSON, but models don't always
    comply perfectly (extra prose, code fences, etc). Try progressively
    looser parsing before giving up and just returning the raw text as the
    translation - a translation call should never hard-fail just because the
    model wrapped its answer oddly.
    """
    candidates = [raw.strip()]
    fenced = re.match(r"^```[a-zA-Z0-9_+-]*\n(.*?)\n?```$", raw.strip(), re.DOTALL)
    if fenced:
        candidates.append(fenced.group(1).strip())
    match = _JSON_OBJECT_RE.search(raw)
    if match:
        candidates.append(match.group(0))

    for candidate in candidates:
        try:
            data = json.loads(candidate)
            if isinstance(data, dict) and "translation" in data:
                return {
                    "detected_source_lang": data.get("detected_source_lang") or None,
                    "translation": str(data["translation"]),
                }
        except (json.JSONDecodeError, TypeError):
            continue

    # Model ignored the JSON instruction entirely - treat its whole reply as
    # the translation rather than failing the request.
    return {"detected_source_lang": None, "translation": raw.strip() or fallback_text}


def explain_how_to_fix(
    issue: Dict[str, Any], full_file_text: str, filename: str, model: Optional[str] = None,
) -> Dict[str, Any]:
    """"How to Fix" for a single issue: unlike fix_snippet (small window,
    writes immediately), this sends the model the ENTIRE file as context so
    it can reason about the full picture, but still asks for a small,
    line-ranged correction so the diff shown to the user stays focused and
    readable. Nothing is written to disk by this call - it only returns an
    explanation plus a suggested change for the caller to show as a preview.
    """
    system = (
        "You are an expert code reviewer helping fix ONE specific static "
        "analysis finding in a file. You will be given the finding and the "
        "COMPLETE source file for context. Respond with STRICT JSON only, "
        "no markdown, no commentary outside the JSON, matching exactly this "
        'shape: {"explanation": "<2-5 sentence explanation, in plain '
        'English, of what is wrong and how to fix it>", "start_line": '
        "<first line number of the corrected block, 1-indexed>, "
        '"end_line": <last line number of the corrected block>, '
        '"fixed_code": "<the corrected code for exactly that line range, '
        'preserving indentation and all unrelated code in that range '
        'exactly except for the fix itself>"}. Keep the corrected block as '
        "small as possible while still fully fixing the issue - ideally "
        "just the affected line(s) plus a little surrounding context for "
        "readability."
    )
    prompt = (
        f"File: {filename}\n"
        f"Tool: {issue['tool']}, Rule: {issue['rule']}, Severity: {issue['severity']}\n"
        f"Reported at line {issue['line']}\n"
        f"Message: {issue['message']}\n\n"
        f"Complete file contents:\n{full_file_text}\n"
    )
    raw = _generate(prompt, system=system, model=model)
    return _parse_how_to_fix_response(raw)


def _parse_how_to_fix_response(raw: str) -> Dict[str, Any]:
    candidates = [raw.strip()]
    fenced = re.match(r"^```[a-zA-Z0-9_+-]*\n(.*?)\n?```$", raw.strip(), re.DOTALL)
    if fenced:
        candidates.append(fenced.group(1).strip())
    match = _JSON_OBJECT_RE.search(raw)
    if match:
        candidates.append(match.group(0))
    for c in candidates:
        try:
            data = json.loads(c)
            if isinstance(data, dict) and "explanation" in data:
                return data
        except (json.JSONDecodeError, TypeError):
            continue
    # Model ignored the JSON instruction - still surface its reply as the
    # explanation rather than failing the request outright; there's just no
    # diff to show in that case (fixed_code left empty).
    return {"explanation": raw.strip(), "start_line": None, "end_line": None, "fixed_code": ""}


def translate_text(
    text: str, source_lang: str, target_lang: str, model: Optional[str] = None,
) -> Dict[str, Optional[str]]:
    """Translate `text` into `target_lang`. If `source_lang` is "auto" (or
    empty), the model is asked to detect the source language itself and
    report what it detected. Returns
    {"detected_source_lang": <name or None>, "translation": <text>}.

    This is a single stateless call, same isolation model as fix_snippet -
    no shared context between translate requests.
    """
    is_auto = not source_lang or source_lang == "auto"
    source_instruction = (
        "Detect the source language automatically."
        if is_auto else
        f"The source language is {source_lang}."
    )
    system = (
        "You are a professional translator. Respond with STRICT JSON only - "
        "no markdown, no code fences, no commentary before or after - "
        'matching exactly this shape: {"detected_source_lang": '
        '"<source language name>", "translation": "<translated text>"}. '
        "Preserve the original meaning, tone, and formatting (line breaks, "
        "punctuation, capitalization style) as naturally as possible in the "
        "target language. Always fill in detected_source_lang with your "
        "best identification of the source language, even if it was given "
        "to you rather than detected."
    )
    prompt = (
        f"{source_instruction}\n"
        f"Translate the following text into {target_lang}.\n\n"
        f"Text:\n{text}\n"
    )
    raw = _generate(prompt, system=system, model=model)
    return _parse_translate_response(raw, fallback_text=text)


def describe_and_translate_image(image_b64: str, target_lang: str, model: str) -> Dict[str, Any]:
    """Analyzes an uploaded image with a vision-capable model: returns a
    natural-language description of what it shows, plus - if it contains
    any visible text - that text and its translation into `target_lang`.
    Single stateless call, same isolation model as everything else here.
    """
    system = (
        "You are an expert image analyst and translator. Respond with "
        'STRICT JSON only, no markdown, no commentary outside the JSON, '
        'matching exactly this shape: {"description": "<a clear, detailed '
        '2-4 sentence description of what this image shows - the scene, '
        'subjects, setting, and any notable details>", "has_text": true or '
        'false, "detected_text": "<any visible text found in the image, '
        'verbatim, or empty if none>", "translation": "<that text '
        'translated into the target language, or empty if none found>"}.'
    )
    prompt = (
        f"Describe this image in detail. Separately, check whether it "
        f"contains any visible text (signs, labels, captions, handwriting, "
        f"etc.) and, if so, translate that text into {target_lang}."
    )
    payload = {
        "model": model,
        "prompt": prompt,
        "system": system,
        "images": [image_b64],
        "stream": False,
    }
    resp = requests.post(f"{config.OLLAMA_BASE_URL}/api/generate", json=payload, timeout=180)
    resp.raise_for_status()
    raw = resp.json().get("response", "").strip()
    return _parse_image_response(raw)


def _parse_image_response(raw: str) -> Dict[str, Any]:
    candidates = [raw.strip()]
    fenced = re.match(r"^```[a-zA-Z0-9_+-]*\n(.*?)\n?```$", raw.strip(), re.DOTALL)
    if fenced:
        candidates.append(fenced.group(1).strip())
    match = _JSON_OBJECT_RE.search(raw)
    if match:
        candidates.append(match.group(0))
    for c in candidates:
        try:
            data = json.loads(c)
            if isinstance(data, dict) and "description" in data:
                return {
                    "description": data.get("description") or "",
                    "has_text": bool(data.get("has_text")),
                    "detected_text": data.get("detected_text") or "",
                    "translation": data.get("translation") or "",
                }
        except (json.JSONDecodeError, TypeError):
            continue
    # Model ignored the JSON instruction - still surface its reply as the
    # description rather than failing the request outright.
    return {"description": raw.strip(), "has_text": False, "detected_text": "", "translation": ""}
