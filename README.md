**English** | [简体中文](README.zh-CN.md)

# Essay Reader

A local-first reader for academic PDFs: upload a paper → accurate layout parsing → dual-channel translation (free offline local model, or a cloud model when accuracy matters) → structured summaries → Q&A with citations.

The interface is a low-distraction cream-and-pale-yellow reading theme. Papers, translations and notes stay on your machine: **apart from the one-time download of local model weights and optional cloud calls, the app makes no outbound network requests at runtime and collects no usage data.**

> The application UI is in Simplified Chinese; this document is the English overview.

## Screenshots

**Reading view** — the paper on the left, translation inline underneath; the top bar carries the active channel, the usage counter and the running cost. Both a light (cream) and a dark theme are available.

![Reading view with inline translation](images/reading-view.png)

**Original page mode** — the real page rendered with pdf.js beside the outline; selecting a paragraph highlights its region, which is the most reliable way to verify parsing and figure placement.

![Original page mode](images/original-page.png)

| Library | Settings |
| --- | --- |
| ![Library with per-paper parse quality](images/library.png) | ![Settings: channels, local model, OCR, cloud API](images/settings.png) |

---

## Quick start

### Clone and install

```powershell
git clone https://github.com/Leon-xieluo-hub/essay-reader.git
cd essay-reader
powershell -ExecutionPolicy Bypass -File .\scripts\setup.ps1   # install deps + build the UI
```

### First-time install (already cloned)

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\setup.ps1
```

### Launch (every time after that)

- **Double-click `启动文献阅读器.cmd` in the project root** (easiest)
- Or from a terminal: `powershell -ExecutionPolicy Bypass -File .\start.ps1`

The launcher builds the UI when it is missing, **stops a stale instance holding the port**, loads `.env`, waits for the server to come up, opens the browser and prints the address in its window. **Closing that window stops the server.**

Open <http://127.0.0.1:8787> and drop a PDF onto the dashed box on the left.

> There is no auto-start and no background service: run the launcher when you need the app. A local tool does not need a resident process.
>
> Troubleshooting: if the page does not open, first read the address printed in the launcher window. If the window flashes and closes, the port is usually occupied (the launcher clears it) or a dependency is missing — paste the error text from that window.
>
> For maintainers: `start.ps1` and `scripts\*.ps1` must be saved as **UTF-8 with BOM**. Without a BOM, Windows PowerShell 5.1 decodes them as ANSI, turns the Chinese comments into mojibake and fails to parse the script (we have hit this once).

Development mode (frontend hot reload): `start.ps1 -Dev`, plus `cd frontend; npm run dev` in a second terminal → <http://127.0.0.1:5173>.

### Manual install (without the helper scripts)

```powershell
# backend dependencies
python -m pip install --index-url https://pypi.org/simple fastapi "uvicorn[standard]" pymupdf python-multipart

# build the frontend
cd frontend; npm install; npm run build; cd ..

# run
$env:PYTHONPATH = "$PWD\backend"
python -m uvicorn app.main:app --host 127.0.0.1 --port 8787
```

> If pip reports `Could not find a version that satisfies the requirement ... (from versions: none)`, your configured mirror is unreachable; point it at the official index with `-i https://pypi.org/simple`.

---

## Two channels, two jobs

| Task | Recommended channel | Notes |
| --- | --- | --- |
| Whole-paper translation, everyday bulk reading | **Local model** | Zero tokens, zero cost, data never leaves the machine; review long or ambiguous sentences (paragraphs flagged as suspect are marked) |
| Close reading, summaries and follow-up questions on important papers | **Cloud model** | More accurate and faster, billed per token; the cost is estimated before you start and a per-paper budget cap is available |
| Reading only | **AI off** | Pure reading mode: parsing, reading, search, notes and figures all work with no network at all |

Both channels share one **glossary** and one **per-paragraph cache**, so switching never loses work: paragraphs already translated by the other channel are reused.
When the machine is offline, the cloud entry point is greyed out with the reason shown — the app **never silently degrades** you to a lower-quality result without saying so.

### Enable the local model (one-time, offline forever after)

1. Install [Ollama](https://ollama.com/download) (one-click installer on Windows).
2. Open the app → Settings → "Local model" → enter a model name (default `qwen3:8b`) → **Download / update this model**. Progress is shown inside the app (~4–5 GB; the only step that needs the internet).
3. Switch the channel menu in the top bar to "Local model".

Machine with no internet at all: run `ollama pull qwen3:8b` on a connected machine, then copy `%USERPROFILE%\.ollama\models` to the same path on the target machine.

**VRAM guidance**: with 8 GB of VRAM, prefer an 8B-class model at Q5/Q6. A smaller model at higher precision beats a bigger model quantised aggressively — aggressive quantisation hurts terminology and number fidelity more than the parameter count helps.

### Enable the cloud model

Settings → Cloud API: fill in Base URL, model name and API key (any OpenAI-compatible endpoint works: DeepSeek / OpenAI / your own proxy).
The key is stored only in the local backend; the UI only reports whether one is configured and never echoes the value.

> **Settings persist.** They are written to the local SQLite `settings` table and reloaded at startup, so the cloud key, model names and concurrency survive a restart. Saving with a blank key does **not** overwrite the stored one. `GET /api/settings/stored` lists which settings are persisted (never the key value).

---

## How the three hard problems are handled

### 1. PDFs are hard to parse

- **Two-column detection**: instead of guessing a whitespace gutter, we look for **repeated line starts in a second text block**, which covers both the classic two-column layout and the "narrow side rail + body" layout used by MDPI and Frontiers; full-width titles and tables only count line starts, so they do not disturb the decision. When the detected rail is narrow (width < 62% of the body column), its content is classified as `meta` — margin article info, citation metadata and reference line numbers all fall into that group.
- **Article info becomes its own region**: publisher labels such as `Citation:` / `Received:` / `Keywords:` / `Academic Editor:` are recognised as a distinct `meta` type and **kept out of the body flow**. The reading pane collects them into one "Article info" card above the text, and translation, summarisation and search never treat them as body text. When the metadata rail interleaves horizontally with the body and a fragment gets glued into a body sentence (e.g. `…cultivation research, and Yang, W.; Zhai, R. 3DPhenoMVS: A`), post-processing splits it back out.
- **Journal names no longer cut through the body**: publishers such as MDPI reprint "Agronomy 2022, 12, 1865" in the middle of the page, where positional rules cannot catch it. We use "same text repeated ≥3 times + font size not larger than body" instead and move it out of the body flow as a running head.
- **Borderless tables are reconstructed**: many journal tables only have a top and a bottom rule and no vertical lines, so PyMuPDF's table detection finds nothing at all (0 tables for the whole test paper). The fallback merges text fragments on the same baseline into rows, splits cells on column gaps ≥12 pt, and requires column positions to align across most rows; "formula / reference list" signatures veto false positives (otherwise equations and reference lists turn into tables). On the test paper the 17-row two-column table is reconstructed completely, and translation keeps the row/column correspondence (header → `性状/缩写`, abbreviations such as `PH`/`PW` untouched).
- **Tables are stripped first**: `page.find_tables()` marks table regions, and text lines inside them are removed from the body flow so cells are not read as prose and cannot invent a phantom "second column". The table itself is rebuilt as structured rows/columns plus HTML, scrollable in the UI and comparable against the original page. The same step rejects "fake tables": if the text in a candidate region runs full width (a reference list, say), it is not treated as one.
- **Display equations are cropped as images**: the text layer returns equations **scrambled** — sub/superscripts, braces and summation limits each become separate lines (`\x1a \x1b b∈B ∥a −b ∥ h(A, B) = max min`), and no text post-processing can restore them reliably. Equations are therefore located by region, anchored on the **equation number `(n)`**: fragments near that baseline are the equation body, each equation becomes its own image (they are never merged), and the crop spans the full horizontal extent of the line so the left edge is not cut off. Images are inlined at their position in the text, click to enlarge, and the original text stays available for search. Body lines inside the cropped region are preserved and heading lines are never swallowed. On the test paper all 4 equation images (including the MAPE summation) come out complete.
- **Reading order**: full-width blocks form paragraphs first, then everything is sorted by (column → y), so a left column is read to its end before the right one instead of bouncing line by line. **Non-body blocks (article info / running heads / journal names) are hoisted ahead of the body**, so metadata no longer interrupts the middle of a paragraph.
- **Figure and table cropping**: rendered from the bounding box at 200 DPI into PNG and bound to the nearest caption; click to enlarge. Very small images (logos, rules, stamps) are filtered out by area ratio.
- **Paragraph and heading repair**: hyphenated line breaks (`hyphen-\nation`) are joined; running heads, footers and page numbers become their own block types and are not translated; heading lines glued into body text are split back out at the line boundary; metadata lines embedded in the middle of a paragraph are extracted instead of misclassifying the whole paragraph.
- **Parsing self-check**: text coverage, garbage ratio, paragraph count, figure/table counts, layout verdict and elapsed time are reported honestly in the "Parse quality" panel together with a quality score. Parse results are cached by file SHA-256, so the same file is never parsed twice.

### 2. Translation goes wrong easily

- **Placeholder protection**: before translation, equations, citations `[12]`, DOIs, URLs, figure references `Fig. 3`, **dates** (`1 February 2020` / `2020-06-29`) and numbers are replaced with `<ph id="n"/>` and restored exactly afterwards; a lost placeholder is refilled from the source and reported. Dates must be protected as a whole: asked to translate `1 February 2020`, a model reliably writes "1 年 2020 月". Short digit+letter tokens such as `3D` / `2D` are protected as one unit (masking only the digit splits them into `<ph id="0"/>D`, and a model that reflows the tag leaves an orphan `3` in the Chinese sentence), while digits inside words such as `3DPhenoMVS` are left alone so proper nouns stay intact.
- **Only blocks with content are translated**: if nothing but protected fragments remains (numbered lists like `5. 6. 7. …`, bare URL lines, formula blocks), the block is skipped. Sending them anyway produced meaningless output such as "5。6。7。" and burned tokens.
- **Glossary**: terms are extracted automatically and enforced during translation; you can add, edit or remove terms in the UI and the change applies to the next translation immediately.
- **Context-aware chunking**: text is split into chunks by token budget, at paragraph boundaries, and each chunk carries the document title, the glossary and the preceding paragraphs to reduce pronoun and reference errors.
- **Quality gate with a retry loop**: every paragraph is checked for placeholder and citation counts, lost numbers, length ratio (omission or hallucinated expansion) and whether it was actually translated into the target language. A failing paragraph is retried once with the failure reason attached; if it still fails it is marked "needs review", flagged in yellow next to the text, and offered a one-click cloud retranslation. The length-ratio floor is calibrated for Chinese compression (technical Chinese runs at 25–40% of the English character count); a tighter bound flagged every correct translation.
- **Tables are translated as a grid**: a table never joins a prose chunk; the whole grid is sent as JSON and must come back with **exactly the same row and column counts** — a shifted row would silently attribute data to the wrong subject, so a shape mismatch fails immediately. Cells go through the same placeholder protection, so numbers and abbreviations stay as they are.
- **Validation cannot be disabled on the local channel**, because small models make noticeably more mistakes with numbers and citations.

### 3. Figures and tables are hard to present

- Images are inlined where they belong, click to open a lightbox, captions are translated with the body text;
- Tables keep their row/column structure (header separated from body, footnotes preserved), scroll horizontally, and offer a "view original" comparison;
- Equations that can be converted to LaTeX are rendered with KaTeX; the rest keep their original image plus a hint to switch to the original page;
- The "original page" mode renders the real page with pdf.js, and selecting a paragraph highlights its region on the page — the most reliable way to verify parsing and figure placement.

---

## Project layout

```
backend/
  app/
    config.py             environment variables and runtime-tunable settings
    schemas.py            document IR / API contract (mirrors frontend types.ts)
    db.py                 SQLite: documents/blocks/translations/glossary/notes/summaries/usage
    parsing/pdf_parser.py PDF → IR: layout, reading order, figure cropping, table rebuild, self-check
    providers/__init__.py dual-channel abstraction: Ollama (local) / OpenAI-compatible (cloud) / off
    services/protect.py   placeholder protection and quality validation
    services/prompts.py   prompt templates for translation/summary/glossary/Q&A (two sets of constraints)
    services/translate.py translation pipeline (chunk → protect → model → repair → validate → cache)
    services/summary.py   structured key points + grounded Q&A over BM25 retrieval
    main.py               FastAPI routes + task queue + local-inference lock + SPA hosting
  tests/
    smoke.py              unit tests: placeholder protection, chunking, JSON tolerance
    test_parser.py        parser regression (two-column + single-column + scanned + real paper)
    make_sample*.py       generate the synthetic test PDFs (no copyrighted content; generated at test time)
frontend/
  src/styles.css         design tokens (cream/pale yellow/dark warm grey, includes dark mode)
  src/store.ts           Zustand state and all business actions
  src/api/               typed API client
  src/components/        TopBar / Sidebar / ReadingPane / BlockView / PdfPane / Dock / SettingsPanel …
  src/views/             Library / DocumentView
scripts/setup.ps1        first-time dependency install and build (run the app via start.ps1)
.env.example             every configurable setting with comments
README.md / README.zh-CN.md   English / Chinese docs (GitHub shows this file)
images/                  README screenshots
```

The data directory `backend/data/` (papers, translations, figures, SQLite) is not committed; deleting it clears your library.

---

## API overview

| Method | Path | Purpose |
| --- | --- | --- |
| GET | `/api/health` `/api/environment` `/api/providers` | health, network and channel status |
| GET/POST | `/api/documents` | list / upload and parse (same file hash is reused) |
| GET | `/api/documents/{id}` `/blocks` `/file` `/export` | document, blocks, original PDF, Markdown export |
| DELETE | `/api/documents/{id}` | delete a paper with its translations, notes and figures |
| POST | `/api/translate` `/api/translate/estimate` | start a translation task / estimate tokens and cost |
| POST/GET | `/api/summary` `/api/summary/{id}` | generate / read the structured summary |
| POST | `/api/ask` | grounded Q&A (BM25 retrieval + cited block ids) |
| GET/POST/DELETE | `/api/notes` `/api/glossary` | notes and glossary |
| GET/PUT | `/api/settings` `/api/usage` | settings and usage counters (counted locally, never reported) |
| POST | `/api/models/pull` | download an Ollama model from inside the app (SSE progress) |
| GET | `/api/tasks/{id}` | task progress |

Interactive docs: `/docs` once the server is running.

---

## Offline capability matrix

| Feature | Offline availability |
| --- | --- |
| Upload, parsing, layout rebuild, figure cropping, table rebuild | ✅ fully offline |
| Scanned-page OCR (RapidOCR / ONNX, CPU) | ✅ fully offline (models ship with the dependency, nothing is downloaded) |
| Reading, zoom, outline, search, reading progress | ✅ fully offline |
| Paragraph alignment, highlighted notes, Markdown export | ✅ fully offline |
| Translation / summary / Q&A (local model) | ✅ needs the model weights downloaded once |
| Translation / summary / Q&A (cloud) | ❌ needs network; greyed out with the reason when unavailable |
| Downloading a local model for the first time | ❌ the only step that requires the internet (offline model import is supported) |

---

## Tests

```powershell
$env:PYTHONPATH = "$PWD\backend"
python backend\tests\smoke.py         # placeholder protection / chunking / JSON tolerance
python backend\tests\test_parser.py   # parser regression: synthetic samples + a real paper
```

`test_parser.py` covers four groups: a two-column paper with figures and a table, a single-column
paper, a scanned page going through OCR, and a **real 17-page MDPI paper**
(`backend/tests/samples/real_world_3dphenomvs.pdf`, used only for parsing tests). The first two and
the scanned page are generated by `make_sample*.py`, so the repository needs no extra binary fixtures.

Tests write only to temporary directories (`ESSAY_DATA_DIR` and the synthetic samples both point at
the system temp directory and are cleaned up on exit), so a test run leaves nothing behind in
`backend/data` (your library) or `backend/tests/samples`.

> The only binary fixture in the repository, `backend/tests/samples/real_world_3dphenomvs.pdf`, is an
> open-access paper from the MDPI journal *Agronomy* 2022, 12, 1865 (CC BY 4.0, by Yinghua Wang et al.;
> DOI on the first page). It is included unmodified as a real-layout regression case; copyright stays
> with the authors and it is redistributed under CC BY 4.0.

The real-paper group asserts bugs that actually happened (see `IMPROVEMENT_PROMPT.md`):

- page 5 has ≤12 blocks (it once shattered into 37, one per line) and a median paragraph length ≥60 characters;
- sentences spanning block boundaries stay intact (re-blocking loses no text; coverage ≥99% overall);
- the outline contains no `N of M` running heads (16 once leaked in), no `0.x` measurement values, no brand fragments (`agronomy` / `Winter` / `Heliyon`);
- the outline contains `1. Introduction` / `2. Materials and Methods` / `3. Results`;
- the front-matter rail (`Citation:` / `Received:` / `Keywords:`) becomes a distinct `meta` type instead of mixing into the body;
- repeated journal names are moved out of the body flow and citation-rail fragments no longer break body sentences;
- a borderless (rules-only) two-column table is rebuilt as 17 structured rows;
- scrambled display equations are cropped as images rather than pasted as garbage text;
- sections starting with a digit (`2.8. 3D Point Cloud…`) reach the outline;
- block ids are globally unique and every page has blocks (per-page ids once collapsed a 21-page paper into 45 blocks);
- **two paragraphs merged into one block**: a first-line indent starts a new paragraph even when the leading is uniform (early versions broke paragraphs on line spacing alone, so an indented first line was swallowed by the previous paragraph);
- **one paragraph split by a page break**: a page ending mid-sentence is rejoined with the start of the next page (the next line must be unindented, not a running head, and wide enough); the join produces no duplicated text, and no page ends mid-sentence any more.

Parser results measured on real papers (public papers, read-only copies, originals untouched):

| Paper | Pages | Layout | Blocks / pages | Figures | Tables | Outline entries | meta |
| --- | --- | --- | --- | --- | --- | --- | --- |
| MDPI tomato growth monitoring | 21 | single | 307 / 21 | 13 | 0 | 25 | 10 |
| Frontiers 3D data augmentation | 17 | double | 333 / 17 | 14 | 1 | 29 | 3 |
| Heliyon yield estimation | 21 | single | 332 / 21 | 11 | 0 | 24 | 2 |
| MDPI 3DPhenoMVS | 17 | single | 181 / 17 | 6 | 1 | 25 | 17 |

> Block counts move as the parsing rules improve; the "MDPI 3DPhenoMVS" row reflects the **current**
> version (181 blocks / 110 paragraphs, 17 pages, the borderless table rebuilt as 17 rows).

Frontend type check and build:

```powershell
cd frontend; npx tsc --noEmit; npm run build
```

---

## Known limitations

- OCR is recognition, not extraction: punctuation, hyphenation and individual characters can differ from the page (confidence is about 0.98 at 200 DPI); verify critical numbers against the original page. Pages that are rotated or skewed are not deskewed and will lose accuracy.
- Table reconstruction relies on PyMuPDF's detector; borderless two-column tables have a dedicated fallback (row grouping + column alignment), but more complex borderless structures (merged cells, nested headers) can still come out incomplete — compare against the original page.
- `pymupdf_layout` is not enabled; layout analysis is rule-based and may need a manual check on unusual three-column or magazine-style pages.
- Heading and outline cleanup is a **heuristic over rules and font sizes**: extreme layouts (a journal name at the same size as the title, printed adjacent to it) can still add or drop an outline entry; check the original page in the "Parse quality" panel. OCR pages carry no font-size information, so those criteria degrade to pure text rules on scans.
- The **icon-style journal masthead** relies on span colours (white text on a colour band is detected; dark-green journal names fall back to size and rule heuristics). PDFs without colour information degrade the same way.
- **Equations are images, not LaTeX**: this keeps them pixel-accurate and fully offline, but equation content is not translated and is not matched by full-text search (the raw text is still indexed for retrieval). Real LaTeX would require a formula-recognition model such as pix2tex, adding dependencies and latency.
- A local 8B model is weaker than a large cloud model at Chinese phrasing and long, complex sentences — a genuine capability gap. Terminological consistency and number fidelity are protected by the glossary, placeholders and the quality gate.
- The first local translation loads the model into VRAM (about 10–30 seconds) before paragraphs start flowing quickly.
- Cost estimates are a **calibrated approximation** (input assumes 700 tokens of overhead per chunk, output is the token estimate × 1.3). Measured on a 17-page paper: estimated 27.3k input / 17.6k output, actual 39.1k input / 17.5k output, about ¥0.08 at `deepseek-chat` pricing.
