"""
Translate tab backend.

Endpoints:
  - GET  /api/translate/languages     - curated language list for the dropdowns
  - GET  /api/translate/models        - locally installed Ollama models
  - GET  /api/translate/vision-models - subset that look vision-capable
  - POST /api/translate               - plain text translation
  - POST /api/translate/image         - upload a standalone image: description + text translation
  - POST /api/translate/pptx          - translate a PowerPoint file
  - POST /api/translate/docx          - translate a Word document
  - POST /api/translate/xlsx          - translate an Excel workbook

Each plain-text/image translate call is a single, stateless Ollama request
(same isolation pattern as quick_fix's per-issue fixes). The document
endpoints run as background jobs (many Ollama calls under the hood) - see
services/pptx_translate.py, docx_translate.py, xlsx_translate.py for how
each format is walked, and office_translate_common.py for the shared
regex-substitution / image-overlay mechanics all three build on.
"""
from __future__ import annotations
import base64
import requests
from fastapi import APIRouter, HTTPException, UploadFile, File, Form

from app import config
from app.models import (
    TranslateLanguagesResponse, TranslateLanguage,
    TranslateModelsResponse, OllamaModelInfo,
    TranslateRequest, TranslateResponse, ImageTranslateResponse,
    TranslateOfficeDocRequest, StartJobResponse,
)
from app.services import ollama_client, pptx_translate, docx_translate, xlsx_translate, jobs

router = APIRouter(prefix="/api/translate", tags=["translate"])

# A curated, practical list for the dropdowns. This does NOT limit what the
# model can actually translate to/from - any language name it understands
# works - it just keeps the UI's source/target pickers sane and keeps the
# swap-language logic (frontend) always able to resolve a valid code.
LANGUAGES: list[tuple[str, str]] = [
    ("en", "English"), ("es", "Spanish"), ("fr", "French"), ("de", "German"),
    ("it", "Italian"), ("pt", "Portuguese"), ("nl", "Dutch"), ("ru", "Russian"),
    ("zh", "Chinese (Simplified)"), ("ja", "Japanese"), ("ko", "Korean"),
    ("ar", "Arabic"), ("hi", "Hindi"), ("bn", "Bengali"), ("ur", "Urdu"),
    ("tr", "Turkish"), ("vi", "Vietnamese"), ("th", "Thai"), ("id", "Indonesian"),
    ("pl", "Polish"), ("uk", "Ukrainian"), ("sv", "Swedish"), ("el", "Greek"),
    ("he", "Hebrew"), ("kn", "Kannada"), ("ta", "Tamil"), ("te", "Telugu"),
    ("ml", "Malayalam"), ("mr", "Marathi"), ("gu", "Gujarati"), ("pa", "Punjabi"),
]
_NAME_BY_CODE = dict(LANGUAGES)


def _resolve_lang_code(detected_name: str | None) -> str | None:
    """Best-effort match of a free-text detected language name (from the
    model) back to one of our dropdown codes, so the frontend can use it for
    the swap button without guessing. Returns None if nothing matches
    confidently - callers must handle that gracefully, never error on it.
    """
    if not detected_name:
        return None
    norm = detected_name.strip().lower()
    for code, name in LANGUAGES:
        if name.lower() == norm:
            return code
    for code, name in LANGUAGES:
        base = name.lower().split(" (")[0]
        if base == norm or base in norm or norm in base:
            return code
    return None


@router.get("/languages", response_model=TranslateLanguagesResponse)
async def languages():
    langs = [TranslateLanguage(code=c, name=n) for c, n in LANGUAGES]
    source = [TranslateLanguage(code="auto", name="Auto Detect")] + langs
    return TranslateLanguagesResponse(source_languages=source, target_languages=langs)


@router.get("/models", response_model=TranslateModelsResponse)
async def models():
    """Lists locally installed Ollama models. Falls back to just the
    configured default model if Ollama isn't reachable or has none pulled,
    so the dropdown is never empty.
    """
    items: list[OllamaModelInfo] = []
    try:
        resp = requests.get(f"{config.OLLAMA_BASE_URL}/api/tags", timeout=5)
        resp.raise_for_status()
        data = resp.json()
        items = [
            OllamaModelInfo(name=m["name"], size_bytes=m.get("size"))
            for m in data.get("models", [])
            if m.get("name")
        ]
    except requests.RequestException:
        pass
    if not items:
        items = [OllamaModelInfo(name=config.OLLAMA_MODEL)]
    return TranslateModelsResponse(models=items, default_model=config.OLLAMA_MODEL)


_VISION_NAME_HINTS = (
    "llava", "vision", "bakllava", "moondream", "minicpm-v",
    "qwen2-vl", "qwen2.5vl", "qwen2.5-vl", "pixtral", "gemma3",
)


@router.get("/vision-models", response_model=TranslateModelsResponse)
async def vision_models():
    """Best-effort filter of installed models down to ones that look
    multimodal/vision-capable by name. Ollama's /api/tags doesn't reliably
    expose a capability flag across versions, so this is a heuristic - the
    PPTX translate UI always also offers "Skip images" regardless of what
    (if anything) shows up here.
    """
    all_models = await models()
    filtered = [m for m in all_models.models if any(h in m.name.lower() for h in _VISION_NAME_HINTS)]
    return TranslateModelsResponse(
        models=filtered or all_models.models, default_model=all_models.default_model,
    )


@router.post("", response_model=TranslateResponse)
async def translate(req: TranslateRequest):
    text = req.text.strip()
    if not text:
        raise HTTPException(400, "Text to translate cannot be empty")
    if not req.target_lang:
        raise HTTPException(400, "Target language is required")

    target_name = _NAME_BY_CODE.get(req.target_lang, req.target_lang)
    source_name = (
        "auto" if req.source_lang in (None, "", "auto")
        else _NAME_BY_CODE.get(req.source_lang, req.source_lang)
    )
    model = req.model or config.OLLAMA_MODEL

    try:
        result = ollama_client.translate_text(text, source_name, target_name, model=model)
    except (requests.RequestException, ValueError) as e:
        raise HTTPException(502, f"Could not reach Ollama at {config.OLLAMA_BASE_URL}: {e}")

    detected_name = result.get("detected_source_lang")
    return TranslateResponse(
        translation=result.get("translation") or "",
        detected_source_lang=detected_name,
        detected_source_code=_resolve_lang_code(detected_name),
        model=model,
    )


_MAX_IMAGE_BYTES = 15 * 1024 * 1024  # 15MB - generous but bounded, since it's base64-encoded whole into one request


@router.post("/image", response_model=ImageTranslateResponse)
async def translate_image_endpoint(
    file: UploadFile = File(...),
    model: str = Form(...),
    target_lang: str = Form("en"),
):
    """Standalone image upload (not tied to any workspace file): sends the
    image to a vision-capable model and returns a description of what it
    shows plus - if it contains visible text - that text and its
    translation. One stateless call, same isolation model as everything
    else in this router.
    """
    if not model:
        raise HTTPException(400, "A vision model is required")
    if not file.content_type or not file.content_type.startswith("image/"):
        raise HTTPException(400, "Uploaded file must be an image")

    data = await file.read()
    if not data:
        raise HTTPException(400, "Uploaded file is empty")
    if len(data) > _MAX_IMAGE_BYTES:
        raise HTTPException(400, f"Image too large (max {_MAX_IMAGE_BYTES // (1024 * 1024)}MB)")

    image_b64 = base64.b64encode(data).decode()
    target_name = _NAME_BY_CODE.get(target_lang, target_lang)

    try:
        result = ollama_client.describe_and_translate_image(image_b64, target_name, model)
    except (requests.RequestException, ValueError) as e:
        raise HTTPException(502, f"Could not reach Ollama at {config.OLLAMA_BASE_URL}: {e}")

    return ImageTranslateResponse(**result, model=model)


@router.post("/pptx", response_model=StartJobResponse)
async def translate_pptx_endpoint(req: TranslateOfficeDocRequest):
    """Translates every text run in a .pptx's slides (and speaker notes),
    and optionally runs every image in its media folder through a vision
    model to detect + translate visible text. See services/pptx_translate.py
    for exactly how it works and its known limitations (image text is
    overlaid as a caption, not replaced pixel-for-pixel).
    """
    return _start_office_translate_job(
        req, expected_suffix=".pptx", kind="translate_pptx",
        run=pptx_translate.translate_pptx,
    )


@router.post("/docx", response_model=StartJobResponse)
async def translate_docx_endpoint(req: TranslateOfficeDocRequest):
    """Translates every text run in a .docx's body, headers/footers,
    footnotes/endnotes, and comments, plus optional image text. See
    services/docx_translate.py.
    """
    return _start_office_translate_job(
        req, expected_suffix=".docx", kind="translate_docx",
        run=docx_translate.translate_docx,
    )


@router.post("/xlsx", response_model=StartJobResponse)
async def translate_xlsx_endpoint(req: TranslateOfficeDocRequest):
    """Translates every cell's text (via the shared strings table and any
    inline strings), comments/notes, and chart text in a .xlsx workbook,
    plus optional image text. Formulas, numeric values, and sheet names are
    never touched. See services/xlsx_translate.py.
    """
    return _start_office_translate_job(
        req, expected_suffix=".xlsx", kind="translate_xlsx",
        run=xlsx_translate.translate_xlsx,
    )


def _start_office_translate_job(req: TranslateOfficeDocRequest, expected_suffix: str, kind: str, run) -> StartJobResponse:
    ws = config.workspace_dir(req.workspace)
    try:
        input_path = config.safe_file_path(req.workspace, req.file)
    except ValueError as e:
        raise HTTPException(400, str(e))
    if not input_path.exists():
        raise HTTPException(404, f"{req.file} not found in workspace")
    if input_path.suffix.lower() != expected_suffix:
        raise HTTPException(400, f"File must be a {expected_suffix}")

    target_name = _NAME_BY_CODE.get(req.target_lang, req.target_lang)
    source_name = (
        "auto" if req.source_lang in (None, "", "auto")
        else _NAME_BY_CODE.get(req.source_lang, req.source_lang)
    )
    model = req.model or config.OLLAMA_MODEL
    output_name = f"translated_{req.target_lang}_{input_path.name}"
    output_path = ws / output_name

    job = jobs.create_job(kind=kind, label=f"Translate {expected_suffix[1:].upper()}: {req.file} → {target_name}")

    def _work(progress_cb):
        stats = run(
            input_path, output_path, source_name, target_name, model,
            req.vision_model, progress_cb=progress_cb,
        )
        return {"status": "ok", "output_file": output_name, **stats}

    jobs.run_in_background(job.id, _work)
    return StartJobResponse(job_id=job.id)
