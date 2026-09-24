"""
Shared helpers for translating Office Open XML documents (.pptx, .docx,
.xlsx). Each format stores its actual text in a different XML tag, but the
mechanics are identical:

  - Find every occurrence of that tag with a regex (NOT a full XML
    parse-and-reserialize), translate the text inside, and substitute it
    back in place. This means every other tag, attribute, and piece of
    structure in the document is left byte-for-byte untouched - which
    matters a lot for not corrupting these formats (run properties,
    formulas, relationships, etc. never go anywhere near our code).
  - Identical strings are translated once and cached for the whole
    document, both to cut down on Ollama calls and to keep terminology
    consistent (e.g. a repeated header, "Page", a recurring label).
  - Images in the format's media folder are individually sent to a vision
    model to detect + translate any visible text, then overlaid as a
    caption on a copy of the image (same filename, so every relationship
    that points at it still resolves).

See pptx_translate.py / docx_translate.py / xlsx_translate.py for the
format-specific parts: which files to open and which tag holds the text in
each one.
"""
from __future__ import annotations
import base64
import json
import re
import textwrap
import zipfile
from pathlib import Path
from typing import Callable, Dict, Optional, Pattern, Tuple

import requests
from PIL import Image, ImageDraw, ImageFont
from xml.sax.saxutils import escape, unescape

from app import config
from app.services import ollama_client

ProgressCB = Callable[[str], None]


def noop(_msg: str) -> None:
    pass


IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".bmp", ".gif"}


def translate_tag_text(
    xml_text: str, tag_re: Pattern, source_lang: str, target_lang: str, model: str,
    cache: Dict[str, str], progress_cb: ProgressCB,
) -> Tuple[str, int]:
    """Translate every match of `tag_re` in xml_text in place.

    `tag_re` must have exactly 3 capture groups: the opening tag (with any
    attributes), the inner text, and the closing tag - see the *_TAG_RE
    constants in the format-specific modules.

    Use this for text elements that are already a single coherent unit on
    their own (no sibling runs to worry about) - e.g. xlsx threaded
    comments' `<text>` element. For anything organized into paragraphs or
    runs (slide/document text, shared strings, cell comments), use
    `translate_grouped_runs` below instead so multi-run sentences aren't
    translated as disconnected fragments.
    """
    count = 0

    def repl(m: re.Match) -> str:
        nonlocal count
        open_tag, inner, close_tag = m.group(1), m.group(2), m.group(3)
        raw = unescape(inner)
        stripped = raw.strip()
        if not stripped:
            return m.group(0)  # whitespace-only/empty - nothing to translate

        if stripped in cache:
            translated = cache[stripped]
        else:
            try:
                result = ollama_client.translate_text(raw, source_lang, target_lang, model=model)
                translated = result.get("translation") or raw
            except requests.RequestException as e:
                progress_cb(f"Translation failed for a text run ({e}); leaving original.")
                translated = raw
            cache[stripped] = translated
            count += 1
            preview = stripped[:40] + ("…" if len(stripped) > 40 else "")
            progress_cb(f"Translated: {preview!r}")

        return f"{open_tag}{escape(translated)}{close_tag}"

    new_xml = tag_re.sub(repl, xml_text)
    return new_xml, count


def translate_grouped_runs(
    xml_text: str, group_re: Pattern, run_re: Pattern,
    source_lang: str, target_lang: str, model: str,
    cache: Dict[str, str], progress_cb: ProgressCB,
) -> Tuple[str, int]:
    """Like `translate_tag_text`, but groups runs by an enclosing container
    first (a paragraph `<a:p>`/`<w:p>`, a shared-string item `<si>`, a
    comment, an inline string `<is>`) so a sentence that's split across
    several runs purely for formatting reasons (e.g. one bolded word mid-
    sentence) is translated as ONE coherent unit instead of disconnected
    fragments.

    Both `group_re` and `run_re` must have the same 3-group shape (open
    tag, inner content, close tag).

    Behavior per group:
    - 0 or 1 non-empty runs (the common case - most paragraphs/cells only
      have one run): translated exactly like `translate_tag_text` would -
      no structural change, that run's formatting is fully preserved.
    - 2+ non-empty runs: their text is concatenated and translated as a
      single unit for grammatical accuracy, then the full translation is
      written into the FIRST non-empty run and every other non-empty run
      in that group is cleared to an empty string. This is a deliberate,
      standard trade-off: the group's paragraph-level formatting (font,
      alignment, list level, etc., all untouched) is preserved, and the
      first run's character formatting now applies to the whole
      translated sentence - but formatting that varied *within* the
      original sentence (just that one bolded word) cannot be mapped onto
      the re-ordered/re-sized translated text in the general case, so it
      collapses to the first run's style rather than being silently
      dropped or scattered incoherently across mismatched fragments.
    """
    count = 0

    def translate_unit(raw: str) -> str:
        nonlocal count
        stripped = raw.strip()
        if stripped in cache:
            return cache[stripped]
        try:
            result = ollama_client.translate_text(raw, source_lang, target_lang, model=model)
            translated = result.get("translation") or raw
        except requests.RequestException as e:
            progress_cb(f"Translation failed for a text run ({e}); leaving original.")
            translated = raw
        cache[stripped] = translated
        count += 1
        preview = stripped[:40] + ("…" if len(stripped) > 40 else "")
        progress_cb(f"Translated: {preview!r}")
        return translated

    def repl_group(gm: re.Match) -> str:
        g_open, inner, g_close = gm.group(1), gm.group(2), gm.group(3)

        run_matches = list(run_re.finditer(inner))
        non_empty = [rm for rm in run_matches if unescape(rm.group(2)).strip()]

        if len(non_empty) <= 1:
            # Fast path: at most one run actually has text - translate it
            # alone, exactly like the simple tag-level substitution.
            def repl_run(rm: re.Match) -> str:
                r_open, text, r_close = rm.group(1), rm.group(2), rm.group(3)
                raw = unescape(text)
                if not raw.strip():
                    return rm.group(0)
                return f"{r_open}{escape(translate_unit(raw))}{r_close}"
            new_inner = run_re.sub(repl_run, inner)
            return f"{g_open}{new_inner}{g_close}"

        # Multiple runs carry real text in this one group - translate the
        # whole thing together for grammatical coherence, then merge.
        combined_raw = "".join(unescape(rm.group(2)) for rm in non_empty)
        translated = translate_unit(combined_raw)

        merged_once = False

        def repl_run_merge(rm: re.Match) -> str:
            nonlocal merged_once
            r_open, text, r_close = rm.group(1), rm.group(2), rm.group(3)
            if not unescape(text).strip():
                return rm.group(0)  # empty run - leave untouched
            if not merged_once:
                merged_once = True
                return f"{r_open}{escape(translated)}{r_close}"
            return f"{r_open}{r_close}"  # cleared - its text now lives in the first run

        new_inner = run_re.sub(repl_run_merge, inner)
        return f"{g_open}{new_inner}{g_close}"

    new_xml = group_re.sub(repl_group, xml_text)
    return new_xml, count


# Reduce the risk of translated text overflowing a fixed-size text box (and
# visually overlapping neighboring shapes) by ensuring text bodies shrink
# to fit rather than overflow. PowerPoint's own "Shrink text on overflow"
# behavior (<a:normAutofit/>) does this automatically once the file is
# opened, without us needing font-metric calculations of our own. Shared
# between pptx slides/notes and xlsx charts, which use the same DrawingML
# text-body structure.
_NOAUTOFIT_RE = re.compile(r"<a:noAutofit\s*/>")
_STALE_NORMAUTOFIT_RE = re.compile(r'<a:normAutofit(?:\s+fontScale="[^"]*")?(?:\s+lnSpcReduction="[^"]*")?\s*/>')
_SELFCLOSED_BODYPR_RE = re.compile(r"<a:bodyPr((?:\s[^>/]*)?)/>")


def ensure_shrink_to_fit(xml_text: str) -> str:
    """Nudges every text body toward "shrink text on overflow" instead of
    "overflow" or a stale cached font-scale computed for the pre-translation
    text length. Shapes explicitly set to auto-*grow* (`<a:spAutoFit/>`) are
    left alone - that's a deliberate authoring choice, not a default we
    should override.
    """
    # Explicit "no autofit" -> shrink-to-fit instead.
    xml_text = _NOAUTOFIT_RE.sub("<a:normAutofit/>", xml_text)
    # Existing shrink-to-fit with a cached percentage computed for the
    # ORIGINAL text -> reset so PowerPoint recomputes it fresh once opened.
    xml_text = _STALE_NORMAUTOFIT_RE.sub("<a:normAutofit/>", xml_text)
    # A bodyPr with no autofit child at all (fully self-closing) -> add
    # one, preserving whatever attributes (wrap, anchor, insets...) it had.
    xml_text = _SELFCLOSED_BODYPR_RE.sub(r"<a:bodyPr\1><a:normAutofit/></a:bodyPr>", xml_text)
    return xml_text


def _parse_vision_json(raw: str) -> Optional[dict]:
    candidates = [raw.strip()]
    fenced = re.match(r"^```[a-zA-Z0-9_+-]*\n(.*?)\n?```$", raw.strip(), re.DOTALL)
    if fenced:
        candidates.append(fenced.group(1).strip())
    match = re.search(r"\{.*\}", raw, re.DOTALL)
    if match:
        candidates.append(match.group(0))
    for c in candidates:
        try:
            data = json.loads(c)
            if isinstance(data, dict):
                return data
        except (json.JSONDecodeError, TypeError):
            continue
    return None


def detect_and_translate_image_text(
    img_path: Path, target_lang: str, vision_model: str,
) -> Optional[str]:
    """Asks the vision model if this image has visible text and, if so,
    returns the translation, else None (caller leaves the image untouched).
    """
    b64 = base64.b64encode(img_path.read_bytes()).decode()
    system = (
        "You detect and translate visible text in images. Respond with "
        'STRICT JSON only, no markdown, no commentary: {"has_text": '
        'true or false, "text": "<the original visible text, or empty>", '
        '"translation": "<that text translated into the target language, '
        'or empty>"}. If the image has no readable text, set has_text to '
        "false and leave text/translation empty."
    )
    prompt = f"Look at this image. Does it contain visible text? If so, translate that text into {target_lang}."
    payload = {
        "model": vision_model,
        "prompt": prompt,
        "system": system,
        "images": [b64],
        "stream": False,
    }
    resp = requests.post(f"{config.OLLAMA_BASE_URL}/api/generate", json=payload, timeout=180)
    resp.raise_for_status()
    raw = resp.json().get("response", "").strip()
    data = _parse_vision_json(raw)
    if not data or not data.get("has_text"):
        return None
    translation = (data.get("translation") or "").strip()
    return translation or None


def overlay_translated_text(img_path: Path, text: str) -> None:
    """Overwrites `img_path` with a copy that has `text` drawn on a
    semi-transparent caption band at the bottom.

    Known limitation: without OCR bounding boxes, this is a caption overlay
    rather than in-place pixel-for-pixel replacement of the original text.
    """
    img = Image.open(img_path).convert("RGBA")
    w, h = img.size
    band_height = max(28, int(h * 0.16))
    overlay = Image.new("RGBA", (w, band_height), (0, 0, 0, 190))
    draw = ImageDraw.Draw(overlay)
    try:
        font = ImageFont.truetype("DejaVuSans-Bold.ttf", size=max(12, band_height // 3))
    except Exception:
        font = ImageFont.load_default()

    wrap_width = max(10, int(w / max(1, band_height // 6)))
    wrapped = textwrap.fill(text, width=wrap_width)
    draw.multiline_text((8, 4), wrapped, fill=(255, 255, 255, 255), font=font, spacing=2)

    composed = img.copy()
    composed.paste(overlay, (0, h - band_height), overlay)

    if img_path.suffix.lower() in (".jpg", ".jpeg"):
        composed = composed.convert("RGB")
    composed.save(img_path)


def translate_images_in_dir(
    media_dir: Path, target_lang: str, vision_model: Optional[str], progress_cb: ProgressCB,
) -> Tuple[int, int]:
    """Walks every image in `media_dir`, overlays translated text where
    the vision model finds any. Returns (images_found, images_translated).
    """
    if not vision_model or not media_dir.exists():
        if media_dir.exists() and any(p.is_file() for p in media_dir.iterdir()):
            progress_cb("Skipping images (no vision model selected).")
        return 0, 0

    image_files = sorted(p for p in media_dir.iterdir() if p.is_file() and p.suffix.lower() in IMAGE_EXTS)
    if not image_files:
        return 0, 0

    progress_cb(f"Found {len(image_files)} image(s) in the media folder.")
    images_found = 0
    images_translated = 0
    for i, img_path in enumerate(image_files, start=1):
        images_found += 1
        progress_cb(f"Checking image {i}/{len(image_files)}: {img_path.name}…")
        try:
            translation = detect_and_translate_image_text(img_path, target_lang, vision_model)
        except requests.RequestException as e:
            progress_cb(f"Vision request failed for {img_path.name}: {e}")
            continue
        except Exception as e:  # noqa: BLE001 - a bad/corrupt image shouldn't kill the whole job
            progress_cb(f"Skipping {img_path.name}: {e}")
            continue
        if translation:
            overlay_translated_text(img_path, translation)
            images_translated += 1
            progress_cb(f"Overlaid translated text on {img_path.name}.")
        else:
            progress_cb(f"No text detected in {img_path.name} — left unchanged.")
    return images_found, images_translated


def rezip(work_dir: Path, output_path: Path) -> None:
    if output_path.exists():
        output_path.unlink()
    with zipfile.ZipFile(output_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for file in sorted(work_dir.rglob("*")):
            if file.is_file():
                zf.write(file, file.relative_to(work_dir))
