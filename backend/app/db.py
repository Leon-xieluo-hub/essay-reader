"""SQLite persistence layer.

Tables are intentionally simple: documents + blocks + per-(block, lang,
provider) translations + glossary + notes + summaries. Cache keys include the
provider/model so the two channels can coexist and be reused per paragraph.
"""

from __future__ import annotations

import json
import sqlite3
import threading
from datetime import datetime, timezone
from typing import Any, Iterable, Optional

from app.config import DB_PATH
from app.schemas import Block, DocumentMeta, GlossaryTerm, Note, PageInfo, ParseReport

_lock = threading.RLock()
_conn: Optional[sqlite3.Connection] = None

SCHEMA = """
CREATE TABLE IF NOT EXISTS documents (
    id TEXT PRIMARY KEY, filename TEXT NOT NULL, title TEXT DEFAULT '',
    authors TEXT DEFAULT '[]', page_count INTEGER DEFAULT 0, file_size INTEGER DEFAULT 0,
    sha256 TEXT DEFAULT '', created_at TEXT DEFAULT '', status TEXT DEFAULT 'parsed',
    pages_json TEXT DEFAULT '[]', report_json TEXT DEFAULT '{}'
);
CREATE TABLE IF NOT EXISTS blocks (
    id TEXT PRIMARY KEY, doc_id TEXT NOT NULL, ord INTEGER NOT NULL, page INTEGER NOT NULL,
    type TEXT NOT NULL, text TEXT DEFAULT '', bbox TEXT DEFAULT '[]', col INTEGER DEFAULT 0,
    level INTEGER, size REAL DEFAULT 0, image_path TEXT, latex TEXT, caption TEXT,
    table_html TEXT, table_rows TEXT, table_rows_translated TEXT, flags TEXT DEFAULT '[]'
);
CREATE INDEX IF NOT EXISTS idx_blocks_doc ON blocks(doc_id, ord);
CREATE TABLE IF NOT EXISTS translations (
    id INTEGER PRIMARY KEY AUTOINCREMENT, block_id TEXT NOT NULL, doc_id TEXT NOT NULL,
    lang TEXT NOT NULL, provider TEXT NOT NULL, model TEXT NOT NULL, text TEXT NOT NULL,
    quality TEXT DEFAULT 'ok', attempts INTEGER DEFAULT 1, tokens_in INTEGER DEFAULT 0,
    tokens_out INTEGER DEFAULT 0, created_at TEXT DEFAULT '',
    UNIQUE(block_id, lang, provider, model)
);
CREATE INDEX IF NOT EXISTS idx_tr_doc ON translations(doc_id, lang);
CREATE TABLE IF NOT EXISTS glossary (
    id INTEGER PRIMARY KEY AUTOINCREMENT, doc_id TEXT NOT NULL, source TEXT NOT NULL,
    target TEXT NOT NULL, note TEXT DEFAULT '', locked INTEGER DEFAULT 0,
    UNIQUE(doc_id, source)
);
CREATE TABLE IF NOT EXISTS notes (
    id INTEGER PRIMARY KEY AUTOINCREMENT, doc_id TEXT NOT NULL, block_id TEXT NOT NULL,
    quote TEXT DEFAULT '', comment TEXT DEFAULT '', color TEXT DEFAULT 'yellow',
    created_at TEXT DEFAULT ''
);
CREATE TABLE IF NOT EXISTS summaries (
    doc_id TEXT NOT NULL, lang TEXT NOT NULL, provider TEXT NOT NULL, model TEXT NOT NULL,
    content TEXT NOT NULL, created_at TEXT DEFAULT '',
    PRIMARY KEY (doc_id, lang, provider, model)
);
CREATE TABLE IF NOT EXISTS usage (
    id INTEGER PRIMARY KEY AUTOINCREMENT, provider TEXT NOT NULL, model TEXT NOT NULL,
    tokens_in INTEGER DEFAULT 0, tokens_out INTEGER DEFAULT 0, seconds REAL DEFAULT 0,
    kind TEXT DEFAULT 'translate', created_at TEXT DEFAULT ''
);
CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY, value TEXT NOT NULL, updated_at TEXT DEFAULT ''
);
"""


def now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def connect() -> sqlite3.Connection:
    global _conn
    with _lock:
        if _conn is None:
            _conn = sqlite3.connect(DB_PATH, check_same_thread=False)
            _conn.row_factory = sqlite3.Row
            _conn.executescript(SCHEMA)
            _migrate(_conn)
            _conn.commit()
        return _conn


def _migrate(conn: sqlite3.Connection) -> None:
    """Additive migrations so an existing local database keeps working."""
    columns = {row["name"] for row in conn.execute("PRAGMA table_info(blocks)")}
    if "size" not in columns:
        conn.execute("ALTER TABLE blocks ADD COLUMN size REAL DEFAULT 0")
    if "table_rows_translated" not in columns:
        conn.execute("ALTER TABLE blocks ADD COLUMN table_rows_translated TEXT")


def _rows(sql: str, params: Iterable[Any] = ()) -> list:
    with _lock:
        return connect().execute(sql, tuple(params)).fetchall()


def _exec(sql: str, params: Iterable[Any] = ()) -> int:
    with _lock:
        conn = connect()
        cur = conn.execute(sql, tuple(params))
        conn.commit()
        return cur.lastrowid or cur.rowcount


def insert_document(*, doc_id: str, filename: str, sha256: str, file_size: int,
                    pages: list, report, title: str = "", authors=None) -> None:
    _exec(
        """INSERT OR REPLACE INTO documents
           (id, filename, title, authors, page_count, file_size, sha256,
            created_at, status, pages_json, report_json) VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
        (doc_id, filename, title, json.dumps(authors or [], ensure_ascii=False), len(pages),
         file_size, sha256, now_iso(), "parsed",
         json.dumps([p.model_dump() for p in pages], ensure_ascii=False),
         report.model_dump_json()),
    )


def update_document_report(doc_id: str, report) -> None:
    _exec("UPDATE documents SET report_json = ? WHERE id = ?", (report.model_dump_json(), doc_id))


def find_document_by_hash(sha256: str) -> Optional[DocumentMeta]:
    rows = _rows("SELECT * FROM documents WHERE sha256 = ? LIMIT 1", (sha256,))
    return _doc_meta(rows[0]) if rows else None


def get_document(doc_id: str) -> Optional[dict]:
    rows = _rows("SELECT * FROM documents WHERE id = ?", (doc_id,))
    if not rows:
        return None
    row = rows[0]
    data = _doc_meta(row).model_dump()
    data["pages"] = json.loads(row["pages_json"] or "[]")
    return data


def list_documents() -> list:
    return [_doc_meta(r) for r in _rows("SELECT * FROM documents ORDER BY created_at DESC")]


def delete_document(doc_id: str) -> None:
    with _lock:
        conn = connect()
        for table in ("blocks", "translations", "glossary", "notes", "summaries"):
            conn.execute(f"DELETE FROM {table} WHERE doc_id = ?", (doc_id,))
        conn.execute("DELETE FROM documents WHERE id = ?", (doc_id,))
        conn.commit()


def _doc_meta(row) -> DocumentMeta:
    report_raw = (row["report_json"] or "").strip()
    report = None
    if report_raw and report_raw != "{}":
        try:
            report = ParseReport(**json.loads(report_raw))
        except Exception:
            report = None
    return DocumentMeta(
        id=row["id"], filename=row["filename"], title=row["title"] or "",
        authors=json.loads(row["authors"] or "[]"), page_count=row["page_count"] or 0,
        file_size=row["file_size"] or 0, sha256=row["sha256"] or "",
        created_at=row["created_at"] or "", status=row["status"] or "parsed",
        parse_report=report,
    )


def insert_blocks(blocks: list) -> None:
    with _lock:
        conn = connect()
        conn.executemany(
            """INSERT OR REPLACE INTO blocks
               (id, doc_id, ord, page, type, text, bbox, col, level, size, image_path,
                latex, caption, table_html, table_rows, table_rows_translated, flags)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            [(b.id, b.doc_id, b.order, b.page, b.type, b.text,
              json.dumps(b.bbox.as_list()), b.column, b.level, b.size, b.image_path, b.latex,
              b.caption, b.table_html,
              json.dumps(b.table_rows, ensure_ascii=False) if b.table_rows else None,
              json.dumps(b.table_rows_translated, ensure_ascii=False) if b.table_rows_translated else None,
              json.dumps(b.flags, ensure_ascii=False)) for b in blocks],
        )
        conn.commit()


def get_blocks(doc_id: str) -> list:
    out = []
    for row in _rows("SELECT * FROM blocks WHERE doc_id = ? ORDER BY ord", (doc_id,)):
        values = json.loads(row["bbox"] or "[0,0,0,0]")
        from app.schemas import BBox
        out.append(Block(
            id=row["id"], doc_id=row["doc_id"], order=row["ord"], page=row["page"],
            type=row["type"], text=row["text"] or "",
            bbox=BBox(x0=values[0], y0=values[1], x1=values[2], y1=values[3]),
            column=row["col"] or 0, level=row["level"], size=row["size"] or 0.0,
            image_path=row["image_path"],
            latex=row["latex"], caption=row["caption"], table_html=row["table_html"],
            table_rows=json.loads(row["table_rows"]) if row["table_rows"] else None,
            table_rows_translated=(
                json.loads(row["table_rows_translated"]) if row["table_rows_translated"] else None
            ),
            flags=json.loads(row["flags"] or "[]"),
        ))
    return out


def upsert_translation(*, block_id: str, doc_id: str, lang: str, provider: str, model: str,
                       text: str, quality: str = "ok", attempts: int = 1,
                       tokens_in: int = 0, tokens_out: int = 0) -> None:
    _exec(
        """INSERT INTO translations
             (block_id, doc_id, lang, provider, model, text, quality, attempts,
              tokens_in, tokens_out, created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?)
           ON CONFLICT(block_id, lang, provider, model) DO UPDATE SET
             text=excluded.text, quality=excluded.quality, attempts=excluded.attempts,
             tokens_in=excluded.tokens_in, tokens_out=excluded.tokens_out,
             created_at=excluded.created_at""",
        (block_id, doc_id, lang, provider, model, text, quality, attempts,
         tokens_in, tokens_out, now_iso()),
    )


def get_translations(doc_id: str, lang: str) -> dict:
    out: dict = {}
    for row in _rows(
        "SELECT * FROM translations WHERE doc_id = ? AND lang = ? ORDER BY created_at DESC",
        (doc_id, lang),
    ):
        out.setdefault(row["block_id"], []).append(dict(row))
    return out


def delete_translations(doc_id: str, block_ids=None) -> None:
    if block_ids:
        marks = ",".join("?" * len(block_ids))
        _exec(f"DELETE FROM translations WHERE doc_id = ? AND block_id IN ({marks})",
              [doc_id, *block_ids])
    else:
        _exec("DELETE FROM translations WHERE doc_id = ?", (doc_id,))


def upsert_glossary(doc_id: str, source: str, target: str, note: str = "", locked: bool = False) -> None:
    _exec(
        """INSERT INTO glossary (doc_id, source, target, note, locked) VALUES (?,?,?,?,?)
           ON CONFLICT(doc_id, source) DO UPDATE SET
             target=excluded.target, note=excluded.note,
             locked=MAX(glossary.locked, excluded.locked)""",
        (doc_id, source, target, note, 1 if locked else 0),
    )


def get_glossary(doc_id: str) -> list:
    return [GlossaryTerm(id=r["id"], doc_id=r["doc_id"], source=r["source"],
                         target=r["target"], note=r["note"] or "", locked=bool(r["locked"]))
            for r in _rows("SELECT * FROM glossary WHERE doc_id = ? ORDER BY id", (doc_id,))]


def delete_glossary_term(doc_id: str, term_id: int) -> None:
    _exec("DELETE FROM glossary WHERE doc_id = ? AND id = ?", (doc_id, term_id))


def insert_note(*, doc_id: str, block_id: str, quote: str, comment: str, color: str) -> int:
    return _exec(
        """INSERT INTO notes (doc_id, block_id, quote, comment, color, created_at)
           VALUES (?,?,?,?,?,?)""",
        (doc_id, block_id, quote, comment, color, now_iso()),
    )


def get_notes(doc_id: str) -> list:
    return [Note(id=r["id"], doc_id=r["doc_id"], block_id=r["block_id"], quote=r["quote"] or "",
                 comment=r["comment"] or "", color=r["color"] or "yellow",
                 created_at=r["created_at"] or "")
            for r in _rows("SELECT * FROM notes WHERE doc_id = ? ORDER BY id", (doc_id,))]


def update_note(note_id: int, comment: str) -> None:
    _exec("UPDATE notes SET comment = ? WHERE id = ?", (comment, note_id))


def delete_note(note_id: int) -> None:
    _exec("DELETE FROM notes WHERE id = ?", (note_id,))


def save_summary(*, doc_id: str, lang: str, provider: str, model: str, content: str) -> None:
    _exec(
        """INSERT INTO summaries (doc_id, lang, provider, model, content, created_at)
           VALUES (?,?,?,?,?,?)
           ON CONFLICT(doc_id, lang, provider, model) DO UPDATE SET
             content=excluded.content, created_at=excluded.created_at""",
        (doc_id, lang, provider, model, content, now_iso()),
    )


def get_summary(doc_id: str, lang: str = "") -> Optional[dict]:
    if lang:
        rows = _rows("SELECT * FROM summaries WHERE doc_id = ? AND lang = ? ORDER BY created_at DESC LIMIT 1",
                     (doc_id, lang))
    else:
        rows = _rows("SELECT * FROM summaries WHERE doc_id = ? ORDER BY created_at DESC LIMIT 1", (doc_id,))
    return dict(rows[0]) if rows else None


def record_usage(*, provider: str, model: str, tokens_in: int, tokens_out: int,
                 seconds: float, kind: str) -> None:
    _exec(
        """INSERT INTO usage (provider, model, tokens_in, tokens_out, seconds, kind, created_at)
           VALUES (?,?,?,?,?,?,?)""",
        (provider, model, tokens_in, tokens_out, seconds, kind, now_iso()),
    )


def usage_totals() -> dict:
    row = _rows(
        """SELECT
             COALESCE(SUM(CASE WHEN provider='cloud' THEN tokens_in  ELSE 0 END),0) AS cloud_in,
             COALESCE(SUM(CASE WHEN provider='cloud' THEN tokens_out ELSE 0 END),0) AS cloud_out,
             COALESCE(SUM(CASE WHEN provider='local' THEN tokens_out ELSE 0 END),0) AS local_out,
             COALESCE(SUM(CASE WHEN provider='local' THEN seconds    ELSE 0 END),0) AS local_seconds
           FROM usage"""
    )[0]
    return {"cloud_tokens_in": row["cloud_in"], "cloud_tokens_out": row["cloud_out"],
            "local_blocks_translated": row["local_out"], "local_seconds": row["local_seconds"]}


def reset_usage() -> None:
    _exec("DELETE FROM usage")


# ------------------------------------------------------------------- settings

def save_settings(values: dict) -> None:
    """Persist user settings so they survive a restart.

    Without this the cloud API key configured in the UI only lived in memory and
    vanished the next time the app was started — the channel then reported
    "not configured" even though the user had already set it up.
    """
    with _lock:
        conn = connect()
        stamp = now_iso()
        for key, value in values.items():
            conn.execute(
                """INSERT INTO settings (key, value, updated_at) VALUES (?,?,?)
                   ON CONFLICT(key) DO UPDATE SET value=excluded.value,
                                                  updated_at=excluded.updated_at""",
                (str(key), json.dumps(value, ensure_ascii=False), stamp),
            )
        conn.commit()


def load_settings() -> dict:
    out: dict = {}
    for row in _rows("SELECT key, value FROM settings"):
        try:
            out[row["key"]] = json.loads(row["value"])
        except Exception:
            continue
    return out