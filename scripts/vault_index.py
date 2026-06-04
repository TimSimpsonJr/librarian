"""vault_index.py — the OPTIONAL vault adapter (Task 1.4).

A SQLite full-text index over a vault directory of Markdown notes, ported from
``research-workflow/scripts/vault_index.py``. It backs Librarian's **vault mode**
only: ``scripts/vault_mode.py`` imports this module exclusively inside its
vault branch, and the portable-first default never touches it.

**This is the SOLE module in Librarian that imports ``sqlite3``.** Keeping the
import here (not at any shared/portable layer) is what makes the portable path
provably sqlite-free — see ``tests/test_vault_mode.py``
``test_portable_path_is_sqlite_import_clean``.

Public API (names kept STABLE so research-workflow / Magpie callers match):

* ``update_index(vault_path) -> dict`` — build/refresh the index of the vault's
  ``.md`` notes (title + tags + body + path), incrementally by mtime. Returns a
  stats dict ``{"added", "updated", "removed"}``. The adapter OWNS index freshness
  (prior-art §5 gap #6): callers ``update_index`` before ``search``; vault_mode
  does this internally so Librarian needs no Stage-0 refresh step.
* ``search(vault_path, query, limit=20) -> list[dict]`` — full-text search;
  returns hits ``{path, title, tags, excerpt, rank}`` (``path`` is vault-relative,
  forward-slashed).
* ``note_exists(vault_path, title) -> bool`` — exact-title membership check.
* ``list_notes(vault_path) -> list[dict]`` — all indexed ``{path, title, tags}``.
* ``build_index(vault_path) -> Path`` — full rebuild from scratch (drops the db).

**FTS5 vs. LIKE fallback.** On first connection the module probes whether this
Python's ``sqlite3`` was compiled with FTS5 (it tries to ``CREATE VIRTUAL TABLE
... USING fts5`` once and caches the result). When FTS5 is present, search uses an
``fts5`` virtual table with ``bm25`` ranking and prefix matching — identical
behavior to research-workflow. When FTS5 is ABSENT, the module transparently falls
back to a plain-SQLite ``LIKE`` substring scan over the same ``notes`` table,
exposing the SAME public API and hit shape (``rank`` becomes a simple
match-count-derived score). Callers and tests cannot tell which backend served a
query; only ranking quality differs.

The index db is created on demand under ``<vault>/.librarian/index.db`` (the
``.librarian`` dir is itself skipped during indexing, like any dotfolder).

Design note: this module does sqlite I/O (that is its whole job) but NO network,
clock, or randomness — index contents are a pure function of the vault's files
and their mtimes.
"""

from __future__ import annotations

import re
import sqlite3
from pathlib import Path

__all__ = [
    "update_index",
    "build_index",
    "search",
    "note_exists",
    "list_notes",
    "fts5_available",
]

CONFIG_DIR = ".librarian"
DB_NAME = "index.db"
EXCERPT_LENGTH = 500

# Cached FTS5 capability probe result (None until first probed).
_FTS5_AVAILABLE: bool | None = None


def _db_path(vault_root: Path) -> Path:
    return vault_root / CONFIG_DIR / DB_NAME


def fts5_available() -> bool:
    """Return True if this Python's sqlite3 supports FTS5 (probed once, cached).

    Tries to create an fts5 virtual table in an in-memory db. The result is cached
    process-wide because the answer is a property of the sqlite3 build, not of any
    particular vault, and the probe is the cheapest reliable signal (``pragma
    compile_options`` is not always populated on every platform build).
    """
    global _FTS5_AVAILABLE
    if _FTS5_AVAILABLE is None:
        try:
            probe = sqlite3.connect(":memory:")
            try:
                probe.execute("CREATE VIRTUAL TABLE _fts5_probe USING fts5(x)")
                _FTS5_AVAILABLE = True
            finally:
                probe.close()
        except sqlite3.Error:
            _FTS5_AVAILABLE = False
    return _FTS5_AVAILABLE


def _connect(vault_root: Path) -> sqlite3.Connection:
    db = _db_path(vault_root)
    db.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db))
    conn.row_factory = sqlite3.Row
    return conn


def _init_tables(conn: sqlite3.Connection) -> None:
    """Create the base ``notes`` table, plus the fts5 mirror when FTS5 is available.

    The ``notes`` table is the single source of truth in BOTH backends. With FTS5,
    an ``notes_fts`` external-content virtual table plus insert/delete/update
    triggers keep a searchable mirror (the research-workflow design). Without FTS5,
    only ``notes`` exists and ``search`` scans it with ``LIKE``.
    """
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS notes (
            path TEXT PRIMARY KEY,
            title TEXT NOT NULL DEFAULT '',
            tags TEXT NOT NULL DEFAULT '',
            excerpt TEXT NOT NULL DEFAULT '',
            body TEXT NOT NULL DEFAULT '',
            mtime REAL NOT NULL
        );
        """
    )
    if fts5_available():
        conn.executescript(
            """
            CREATE VIRTUAL TABLE IF NOT EXISTS notes_fts USING fts5(
                title, tags, body, content=notes, content_rowid=rowid
            );
            CREATE TRIGGER IF NOT EXISTS notes_ai AFTER INSERT ON notes BEGIN
                INSERT INTO notes_fts(rowid, title, tags, body)
                VALUES (new.rowid, new.title, new.tags, new.body);
            END;
            CREATE TRIGGER IF NOT EXISTS notes_ad AFTER DELETE ON notes BEGIN
                INSERT INTO notes_fts(notes_fts, rowid, title, tags, body)
                VALUES ('delete', old.rowid, old.title, old.tags, old.body);
            END;
            CREATE TRIGGER IF NOT EXISTS notes_au AFTER UPDATE ON notes BEGIN
                INSERT INTO notes_fts(notes_fts, rowid, title, tags, body)
                VALUES ('delete', old.rowid, old.title, old.tags, old.body);
                INSERT INTO notes_fts(rowid, title, tags, body)
                VALUES (new.rowid, new.title, new.tags, new.body);
            END;
            """
        )


def _normalize_newlines(text: str) -> str:
    """Normalize CRLF / lone-CR line endings to LF before frontmatter parsing.

    Notes authored on Windows (including by Librarian's own ``write_note.py``) use
    CRLF endings, so the ``^---\\n ... \\n---`` fences below would never match and
    the YAML frontmatter would (a) yield no ``title``/``tags`` and (b) leak into the
    indexed body. Folding ``\\r\\n`` and any stray lone ``\\r`` to ``\\n`` first makes
    the fence regexes line-ending-agnostic on every platform.
    """
    return text.replace("\r\n", "\n").replace("\r", "\n")


def _parse_frontmatter(text: str) -> tuple[str, str]:
    """Extract title and tags from YAML frontmatter. Returns (title, tags_csv).

    Deliberately a light regex parse (not a YAML load): the adapter must stay
    stdlib-only, and the index only needs the title/tags scalars for ranking and
    the exact-title check. Line endings are normalized to LF first so CRLF notes
    (Windows / ``write_note.py``) parse identically to LF ones.
    """
    text = _normalize_newlines(text)
    title = ""
    tags = ""
    fm_match = re.match(r"^---\n(.*?)\n---", text, re.DOTALL)
    if not fm_match:
        return title, tags
    fm = fm_match.group(1)
    for line in fm.splitlines():
        if line.startswith("title:"):
            title = line.split(":", 1)[1].strip().strip("'\"")
        if line.startswith("tags:"):
            rest = line.split(":", 1)[1].strip()
            if rest.startswith("["):
                tags = rest.strip("[]").replace(",", ", ")
            else:
                tags = rest
    return title, tags


def _body_text(text: str) -> str:
    """Strip frontmatter, return body text (line endings normalized to LF first)."""
    text = _normalize_newlines(text)
    stripped = re.sub(r"^---\n.*?\n---\n?", "", text, count=1, flags=re.DOTALL)
    return stripped.strip()


def _index_file(conn: sqlite3.Connection, vault_root: Path, rel_path: str, mtime: float) -> None:
    """Index or update a single file (read text, parse, upsert into ``notes``)."""
    full = vault_root / rel_path
    try:
        # newline="" disables universal-newline translation so the bytes on disk
        # (including CRLF written by Windows / write_note.py) reach the parser
        # faithfully; _parse_frontmatter / _body_text normalize to LF themselves.
        # (Path.read_text gained a `newline` kwarg only in 3.13, so open() here.)
        with full.open("r", encoding="utf-8", newline="") as fh:
            text = fh.read()
    except (OSError, UnicodeDecodeError):
        return
    title, tags = _parse_frontmatter(text)
    if not title:
        title = full.stem
    body = _body_text(text)
    excerpt = body[:EXCERPT_LENGTH]
    conn.execute(
        "INSERT OR REPLACE INTO notes (path, title, tags, excerpt, body, mtime) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (rel_path, title, tags, excerpt, body, mtime),
    )


def _should_skip(rel_path: str) -> bool:
    """Skip hidden dirs (incl. ``.librarian``) and non-.md files."""
    parts = Path(rel_path).parts
    for part in parts:
        if part.startswith("."):
            return True
    return not rel_path.endswith(".md")


def _rel(md: Path, vault_root: Path) -> str:
    """Vault-relative, forward-slashed path for a note file (stable across OSes)."""
    return str(md.relative_to(vault_root)).replace("\\", "/")


def build_index(vault_root: Path) -> Path:
    """Build the full index from scratch (drops any existing db). Returns the db path."""
    vault_root = Path(vault_root)
    db = _db_path(vault_root)
    if db.exists():
        db.unlink()
    conn = _connect(vault_root)
    try:
        _init_tables(conn)
        for md in vault_root.rglob("*.md"):
            rel = _rel(md, vault_root)
            if _should_skip(rel):
                continue
            _index_file(conn, vault_root, rel, md.stat().st_mtime)
        conn.commit()
    finally:
        conn.close()
    return db


def update_index(vault_root: Path) -> dict:
    """Incrementally refresh the index by mtime. Returns ``{added, updated, removed}``.

    The adapter owns freshness (prior-art §5 gap #6): every note newer than its
    indexed mtime is re-read, new notes are added, and notes deleted on disk are
    removed from the index. Cheap to call before each ``search``.
    """
    vault_root = Path(vault_root)
    conn = _connect(vault_root)
    try:
        _init_tables(conn)
        stats = {"added": 0, "updated": 0, "removed": 0}
        indexed: dict[str, float] = {}
        for row in conn.execute("SELECT path, mtime FROM notes"):
            indexed[row["path"]] = row["mtime"]
        on_disk: set[str] = set()
        for md in vault_root.rglob("*.md"):
            rel = _rel(md, vault_root)
            if _should_skip(rel):
                continue
            on_disk.add(rel)
            mtime = md.stat().st_mtime
            if rel not in indexed:
                _index_file(conn, vault_root, rel, mtime)
                stats["added"] += 1
            elif mtime > indexed[rel]:
                _index_file(conn, vault_root, rel, mtime)
                stats["updated"] += 1
        for path in indexed:
            if path not in on_disk:
                conn.execute("DELETE FROM notes WHERE path = ?", (path,))
                stats["removed"] += 1
        conn.commit()
    finally:
        conn.close()
    return stats


def _query_tokens(query: str) -> list[str]:
    """Extract bare word tokens from arbitrary (untrusted) query text.

    The index is searched with text that originates from note titles and link
    hints — i.e. FOIA-grade adversarial strings like ``Smith v. Jones (2020)``,
    ``Acme OR Globex``, or ``NEAR(camera budget)``. ``re.findall(r"\\w+")`` keeps
    ONLY alphanumeric/underscore runs (Unicode-aware), discarding every byte that
    FTS5 could interpret as syntax (quotes, parens, ``*``, ``^``, ``:``, ``-``,
    ``+`` …). The result feeds both the FTS5 and LIKE paths so the two backends
    tokenize identically.
    """
    return re.findall(r"\w+", query, re.UNICODE)


def _prepare_query(query: str) -> str:
    """Build a crash-proof FTS5 MATCH expression from untrusted text.

    Each word token is emitted as a *quoted FTS5 string* with a trailing prefix
    operator — ``"<tok>"*`` — with any internal double-quote doubled per FTS5's
    string-literal rules. Quoting neutralizes FTS5 keywords (``AND``/``OR``/
    ``NOT``/``NEAR``) and punctuation to LITERAL terms, so no input can form an
    operator, an unbalanced quote, or a bare column filter. The space-joined terms
    keep FTS5's implicit-AND semantics (matching research-workflow's behavior).

    Returns ``""`` when no usable word token remains; callers treat that as a
    no-op query (``[]``) rather than passing an empty/invalid MATCH to sqlite.

    Example: ``Acme OR Globex`` -> ``"Acme"* "OR"* "Globex"*`` (the ``OR`` is a
    literal term, not the FTS5 OR operator).
    """
    parts = []
    for tok in _query_tokens(query):
        escaped = tok.replace('"', '""')
        parts.append(f'"{escaped}"*')
    return " ".join(parts)


def _search_fts(conn: sqlite3.Connection, query: str, limit: int) -> list[dict]:
    prepared = _prepare_query(query)
    if not prepared:
        return []
    try:
        rows = conn.execute(
            """SELECT n.path, n.title, n.tags, n.excerpt,
                      bm25(notes_fts, 10.0, 5.0, 1.0) AS rank
               FROM notes_fts f
               JOIN notes n ON n.rowid = f.rowid
               WHERE notes_fts MATCH ?
               ORDER BY rank
               LIMIT ?""",
            (prepared, limit),
        ).fetchall()
    except sqlite3.OperationalError:
        # Safety net: no MATCH expression may crash the batch regardless of any
        # residual FTS5 edge. Fall back to the FTS5-free LIKE scan for this query.
        return _search_like(conn, query, limit)
    return [dict(r) for r in rows]


def _search_like(conn: sqlite3.Connection, query: str, limit: int) -> list[dict]:
    """FTS5-free fallback: substring (LIKE) scan over title+tags+body.

    Same public hit shape as the FTS path. ``rank`` is a NEGATED match score (more
    matched terms / a title hit => more negative) so the shared ``ORDER BY rank
    ASC`` orders best-first exactly like bm25's smaller-is-better convention.

    Tokenizes with the SAME word-extraction as the FTS path (``_query_tokens``)
    so the two backends agree on token boundaries and neither is fooled by
    punctuation in untrusted query text. Matching is plain Python substring
    containment, so adversarial input can never crash this path.
    """
    tokens = _query_tokens(query)
    if not tokens:
        return []
    rows = conn.execute(
        "SELECT path, title, tags, excerpt, body FROM notes"
    ).fetchall()
    scored: list[tuple[float, dict]] = []
    for r in rows:
        title_l = (r["title"] or "").lower()
        tags_l = (r["tags"] or "").lower()
        body_l = (r["body"] or "").lower()
        score = 0.0
        matched_any = False
        for tok in tokens:
            t = tok.lower()
            hit = False
            if t in title_l:
                score += 10.0  # weight a title hit like fts5's title column boost
                hit = True
            if t in tags_l:
                score += 5.0
                hit = True
            if t in body_l:
                score += 1.0
                hit = True
            matched_any = matched_any or hit
        if matched_any:
            hit = {
                "path": r["path"],
                "title": r["title"],
                "tags": r["tags"],
                "excerpt": r["excerpt"],
                "rank": -score,  # smaller (more negative) = better, matching bm25
            }
            scored.append((-score, hit))
    # Sort best-first (most negative rank), then by path for a stable tie-break.
    scored.sort(key=lambda s: (s[0], s[1]["path"]))
    return [hit for _, hit in scored[:limit]]


def search(vault_root: Path, query: str, limit: int = 20) -> list[dict]:
    """Full-text search. Returns ``[{path, title, tags, excerpt, rank}, ...]``.

    Uses FTS5 + bm25 when available, else a LIKE substring scan (same hit shape).
    An empty/whitespace query returns ``[]``. ``path`` values are vault-relative
    and forward-slashed.
    """
    vault_root = Path(vault_root)
    conn = _connect(vault_root)
    try:
        if fts5_available():
            return _search_fts(conn, query, limit)
        return _search_like(conn, query, limit)
    finally:
        conn.close()


def list_notes(vault_root: Path) -> list[dict]:
    """List all indexed notes as ``[{path, title, tags}, ...]`` ordered by path."""
    vault_root = Path(vault_root)
    conn = _connect(vault_root)
    try:
        rows = conn.execute(
            "SELECT path, title, tags FROM notes ORDER BY path"
        ).fetchall()
    finally:
        conn.close()
    return [dict(r) for r in rows]


def note_exists(vault_root: Path, title: str) -> bool:
    """True if a note with this title is indexed (case-INSENSITIVE).

    Case-insensitive on purpose: the vault-mode matcher
    (``vault_mode._best_title_match``) compares titles case-insensitively, so a
    future caller using ``note_exists`` as a dedup guard agrees with what
    ``resolve_notes`` would actually route as an update. ``COLLATE NOCASE`` applies
    in both backends (this queries the base ``notes`` table, which exists with or
    without FTS5).
    """
    vault_root = Path(vault_root)
    conn = _connect(vault_root)
    try:
        row = conn.execute(
            "SELECT 1 FROM notes WHERE title = ? COLLATE NOCASE LIMIT 1", (title,)
        ).fetchone()
    finally:
        conn.close()
    return row is not None
