import sqlite3
from contextlib import contextmanager
from pathlib import Path
from .config import DB_PATH

SCHEMA = """
-- One row per pipeline execution
CREATE TABLE IF NOT EXISTS runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    started_at TEXT NOT NULL DEFAULT (datetime('now')),
    finished_at TEXT,
    stories_fetched INTEGER DEFAULT 0,
    stories_processed INTEGER DEFAULT 0
);

-- Raw HN stories, deduped on objectID
CREATE TABLE IF NOT EXISTS stories (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    object_id TEXT UNIQUE NOT NULL,
    title TEXT NOT NULL,
    url TEXT,
    author TEXT,
    points INTEGER,
    num_comments INTEGER,
    created_at TEXT,
    fetched_at TEXT NOT NULL DEFAULT (datetime('now')),

    -- Processing state
    status TEXT NOT NULL DEFAULT 'pending',
    prompt_version TEXT,

    -- LLM outputs (NULL until processed)
    summary TEXT,
    tags TEXT,
    audience TEXT,

    -- Link to which run processed this
    processed_in_run_id INTEGER REFERENCES runs(id)
);

-- Every LLM call, for cost tracking
CREATE TABLE IF NOT EXISTS llm_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id INTEGER NOT NULL REFERENCES runs(id),
    story_id INTEGER NOT NULL REFERENCES stories(id),
    model TEXT NOT NULL,
    prompt_version TEXT NOT NULL,
    input_tokens INTEGER NOT NULL,
    output_tokens INTEGER NOT NULL,
    cost_usd REAL NOT NULL,
    called_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_stories_status ON stories(status);
CREATE INDEX IF NOT EXISTS idx_stories_object_id ON stories(object_id);
CREATE INDEX IF NOT EXISTS idx_llm_runs_run_id ON llm_runs(run_id);
"""


def init_db() -> None:
    """Initialize the database with schema."""
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(DB_PATH) as conn:
        conn.executescript(SCHEMA)
        conn.commit()


@contextmanager
def get_connection():
    """Context manager for database connections."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
    finally:
        conn.close()


def create_run(conn: sqlite3.Connection) -> int:
    """Create a new pipeline run and return its ID."""
    cursor = conn.execute("INSERT INTO runs DEFAULT VALUES")
    conn.commit()
    return cursor.lastrowid


def finish_run(conn: sqlite3.Connection, run_id: int, stories_fetched: int, stories_processed: int) -> None:
    """Mark a run as finished."""
    conn.execute(
        """
        UPDATE runs
        SET finished_at = datetime('now'),
            stories_fetched = ?,
            stories_processed = ?
        WHERE id = ?
        """,
        (stories_fetched, stories_processed, run_id)
    )
    conn.commit()


def insert_story(conn: sqlite3.Connection, story: dict) -> bool:
    """
    Insert a story if it doesn't exist (dedupe on object_id).
    Returns True if inserted, False if already existed.
    """
    cursor = conn.execute(
        """
        INSERT OR IGNORE INTO stories (
            object_id, title, url, author, points, num_comments, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (
            story["objectID"],
            story["title"],
            story.get("url"),
            story.get("author"),
            story.get("points"),
            story.get("num_comments"),
            story.get("created_at"),
        )
    )
    conn.commit()
    return cursor.rowcount > 0


def get_stories_to_process(conn: sqlite3.Connection, prompt_version: str) -> list:
    """
    Get stories that need processing:
    - status is 'pending' or 'processing' (incomplete)
    - OR status is 'done' but with a different prompt version (re-process)
    """
    cursor = conn.execute(
        """
        SELECT * FROM stories
        WHERE status IN ('pending', 'processing')
           OR (status = 'done' AND prompt_version != ?)
        ORDER BY id
        """,
        (prompt_version,)
    )
    return cursor.fetchall()


if __name__ == "__main__":
    init_db()
    print(f"Database initialized at {DB_PATH}")
