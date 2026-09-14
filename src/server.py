"""
FastAPI server for browsing HN stories and viewing run costs.
"""

import json
from fastapi import FastAPI, Query
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pathlib import Path

from .db import init_db, get_connection

app = FastAPI(title="HN Story Summarizer")

# Static files
STATIC_DIR = Path(__file__).parent.parent / "static"


@app.on_event("startup")
def startup():
    init_db()


@app.get("/")
def index():
    """Serve the main UI."""
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/api/stories")
def get_stories(
    status: str = Query(None, description="Filter by status: pending, processing, done, failed"),
    tag: str = Query(None, description="Filter by tag (partial match)"),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
):
    """Get stories with optional filters."""
    with get_connection() as conn:
        query = "SELECT * FROM stories WHERE 1=1"
        params = []

        if status:
            query += " AND status = ?"
            params.append(status)

        if tag:
            # Search within JSON array stored as text
            query += " AND tags LIKE ?"
            params.append(f"%{tag}%")

        query += " ORDER BY id DESC LIMIT ? OFFSET ?"
        params.extend([limit, offset])

        cursor = conn.execute(query, params)
        rows = cursor.fetchall()

        stories = []
        for row in rows:
            story = dict(row)
            # Parse tags JSON if present
            if story.get("tags"):
                try:
                    story["tags"] = json.loads(story["tags"])
                except json.JSONDecodeError:
                    story["tags"] = []
            else:
                story["tags"] = []
            stories.append(story)

        # Get total count for pagination
        count_query = "SELECT COUNT(*) as total FROM stories WHERE 1=1"
        count_params = []
        if status:
            count_query += " AND status = ?"
            count_params.append(status)
        if tag:
            count_query += " AND tags LIKE ?"
            count_params.append(f"%{tag}%")

        total = conn.execute(count_query, count_params).fetchone()["total"]

        return {"stories": stories, "total": total, "limit": limit, "offset": offset}


@app.get("/api/stories/{story_id}")
def get_story(story_id: int):
    """Get a single story by ID."""
    with get_connection() as conn:
        cursor = conn.execute("SELECT * FROM stories WHERE id = ?", (story_id,))
        row = cursor.fetchone()
        if not row:
            return {"error": "Story not found"}, 404

        story = dict(row)
        if story.get("tags"):
            try:
                story["tags"] = json.loads(story["tags"])
            except json.JSONDecodeError:
                story["tags"] = []

        return story


@app.get("/api/runs")
def get_runs():
    """Get all pipeline runs with cost totals."""
    with get_connection() as conn:
        cursor = conn.execute(
            """
            SELECT
                r.id,
                r.started_at,
                r.finished_at,
                r.stories_fetched,
                r.stories_processed,
                COALESCE(SUM(l.cost_usd), 0) as total_cost,
                COUNT(l.id) as llm_calls
            FROM runs r
            LEFT JOIN llm_runs l ON r.id = l.run_id
            GROUP BY r.id
            ORDER BY r.id DESC
            """
        )
        rows = cursor.fetchall()
        return {"runs": [dict(row) for row in rows]}


@app.get("/api/runs/{run_id}")
def get_run(run_id: int):
    """Get detailed info for a specific run including all LLM calls."""
    with get_connection() as conn:
        # Get run info
        run_cursor = conn.execute("SELECT * FROM runs WHERE id = ?", (run_id,))
        run_row = run_cursor.fetchone()
        if not run_row:
            return {"error": "Run not found"}, 404

        run = dict(run_row)

        # Get LLM calls for this run
        llm_cursor = conn.execute(
            """
            SELECT l.*, s.title as story_title
            FROM llm_runs l
            JOIN stories s ON l.story_id = s.id
            WHERE l.run_id = ?
            ORDER BY l.id
            """,
            (run_id,),
        )
        llm_calls = [dict(row) for row in llm_cursor.fetchall()]

        # Calculate totals
        total_cost = sum(call["cost_usd"] for call in llm_calls)
        total_input_tokens = sum(call["input_tokens"] for call in llm_calls)
        total_output_tokens = sum(call["output_tokens"] for call in llm_calls)

        return {
            "run": run,
            "llm_calls": llm_calls,
            "totals": {
                "cost_usd": total_cost,
                "input_tokens": total_input_tokens,
                "output_tokens": total_output_tokens,
                "calls": len(llm_calls),
            },
        }


@app.get("/api/tags")
def get_tags():
    """Get all unique tags across processed stories."""
    with get_connection() as conn:
        cursor = conn.execute(
            "SELECT tags FROM stories WHERE tags IS NOT NULL AND status = 'done'"
        )
        rows = cursor.fetchall()

        tag_counts = {}
        for row in rows:
            try:
                tags = json.loads(row["tags"])
                for tag in tags:
                    tag_counts[tag] = tag_counts.get(tag, 0) + 1
            except json.JSONDecodeError:
                continue

        # Sort by count descending
        sorted_tags = sorted(tag_counts.items(), key=lambda x: -x[1])
        return {"tags": [{"name": t[0], "count": t[1]} for t in sorted_tags]}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)
