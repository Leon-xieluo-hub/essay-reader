[简体中文](CHANGELOG.zh-CN.md) | **English**

# Changelog

Notable changes to Essay Reader, newest first. Versions are tagged in this
repository; the tag pages carry the same notes.

## 0.2.0 — 2026-09-21

Parser overhaul driven by nine real papers (8–21 pages, single- and two-column,
equation-heavy). The previous segmentation fix had only ever been verified on one
paper; measured across the set, it was not general.

### Fixed

- **Paragraphs cut by the layout are rejoined properly.** The merge signal is now
  typographic instead of stylistic: a last line that **reaches the column's right
  edge** was cut by the measure, so the paragraph continues. The previous
  first-line-indent test only fires on 1–13% of paragraphs in the block-style
  layouts MDPI, Frontiers and Elsevier use. On the reference paper, continuations
  merged rose from 4 to 16 and no page ends mid-sentence any more
  (0 splits / 0 tails, median paragraph 389 → 473 characters).
- **Text loss from tables.** A table region may only swallow text it reproduces:
  the characters of the removed lines are compared with the rebuilt cells, and
  below 80% coverage the original lines stay in the body flow (with a warning).
  Measured coverage: Comprehensive review 0.963 → **0.997**, *Using color and 3D
  geometry* 0.874 → **0.964**, Field-grown tomato 0.949 → **0.971**, fpls
  0.943 → **0.960**, Leaf Area 0.985 → **0.993**.
- **Text loss from equation crops.** Prose is excluded from the crop rectangle and
  is never moved into an image, while equations are still cropped, including
  pure-glyph displays (`z`, `ph`, `V =`) that only make sense as an image.
- **Table 1 lost its last row** (17 → **18 rows**). A row whose left cell wraps
  onto a second line puts its right-hand value *between* the two halves, so
  baseline grouping never saw a pair and the whole row was dropped out of the
  table. Wrapped rows are now absorbed explicitly.
- **Paragraphs that merely mention an equation** (`…with R² = 0.72…`) are no longer
  retyped as formulas — they keep their typeface, stay in the flow and are
  translated.
- **Reading position survives the mode switch.** Bilingual / Translation /
  Original change every block's height, so the browser clamped the scroll
  position and it looked like the app jumped back to the top; the paragraph at the
  top of the viewport is now pinned in place.
- The outline no longer sinks below the whole library: it renders directly under
  the open paper.
- Running heads are recognised by shape rather than by y position, so body text
  that starts high on a page is no longer mistaken for one.

### Added

- **Inline bold and italic.** Emphasis is extracted per span into `Block.emphasis`
  (character offsets into the block text) and rendered as `<strong>` / `<em>`,
  composed with search highlighting.
- **Interface language follows the system** (Chinese → Simplified Chinese,
  otherwise English) with a `中 / EN` switch in the top bar that remembers the
  choice. 313 strings across `frontend/src/i18n/`, no untranslated keys.
- `blocks.emphasis` column (additive migration, existing libraries keep working).

## 0.1.0 — 2026-09-19

First public release.

### Added

- PDF → document IR: column and metadata-rail detection, reading order, borderless
  table reconstruction, 200 DPI figure and equation cropping, outline cleanup,
  parse self-check (coverage, garbage ratio, paragraph/figure/table counts).
- Offline OCR fallback for scanned pages (RapidOCR/ONNX, CPU) folded into the same
  layout logic.
- Dual-channel translation (local Ollama / OpenAI-compatible cloud) sharing one
  glossary and one per-paragraph cache, with placeholder protection for citations,
  DOIs, URLs, dates and numbers, a per-paragraph quality gate and one-click cloud
  retranslation of flagged paragraphs.
- Structured summaries and grounded Q&A with cited blocks.
- FastAPI backend serving the built React/Vite SPA on one port; library,
  translations, notes and figures stay in local SQLite, no telemetry.
- Regression suites: parser (two-column, single-column, scanned, real 17-page
  paper) and service-level smoke tests, both hermetic (temporary directories only).
- Bilingual documentation (English README with `README.zh-CN.md`), screenshots,
  and a Windows launcher that builds, clears the port and opens the browser.
