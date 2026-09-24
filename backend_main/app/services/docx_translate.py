"""
Translate a .docx file: every <w:t> text run in the main document, headers,
footers, footnotes, endnotes, and comments, plus any visible text found in
images under word/media/.

A .docx is a zip of OOXML parts. Text runs everywhere in it (body,
headers/footers, notes, comments) use the same <w:t>...</w:t> tag
(wordprocessingml namespace), grouped into paragraphs (<w:p>). Translation
happens per-paragraph (not per-run) so a sentence split across several runs
purely for formatting reasons (e.g. one bolded word) is translated as one
coherent unit - see office_translate_common.translate_grouped_runs for
exactly how that works and what it preserves vs. collapses.
"""
from __future__ import annotations
import re
import shutil
import uuid
import zipfile
from pathlib import Path
from typing import Dict, List, Optional

from app.services import office_translate_common as common

ProgressCB = common.ProgressCB

_W_P_RE = re.compile(r"(<w:p(?:\s[^>]*)?>)(.*?)(</w:p>)", re.DOTALL)
_W_T_RE = re.compile(r"(<w:t(?:\s[^>]*)?>)(.*?)(</w:t>)", re.DOTALL)

# Parts (beyond the main body) that can contain their own <w:t> text runs.
_AUXILIARY_GLOBS = [
    "header*.xml",
    "footer*.xml",
    "footnotes.xml",
    "endnotes.xml",
    "comments.xml",
]


def translate_docx(
    input_path: Path, output_path: Path,
    source_lang: str, target_lang: str, model: str,
    vision_model: Optional[str], progress_cb: ProgressCB = common.noop,
) -> dict:
    work_dir = output_path.parent / f".docx_work_{uuid.uuid4().hex[:8]}"
    work_dir.mkdir(parents=True, exist_ok=True)
    try:
        progress_cb(f"Unpacking {input_path.name}…")
        with zipfile.ZipFile(input_path, "r") as zf:
            zf.extractall(work_dir)

        word_dir = work_dir / "word"
        cache: Dict[str, str] = {}
        total_runs = 0

        doc_xml = word_dir / "document.xml"
        if doc_xml.exists():
            progress_cb("Translating main document body…")
            xml_text = doc_xml.read_text(encoding="utf-8")
            new_xml, count = common.translate_grouped_runs(
                xml_text, _W_P_RE, _W_T_RE, source_lang, target_lang, model, cache, progress_cb,
            )
            doc_xml.write_text(new_xml, encoding="utf-8")
            total_runs += count

        auxiliary_files: List[Path] = []
        if word_dir.exists():
            for pattern in _AUXILIARY_GLOBS:
                auxiliary_files.extend(sorted(word_dir.glob(pattern)))

        if auxiliary_files:
            progress_cb(f"Translating {len(auxiliary_files)} header/footer/note/comment part(s)…")
        for part in auxiliary_files:
            xml_text = part.read_text(encoding="utf-8")
            new_xml, count = common.translate_grouped_runs(
                xml_text, _W_P_RE, _W_T_RE, source_lang, target_lang, model, cache, progress_cb,
            )
            part.write_text(new_xml, encoding="utf-8")
            total_runs += count

        images_found, images_translated = common.translate_images_in_dir(
            word_dir / "media", target_lang, vision_model, progress_cb,
        )

        progress_cb("Repackaging .docx…")
        common.rezip(work_dir, output_path)

        return {
            "parts_translated": 1 + len(auxiliary_files) if doc_xml.exists() else len(auxiliary_files),
            "text_runs_translated": total_runs,
            "images_found": images_found,
            "images_translated": images_translated,
        }
    finally:
        shutil.rmtree(work_dir, ignore_errors=True)
