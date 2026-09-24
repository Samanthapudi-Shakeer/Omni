"""
Translate a .xlsx file: every cell's text content, comments/notes, and text
embedded in charts, plus any visible text found in images under xl/media/.

Where cell text actually lives (this is why "cell to cell" isn't literally
"one Ollama call per cell"):
  - Most text cells reference the workbook-wide shared strings table
    (xl/sharedStrings.xml, <si><t>...</t></si> per unique string) rather
    than storing text inline - so we translate that table once. Any two
    cells with identical text share one entry there and get translated
    together, which is both far more efficient and keeps terminology
    consistent across the sheet.
  - Some cells store their text inline instead (<c t="inlineStr"><is><t>
    ...</t></is></c>), typically from certain export tools - each
    worksheet's XML is scanned for these too.
  - Legacy cell comments live in xl/comments<N>.xml as <t> runs; newer
    "threaded comments" (notes) live in xl/threadedComments/*.xml as a
    single <text>...</text> element instead - both are translated.
  - Chart titles/labels/axis text (xl/charts/chart<N>.xml) use the same
    drawingml <a:t> tag as PowerPoint text runs.

We still report how many actual cells contained string content (counted
directly from each worksheet's <c t="s"> / <c t="inlineStr"> cells), since
that's the number a user thinks of as "how many cells got translated" even
though the underlying work was done more efficiently via the shared table.

Formulas (<f>), numeric values (<v>) that aren't string indices, and sheet
names are never touched - translating a sheet name could break formulas
that reference it by name, so that's intentionally out of scope.

See office_translate_common.py for the shared regex-substitution /
image-overlay / rezip mechanics this builds on.
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

_T_RE = re.compile(r"(<t(?:\s[^>]*)?>)(.*?)(</t>)", re.DOTALL)
_TEXT_RE = re.compile(r"(<text(?:\s[^>]*)?>)(.*?)(</text>)", re.DOTALL)
_A_T_RE = re.compile(r"(<a:t(?:\s[^>]*)?>)(.*?)(</a:t>)", re.DOTALL)

_STRING_CELL_RE = re.compile(r'<c\s[^>]*\bt="(?:s|inlineStr|str)"[^>]*>')


def _count_string_cells(xml_text: str) -> int:
    return len(_STRING_CELL_RE.findall(xml_text))


def translate_xlsx(
    input_path: Path, output_path: Path,
    source_lang: str, target_lang: str, model: str,
    vision_model: Optional[str], progress_cb: ProgressCB = common.noop,
) -> dict:
    work_dir = output_path.parent / f".xlsx_work_{uuid.uuid4().hex[:8]}"
    work_dir.mkdir(parents=True, exist_ok=True)
    try:
        progress_cb(f"Unpacking {input_path.name}…")
        with zipfile.ZipFile(input_path, "r") as zf:
            zf.extractall(work_dir)

        xl_dir = work_dir / "xl"
        cache: Dict[str, str] = {}
        total_runs = 0
        cells_with_text = 0

        shared_strings = xl_dir / "sharedStrings.xml"
        if shared_strings.exists():
            progress_cb("Translating shared strings table…")
            xml_text = shared_strings.read_text(encoding="utf-8")
            new_xml, count = common.translate_tag_text(
                xml_text, _T_RE, source_lang, target_lang, model, cache, progress_cb,
            )
            shared_strings.write_text(new_xml, encoding="utf-8")
            total_runs += count

        sheets_dir = xl_dir / "worksheets"
        sheet_files = sorted(sheets_dir.glob("sheet*.xml")) if sheets_dir.exists() else []
        progress_cb(f"Found {len(sheet_files)} worksheet(s).")
        for idx, sf in enumerate(sheet_files, start=1):
            xml_text = sf.read_text(encoding="utf-8")
            cells_with_text += _count_string_cells(xml_text)
            # Only inline strings live directly in the worksheet XML - most
            # cells just reference the shared table above, which is already
            # translated.
            if "inlineStr" in xml_text:
                progress_cb(f"Translating inline cell text in sheet {idx}/{len(sheet_files)}…")
                new_xml, count = common.translate_tag_text(
                    xml_text, _T_RE, source_lang, target_lang, model, cache, progress_cb,
                )
                if count:
                    sf.write_text(new_xml, encoding="utf-8")
                    total_runs += count

        # Comment file placement isn't perfectly standardized across writers -
        # some put it at xl/comments1.xml, others (e.g. openpyxl) at
        # xl/comments/comment1.xml - so search recursively for anything
        # under xl/ whose filename starts with "comment" (this does NOT
        # match "threadedComment*.xml", which is handled separately below).
        comment_files = sorted(p for p in xl_dir.rglob("comment*.xml"))
        if comment_files:
            progress_cb(f"Translating {len(comment_files)} legacy comment part(s)…")
        for cf in comment_files:
            xml_text = cf.read_text(encoding="utf-8")
            new_xml, count = common.translate_tag_text(
                xml_text, _T_RE, source_lang, target_lang, model, cache, progress_cb,
            )
            cf.write_text(new_xml, encoding="utf-8")
            total_runs += count

        threaded_dir = xl_dir / "threadedComments"
        threaded_files = sorted(threaded_dir.glob("threadedComment*.xml")) if threaded_dir.exists() else []
        if threaded_files:
            progress_cb(f"Translating {len(threaded_files)} threaded comment/note part(s)…")
        for tf in threaded_files:
            xml_text = tf.read_text(encoding="utf-8")
            new_xml, count = common.translate_tag_text(
                xml_text, _TEXT_RE, source_lang, target_lang, model, cache, progress_cb,
            )
            tf.write_text(new_xml, encoding="utf-8")
            total_runs += count

        charts_dir = xl_dir / "charts"
        chart_files = sorted(charts_dir.glob("chart*.xml")) if charts_dir.exists() else []
        if chart_files:
            progress_cb(f"Translating text in {len(chart_files)} chart(s)…")
        for chf in chart_files:
            xml_text = chf.read_text(encoding="utf-8")
            new_xml, count = common.translate_tag_text(
                xml_text, _A_T_RE, source_lang, target_lang, model, cache, progress_cb,
            )
            chf.write_text(new_xml, encoding="utf-8")
            total_runs += count

        images_found, images_translated = common.translate_images_in_dir(
            xl_dir / "media", target_lang, vision_model, progress_cb,
        )

        progress_cb("Repackaging .xlsx…")
        common.rezip(work_dir, output_path)

        return {
            "worksheets": len(sheet_files),
            "cells_with_text": cells_with_text,
            "text_runs_translated": total_runs,
            "comment_parts": len(comment_files) + len(threaded_files),
            "charts_translated": len(chart_files),
            "images_found": images_found,
            "images_translated": images_translated,
        }
    finally:
        shutil.rmtree(work_dir, ignore_errors=True)
