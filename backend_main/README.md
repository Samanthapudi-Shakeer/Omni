# Aider Console — Backend (FastAPI)

## 1. Install Python deps
```bash
cd backend
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
```

`aider-chat` and `pylint` come from pip. The other three linters are native
tools you install separately:

| Tool      | Install                                                                 |
|-----------|--------------------------------------------------------------------------|
| OCLint    | `brew install oclint` (macOS) or download from https://oclint.org       |
| HTMLHint  | `npm install -g htmlhint`                                                |
| PMD       | Download from https://pmd.github.io and add `pmd/bin` to your `PATH`     |

If a binary isn't on PATH you can point at it explicitly via env vars:
`AC_OCLINT_BIN`, `AC_HTMLHINT_BIN`, `AC_PMD_BIN`, `AC_PYLINT_BIN`.

## 2. Point at your local Ollama
By default the backend talks to `http://localhost:11434` and uses model
`qwen2.5-coder:32b` (matching the model selected in the console screenshot).
Override with `OLLAMA_BASE_URL` / `OLLAMA_MODEL` if needed. `aider` itself
is invoked with `--model ollama/<OLLAMA_MODEL>` (see `AIDER_MODEL`).

Static analysis automatically uses SonarQube when `SONAR_URL` and either
`SONAR_TOKEN` or `SONAR_USERNAME`/`SONAR_PASSWORD` are configured. Set
`SONAR_SCANNER` when `sonar-scanner` is not on `PATH`. Without those settings
the existing per-file linters are used as a local fallback.

SonarQube credentials have no source-controlled defaults. Configure a
user-generated token (preferred) before starting the backend:

```bash
export SONAR_TOKEN='your-sonarqube-user-token'
```

Username/password authentication is also supported when required:

```bash
export SONAR_USERNAME='your-sonarqube-username'
export SONAR_PASSWORD='your-sonarqube-password'
```

If credentials are missing, SonarQube analysis returns a configuration error
instead of attempting an unauthenticated scan. Rotate any credentials that
were previously stored in local configuration or source history.

The Static Analysis upload accepts a project ZIP. SonarQube's standard API
does not accept ZIP files directly: the backend creates a ZIP for the selected
files, extracts it into a temporary staging directory, and invokes the
SonarScanner CLI there. Install the scanner on the backend host and either put
`sonar-scanner` on `PATH` or set `SONAR_SCANNER` to its absolute executable
path. `SONAR_URL`, `SONAR_TOKEN` (preferred), or the username/password pair
must also be set.

## 3. Run
```bash
uvicorn app.main:app --reload --port 8000
```

The frontend development server proxies `/api` to port `8080`. Set
`VITE_API_TARGET=http://host:port` before starting Vite when the backend uses
a different address.

## How "isolated" sessions work

**How to Fix** (`POST /api/analysis/how-to-fix`) is preview-only and does
**not** use aider. It's one direct, stateless call to Ollama's
`/api/generate` carrying the issue AND the **entire file** as context (so
the model can reason about the full picture), asking for an explanation
plus a small, line-ranged corrected block - see `services/how_to_fix.py`.
Nothing is written to disk by this call; it only returns the explanation
and a diff for the UI to show. **Apply this fix** (`POST
/api/analysis/apply-fix`) is a separate, explicit action that writes
exactly the `start_line`/`end_line`/`fixed_code` the preview returned - no
second Ollama call, so what gets applied is guaranteed to match what was
shown.

**Fix All** (`POST /api/analysis/fix-all`) is unchanged from before: it
still auto-applies every given issue using `services/quick_fix.py`, one
stateless Ollama call per issue carrying only a small window of
surrounding code (`AC_FIX_CONTEXT_LINES`, default 8 lines each side of the
reported line) rather than the whole file - full-file context per issue
wouldn't scale well across a large batch. No chat history or `context`
array is passed or reused in either path, and each fix already runs
independently, so fixes never share model context.

Either way, the fix is written **directly into the original file** (in
place - no `fix_<name>` copy). The first time a file is touched, its
current content is committed as a baseline in a dedicated version-history
repo under `<workspace>/.ac_history/` (separate from any real project git
repo - see `services/versioning.py`); every fix after that is its own
commit. That's what backs:
- `GET /api/analysis/history/{ws}/{file}` - full commit list for a file
- `GET /api/analysis/diff/{ws}/{file}` - diff for one commit, between any
  two versions, or (default) from the very first tracked version to now

**Fix All** applies every given issue, grouped by file, **from the last
line to the first** within each file - this way, once an earlier
(lower-line-number) fix runs, the line numbers
it still expects for issues above it in the file haven't shifted from fixes
already applied below. Each issue is still its own isolated Ollama call and
its own commit.

**Modularization** (`POST /api/modularize/start-session` + `WS
/api/pty/ws/{session_id}`) and **Test Case Generation** (`POST
/api/testgen/start` + the same shared WebSocket endpoint) both use a
genuinely **interactive** aider session attached to a real pseudo-terminal
(`pty.fork()` in `services/pty_session.py`) - not the old non-interactive
`aider --yes-always`. Aider can ask real Y/N questions and the developer
answers them live in the terminal UI, exactly like running aider by hand.
Output streams to the browser over a WebSocket in real time; keystrokes go
back the same way. Each run creates a throwaway git repo under
`workspaces/<name>/.ac_sessions/<kind>_<id>/`, completely separate from the
version-history repo used by Fix/Fix All. When the session ends, any
new/changed files are copied from the isolated session directory back into
the real workspace.

A short, hardcoded list of known low-value prompts is auto-answered so a
background PTY session never silently stalls on something unrelated to the
actual task - currently just aider's "Open documentation url for more
info?" prompt (answered "No"), matched against recent output and answered
by writing directly to the PTY, visible in the terminal like real input.
Everything else - "Add file to chat?", "Proceed?", any genuine
confirmation - is left entirely to the user. This replaces the old
non-interactive path's automatic token-limit `/clear`-and-retry behavior;
since the session is now interactive, if the model's context fills up you
can just type `/clear` yourself the same way you would running aider
directly.

**Translate & Describe an Image** (`POST /api/translate/image`) is the
simplest of the translate endpoints: a direct multipart file upload (no
workspace attach step needed), one vision-model call asking for both a
description of the image and, if it contains visible text, that text plus
its translation. It's synchronous like Ask AI - no job/session involved.

**Translate a document** (`POST /api/translate/pptx` / `/docx` / `/xlsx`)
does NOT use aider or an isolated session directory the way the features
above do - a .pptx/.docx/.xlsx is just a zip of XML parts (OOXML), so the
approach is: unzip into a scratch directory, find every occurrence of the
tag that holds visible text for that format with a regex (never a full
XML parse-and-reserialize, so every other tag/attribute/relationship is
left byte-for-byte untouched), translate each one (identical strings are
translated once and cached across the whole document), write the result
back, then re-zip. See `services/office_translate_common.py` for the
shared mechanics and `pptx_translate.py` / `docx_translate.py` /
`xlsx_translate.py` for which files/tags each format uses:

| Format | Body text tag | Also translated |
|---|---|---|
| .pptx | `<a:t>` in each slide | speaker notes |
| .docx | `<w:t>` in `document.xml` | headers, footers, footnotes/endnotes, comments |
| .xlsx | `<t>` in `sharedStrings.xml` + inline `<t>` in worksheets | legacy + threaded comments/notes, chart `<a:t>` text |

For .xlsx, formulas (`<f>`), numeric values, and sheet names are
deliberately never touched - renaming a sheet could break formulas that
reference it by name.

**Translation accuracy across split runs (pptx/docx).** A single sentence
is often split across multiple XML runs purely for formatting reasons -
e.g. one bolded word mid-sentence means three `<a:t>`/`<w:t>` runs instead
of one. Translating each run in isolation loses grammatical context and
can produce broken or nonsensical output for the sentence as a whole. For
.pptx and .docx, translation instead happens **per paragraph**
(`services/office_translate_common.translate_grouped_runs`): every
paragraph's runs are inspected, and if more than one carries real text,
they're concatenated and sent to Ollama as a single coherent unit, then
the full translation is written into the first non-empty run while the
rest are cleared. Paragraphs with 0 or 1 text-bearing run (the common
case) are unaffected - handled exactly like a single tag substitution,
with that run's formatting fully preserved. The trade-off for multi-run
paragraphs is deliberate and standard for this problem: paragraph-level
formatting (font, alignment, indentation, list level - none of it is ever
touched) survives intact, and the *first* run's character formatting now
applies to the whole translated sentence, but formatting that varied
*within* the original sentence can't be mapped onto the re-ordered/
re-sized translated text in the general case (word count and order change
across languages), so it collapses to the first run's style rather than
being scattered incoherently across mismatched fragments. This was
verified directly: a real `.pptx` built with a paragraph split into three
runs (plain / bold / plain) had the model receive the full sentence
`"The quick brown fox jumps over the lazy dog."` as one prompt (confirmed
by inspecting exactly what was sent), and the resulting file - reopened
with python-pptx - retained all three runs with the complete translation
in the first and the other two correctly emptied, not duplicated.

**Reducing text-overflow overlap (pptx / xlsx charts).** Translated text
is very often longer than the original (many language pairs run 15-30%
longer), which risks overflowing a fixed-size text box and visually
overlapping neighboring shapes on a slide. After translating each slide
(and xlsx chart), `services/office_translate_common.ensure_shrink_to_fit`
nudges every text body toward PowerPoint's own "shrink text on overflow"
behavior: explicit `<a:noAutofit/>` becomes `<a:normAutofit/>`, a stale
cached font-scale percentage (computed for the *original* text length) is
reset so PowerPoint recomputes it fresh, and a bodyPr with no autofit
setting at all gets one added. Shapes the original author explicitly set
to auto-*grow* (`<a:spAutoFit/>`) are left alone, since that's a
deliberate authoring choice, not a default to override. This still can't
guarantee zero overlap in every case (extreme length differences or
already-tight layouts can still clip), but it removes the single biggest
cause of translated slides visually breaking.

If a vision model is selected, every image in the format's media folder
(`ppt/media/`, `word/media/`, `xl/media/`) is sent to that model asking
whether it contains visible text; if so, the translation is overlaid as a
semi-transparent caption band on a copy of the image (same filename, so
every relationship still resolves). **Known limitation:** without OCR
bounding boxes, this is a caption overlay, not in-place pixel-for-pixel
replacement of the original text.

## Background jobs & progress

**Fix All** and **document translation** (pptx/docx/xlsx) run as
background jobs: their POST endpoints return a `job_id` immediately; poll
`GET /api/jobs/{job_id}` for `status` (`running`/`done`/`error`), an
ordered `progress` log, and the final `result`. The frontend's top-right
tray polls this automatically.

**How to Fix** and plain-text/image translate are single, synchronous
Ollama calls - no job needed.

**Modularization** and **Test Case Generation** are neither - they're live
terminal sessions over a shared WebSocket (`/api/pty/ws/{session_id}`), not
a progress log.

## API summary
- `GET  /api/workspace/{ws}/files` — list files
- `POST /api/workspace/{ws}/upload` — multipart file upload
- `POST /api/analysis/run` — `{workspace, files[]}` → issues + AI txt report
- `GET  /api/analysis/report/{ws}/{report_file}` — download the txt report
- `POST /api/analysis/ask` — `{workspace, issue}` → AI explanation
- `POST /api/analysis/how-to-fix` — `{workspace, issue, model?}` → explanation + diff (preview only, writes nothing)
- `POST /api/analysis/apply-fix` — `{workspace, issue, start_line, end_line, fixed_code}` → writes exactly the previewed fix, no Ollama call
- `POST /api/analysis/fix-all` — `{workspace, issues[]}` → job_id (fixes every issue, in place)
- `GET  /api/analysis/history/{ws}/{file}` — commit list for a file's AI-fix history
- `GET  /api/analysis/diff/{ws}/{file}` — diff (optionally `?commit=` or `?against=`)
- `GET  /api/modularize/default-prompt` — editable default prompt text
- `POST /api/modularize/start-session` — `{workspace, file, prompt}` → session_id (interactive PTY, same as Test Case Generation)
- `GET  /api/jobs/{job_id}` — poll status/progress/result for any of the above jobs
- `GET  /api/testgen/default-prompt` — editable default test-generation prompt
- `POST /api/testgen/start` — `{workspace, files[], prompt}` → session_id
- `WS   /api/pty/ws/{session_id}` — shared live interactive terminal for both Modularization and Test Case Generation (output/input/resize + exit event with changed files)
- `GET  /api/translate/languages` — dropdown language list (source list includes "auto")
- `GET  /api/translate/models` — locally installed Ollama models (name + size)
- `GET  /api/translate/vision-models` — subset of installed models that look vision-capable by name (heuristic; UI always also offers "skip images")
- `POST /api/translate/image` — multipart upload (`file`, `model`, `target_lang`) → `{description, has_text, detected_text, translation, model}`, one synchronous vision-model call, no workspace/file attach needed
- `POST /api/translate` — `{text, source_lang, target_lang, model?}` → `{translation, detected_source_lang, detected_source_code, model}`
- `POST /api/translate/pptx` — `{workspace, file, source_lang, target_lang, model?, vision_model?}` → job_id
- `POST /api/translate/docx` — same shape → job_id
- `POST /api/translate/xlsx` — same shape → job_id
