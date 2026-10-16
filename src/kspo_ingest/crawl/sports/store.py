"""SQLite persistence mirroring the spec DB model (§12).

Kept storage-agnostic and dependency-free so the crawler runs standalone for
verification. Column names/semantics map 1:1 to the PostgreSQL schema in the
spec; swapping to Postgres is a driver change, not a redesign.
"""
from __future__ import annotations

import json
import sqlite3
import time
from contextlib import contextmanager

SCHEMA = """
CREATE TABLE IF NOT EXISTS crawl_source (
  id INTEGER PRIMARY KEY,
  host TEXT NOT NULL,
  source_type TEXT NOT NULL,
  variant TEXT, board_seq INTEGER, menu_seq INTEGER, page_seq INTEGER,
  book_gbn TEXT, extra_params TEXT, list_url_tmpl TEXT,
  priority INTEGER DEFAULT 2, enabled INTEGER DEFAULT 1,
  last_crawled_at REAL,
  UNIQUE(host, source_type, variant, board_seq, page_seq, book_gbn)
);
CREATE TABLE IF NOT EXISTS document (
  id INTEGER PRIMARY KEY,
  source_host TEXT NOT NULL,
  unit_type TEXT NOT NULL,
  natural_id TEXT NOT NULL,
  canonical_url TEXT NOT NULL,
  fetch_url TEXT,
  source_id INTEGER,
  title TEXT, body_text TEXT, posted_at TEXT,
  content_hash TEXT, meta TEXT,
  status TEXT DEFAULT 'active',
  first_seen_at REAL, last_seen_at REAL, last_changed_at REAL,
  UNIQUE(source_host, unit_type, natural_id)
);
CREATE TABLE IF NOT EXISTS attachment (
  id INTEGER PRIMARY KEY,
  document_id INTEGER NOT NULL,
  kind TEXT, download_url TEXT, display_name TEXT, stored_name TEXT,
  mime TEXT, bytes INTEGER, sha256 TEXT, fetched INTEGER DEFAULT 0,
  UNIQUE(document_id, stored_name)
);
CREATE TABLE IF NOT EXISTS crawl_run (
  id INTEGER PRIMARY KEY,
  started_at REAL, ended_at REAL, mode TEXT, status TEXT, stats TEXT
);
CREATE TABLE IF NOT EXISTS crawl_frontier (
  id INTEGER PRIMARY KEY,
  run_id INTEGER, item_type TEXT, payload TEXT, priority INTEGER,
  status TEXT DEFAULT 'pending', attempts INTEGER DEFAULT 0,
  last_error TEXT, updated_at REAL
);
CREATE TABLE IF NOT EXISTS crawl_checkpoint (
  run_id INTEGER, source_id INTEGER, last_page INTEGER,
  last_seen_natural_id TEXT, phase TEXT, updated_at REAL,
  PRIMARY KEY(run_id, source_id)
);
CREATE INDEX IF NOT EXISTS ix_front_status ON crawl_frontier(run_id, status, priority);
"""


class Store:
    def __init__(self, path: str = "sports_crawl.db"):
        self.db = sqlite3.connect(path)
        self.db.row_factory = sqlite3.Row
        self.db.executescript(SCHEMA)
        self.db.commit()

    def close(self):
        self.db.close()

    @contextmanager
    def tx(self):
        try:
            yield self.db
            self.db.commit()
        except Exception:
            self.db.rollback()
            raise

    # --- sources ---
    def upsert_source(self, **k) -> int:
        # NOTE: `INSERT OR IGNORE` alone is NOT idempotent here — the UNIQUE key
        # includes nullable columns (page_seq/book_gbn/variant) and SQLite treats
        # NULL as distinct in UNIQUE, so every re-run inserted a full duplicate
        # copy (audit 2026-07-08: 34→68 sources). Fix: IFNULL-normalized
        # existence check first, insert only when truly absent.
        find = (
            "SELECT id FROM crawl_source WHERE host=? AND source_type=? AND "
            "IFNULL(variant,'')=IFNULL(?,'') AND IFNULL(board_seq,-1)=IFNULL(?,-1) AND "
            "IFNULL(page_seq,-1)=IFNULL(?,-1) AND IFNULL(book_gbn,'')=IFNULL(?,'')"
        )
        key = (k["host"], k["source_type"], k.get("variant"), k.get("board_seq"),
               k.get("page_seq"), k.get("book_gbn"))
        cols = ("host", "source_type", "variant", "board_seq", "menu_seq",
                "page_seq", "book_gbn", "extra_params", "list_url_tmpl", "priority")
        vals = [k.get(c) for c in cols]
        if isinstance(k.get("extra_params"), dict):
            vals[cols.index("extra_params")] = json.dumps(k["extra_params"], ensure_ascii=False)
        with self.tx() as db:
            row = db.execute(find, key).fetchone()
            if row is not None:
                return row["id"]
            cur = db.execute(
                f"INSERT INTO crawl_source ({','.join(cols)}) VALUES ({','.join('?'*len(cols))})",
                vals)
            return cur.lastrowid

    def list_sources(self, enabled_only=True):
        q = "SELECT * FROM crawl_source"
        if enabled_only:
            q += " WHERE enabled=1"
        q += " ORDER BY priority, id"
        return self.db.execute(q).fetchall()

    def mark_source_crawled(self, source_id: int):
        """Record that a source finished a crawl pass (drives coverage/freshness)."""
        with self.tx() as db:
            db.execute("UPDATE crawl_source SET last_crawled_at=? WHERE id=?",
                       (time.time(), source_id))

    # --- runs ---
    def start_run(self, mode: str) -> int:
        # Recover ghost runs: any run still 'running' when a new one starts was
        # killed without a terminal status (audit 2026-07-08: run left 'running'
        # forever after SIGTERM). Mark them 'interrupted' so operators don't see
        # a perpetually-running job.
        with self.tx() as db:
            db.execute(
                "UPDATE crawl_run SET status='interrupted', ended_at=? "
                "WHERE status='running'", (time.time(),))
            cur = db.execute(
                "INSERT INTO crawl_run (started_at, mode, status, stats) VALUES (?,?,?,?)",
                (time.time(), mode, "running", "{}"))
            return cur.lastrowid

    def finish_run(self, run_id: int, status: str, stats: dict):
        with self.tx() as db:
            db.execute("UPDATE crawl_run SET ended_at=?, status=?, stats=? WHERE id=?",
                       (time.time(), status, json.dumps(stats, ensure_ascii=False), run_id))

    # --- documents ---
    def get_document(self, host, unit_type, natural_id):
        return self.db.execute(
            "SELECT * FROM document WHERE source_host=? AND unit_type=? AND natural_id=?",
            (host, unit_type, natural_id)).fetchone()

    def upsert_document(self, *, host, unit_type, natural_id, canonical_url,
                        fetch_url, source_id, title, body_text, posted_at,
                        content_hash, meta) -> tuple[int, str]:
        """Returns (document_id, change) where change in {new,changed,unchanged}."""
        now = time.time()
        existing = self.get_document(host, unit_type, natural_id)
        with self.tx() as db:
            if existing is None:
                cur = db.execute(
                    "INSERT INTO document (source_host,unit_type,natural_id,canonical_url,"
                    "fetch_url,source_id,title,body_text,posted_at,content_hash,meta,"
                    "status,first_seen_at,last_seen_at,last_changed_at) "
                    "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (host, unit_type, natural_id, canonical_url, fetch_url, source_id,
                     title, body_text, posted_at, content_hash,
                     json.dumps(meta, ensure_ascii=False), "active", now, now, now))
                return cur.lastrowid, "new"
            change = "unchanged" if existing["content_hash"] == content_hash else "changed"
            status = "active" if change == "unchanged" else "changed"
            db.execute(
                "UPDATE document SET canonical_url=?,fetch_url=?,title=?,body_text=?,"
                "posted_at=?,content_hash=?,meta=?,status=?,last_seen_at=?,"
                "last_changed_at=CASE WHEN content_hash!=? THEN ? ELSE last_changed_at END "
                "WHERE id=?",
                (canonical_url, fetch_url, title, body_text, posted_at, content_hash,
                 json.dumps(meta, ensure_ascii=False), status, now,
                 content_hash, now, existing["id"]))
            return existing["id"], change

    def upsert_attachment(self, document_id, att):
        with self.tx() as db:
            db.execute(
                "INSERT OR IGNORE INTO attachment (document_id,kind,download_url,"
                "display_name,stored_name,mime) VALUES (?,?,?,?,?,?)",
                (document_id, att.kind, att.download_url, att.display_name,
                 att.stored_name, getattr(att, "mime", None)))

    def mark_seen(self, host, unit_type, natural_id):
        with self.tx() as db:
            db.execute("UPDATE document SET last_seen_at=? WHERE source_host=? AND "
                       "unit_type=? AND natural_id=?",
                       (time.time(), host, unit_type, natural_id))

    # --- checkpoints ---
    def save_checkpoint(self, run_id, source_id, last_page, last_seen_natural_id, phase):
        with self.tx() as db:
            db.execute(
                "INSERT INTO crawl_checkpoint (run_id,source_id,last_page,"
                "last_seen_natural_id,phase,updated_at) VALUES (?,?,?,?,?,?) "
                "ON CONFLICT(run_id,source_id) DO UPDATE SET last_page=excluded.last_page,"
                "last_seen_natural_id=excluded.last_seen_natural_id,phase=excluded.phase,"
                "updated_at=excluded.updated_at",
                (run_id, source_id, last_page, last_seen_natural_id, phase, time.time()))

    def get_checkpoint(self, run_id, source_id):
        return self.db.execute(
            "SELECT * FROM crawl_checkpoint WHERE run_id=? AND source_id=?",
            (run_id, source_id)).fetchone()

    # --- stats helpers ---
    def counts(self):
        c = self.db.execute
        return {
            "documents": c("SELECT COUNT(*) FROM document").fetchone()[0],
            "by_type": {r[0]: r[1] for r in c(
                "SELECT unit_type, COUNT(*) FROM document GROUP BY unit_type").fetchall()},
            "attachments": c("SELECT COUNT(*) FROM attachment").fetchone()[0],
            "auth_gated": c("SELECT COUNT(*) FROM document WHERE status='auth_gated'").fetchone()[0],
        }
