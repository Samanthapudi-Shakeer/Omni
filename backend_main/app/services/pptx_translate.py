"""
Translate a .pptx file: every <a:t> text run in each slide (and speaker
note), plus any visible text found in images under ppt/media/.

A .pptx is a zip of OOXML parts. Text runs in slides/notes live in
<a:t>...</a:t> (drawingml namespace), grouped into paragraphs (<a:p>).
Translation happens per-paragraph (not per-run) so a sentence split across
several runs purely for formatting reasons (e.g. one bolded word) is
translated as one coherent unit - see
office_translate_common.translate_grouped_runs for exactly how that works
and what it preserves vs. collapses. After translating each slide, text
bodies are nudged toward "shrink text on overflow" (ensure_shrink_to_fit)
so a translation that runs longer than the original is far less likely to
overflow its box and visually overlap neighboring shapes.
"""
from __future__ import annotations
import re
import shutil
import uuid
import zipfile
from pathlib import Path
from typing import Dict, Optional

from app.services import office_translate_common as common

ProgressCB = common.ProgressCB

_A_P_RE = re.compile(r"(<a:p(?:\s[^>]*)?>)(.*?)(</a:p>)", re.DOTALL)
_A_T_RE = re.compile(r"(<a:t(?:\s[^>]*)?>)(.*?)(</a:t>)", re.DOTALL)


def _slide_sort_key(p: Path) -> int:
    m = re.search(r"\d+", p.stem)
    return int(m.group()) if m else 0


def translate_pptx(
    input_path: Path, output_path: Path,
    source_lang: str, target_lang: str, model: str,
    vision_model: Optional[str], progress_cb: ProgressCB = common.noop,
) -> dict:
    work_dir = output_path.parent / f".pptx_work_{uuid.uuid4().hex[:8]}"
    work_dir.mkdir(parents=True, exist_ok=True)
    try:
        progress_cb(f"Unpacking {input_path.name}…")
        with zipfile.ZipFile(input_path, "r") as zf:
            zf.extractall(work_dir)

        slides_dir = work_dir / "ppt" / "slides"
        slide_files = sorted(slides_dir.glob("slide*.xml"), key=_slide_sort_key) if slides_dir.exists() else []

        notes_dir = work_dir / "ppt" / "notesSlides"
        notes_files = sorted(notes_dir.glob("notesSlide*.xml")) if notes_dir.exists() else []

        cache: Dict[str, str] = {}
        total_runs = 0

        progress_cb(f"Found {len(slide_files)} slide(s) to translate.")
        for idx, sf in enumerate(slide_files, start=1):
            progress_cb(f"Translating slide {idx}/{len(slide_files)}…")
            xml_text = sf.read_text(encoding="utf-8")
            new_xml, count = common.translate_grouped_runs(
                xml_text, _A_P_RE, _A_T_RE, source_lang, target_lang, model, cache, progress_cb,
            )
            new_xml = common.ensure_shrink_to_fit(new_xml)
            sf.write_text(new_xml, encoding="utf-8")
            total_runs += count

        if notes_files:
            progress_cb(f"Translating {len(notes_files)} speaker note(s)…")
        for nf in notes_files:
            xml_text = nf.read_text(encoding="utf-8")
            new_xml, count = common.translate_grouped_runs(
                xml_text, _A_P_RE, _A_T_RE, source_lang, target_lang, model, cache, progress_cb,
            )
            new_xml = common.ensure_shrink_to_fit(new_xml)
            nf.write_text(new_xml, encoding="utf-8")
            total_runs += count

        images_found, images_translated = common.translate_images_in_dir(
            work_dir / "ppt" / "media", target_lang, vision_model, progress_cb,
        )

        progress_cb("Repackaging .pptx…")
        common.rezip(work_dir, output_path)

        return {
            "slides": len(slide_files),
            "notes_slides": len(notes_files),
            "text_runs_translated": total_runs,
            "images_found": images_found,
            "images_translated": images_translated,
        }
    finally:
        shutil.rmtree(work_dir, ignore_errors=True)
