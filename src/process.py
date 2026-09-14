"""
LLM processing script with status machine, transactional writes, and cost logging.

Crash-safe: each item's LLM call + DB write happens in a single transaction.
Idempotent: skips items already processed with the current prompt version.
"""

import json
import anthropic
from .config import ANTHROPIC_API_KEY, LLM_MODEL, PROMPT_VERSION, get_cost
from .db import init_db, get_connection, create_run, finish_run, get_stories_to_process

SYSTEM_PROMPT = """You analyze Hacker News stories and provide structured summaries.
Always respond with valid JSON in exactly this format:
{
  "summary": "A 2-sentence plain-English summary of what this story is about.",
  "tags": ["tag1", "tag2"],
  "audience": "A one-liner describing who should read this."
}

Rules:
- summary: Exactly 2 sentences, plain English, no jargon
- tags: 2-4 relevant topic tags (lowercase, e.g. "ai", "security", "startups")
- audience: One sentence, e.g. "Developers interested in database optimization"
"""


def build_user_prompt(story: dict) -> str:
    """Build the user prompt from story data."""
    title = story["title"]
    url = story["url"] or "No URL"
    author = story["author"] or "Unknown"
    points = story["points"] or 0
    comments = story["num_comments"] or 0

    return f"""Analyze this Hacker News story:

Title: {title}
URL: {url}
Author: {author}
Points: {points}
Comments: {comments}

Provide your analysis as JSON."""


def call_llm(client: anthropic.Anthropic, story: dict) -> tuple[dict, int, int]:
    """
    Call Claude API and return (parsed_response, input_tokens, output_tokens).
    Raises on API or parsing errors.
    """
    user_prompt = build_user_prompt(story)

    response = client.messages.create(
        model=LLM_MODEL,
        max_tokens=300,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": user_prompt}],
    )

    input_tokens = response.usage.input_tokens
    output_tokens = response.usage.output_tokens

    # Extract text content
    if not response.content:
        raise ValueError("Empty response from API")
    text = response.content[0].text

    # Strip markdown code blocks if present
    if text.startswith("```"):
        lines = text.split("\n")
        # Remove first line (```json) and last line (```)
        text = "\n".join(lines[1:-1] if lines[-1] == "```" else lines[1:])

    # Parse JSON response
    parsed = json.loads(text)

    # Validate required fields
    if not all(k in parsed for k in ("summary", "tags", "audience")):
        raise ValueError(f"Missing required fields in response: {parsed}")

    return parsed, input_tokens, output_tokens


def process_story(conn, client: anthropic.Anthropic, story: dict, run_id: int) -> bool:
    """
    Process a single story: call LLM, write results transactionally.
    Returns True if successful, False if failed.
    """
    story_id = story["id"]
    title = story["title"][:50]

    # Mark as processing (outside transaction - signals we're working on it)
    conn.execute("UPDATE stories SET status = 'processing' WHERE id = ?", (story_id,))
    conn.commit()

    try:
        # Call LLM
        result, input_tokens, output_tokens = call_llm(client, story)
        cost_usd = get_cost(LLM_MODEL, input_tokens, output_tokens)

        # Single transaction: update story + insert llm_run
        conn.execute("BEGIN IMMEDIATE")
        try:
            # Update story with results
            conn.execute(
                """
                UPDATE stories
                SET status = 'done',
                    prompt_version = ?,
                    summary = ?,
                    tags = ?,
                    audience = ?,
                    processed_in_run_id = ?
                WHERE id = ?
                """,
                (
                    PROMPT_VERSION,
                    result["summary"],
                    json.dumps(result["tags"]),
                    result["audience"],
                    run_id,
                    story_id,
                ),
            )

            # Insert cost record
            conn.execute(
                """
                INSERT INTO llm_runs (run_id, story_id, model, prompt_version, input_tokens, output_tokens, cost_usd)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (run_id, story_id, LLM_MODEL, PROMPT_VERSION, input_tokens, output_tokens, cost_usd),
            )

            conn.commit()
            print(f"  ✓ {title}... (${cost_usd:.6f})")
            return True

        except Exception as e:
            conn.rollback()
            raise e

    except Exception as e:
        # Mark as failed
        conn.execute(
            "UPDATE stories SET status = 'failed' WHERE id = ?",
            (story_id,),
        )
        conn.commit()
        print(f"  ✗ {title}... ERROR: {e}")
        return False


def process(limit: int = None) -> dict:
    """
    Main processing function.

    Args:
        limit: Optional max number of stories to process (for testing)

    Returns:
        Dict with run stats
    """
    if not ANTHROPIC_API_KEY:
        raise ValueError("ANTHROPIC_API_KEY not set. Create a .env file with your key.")

    init_db()
    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

    with get_connection() as conn:
        # Create a new run
        run_id = create_run(conn)
        print(f"Starting run {run_id}...")

        # Get stories to process
        stories = get_stories_to_process(conn, PROMPT_VERSION)
        if limit:
            stories = stories[:limit]

        total = len(stories)
        if total == 0:
            print("No stories to process.")
            finish_run(conn, run_id, 0, 0)
            return {"run_id": run_id, "processed": 0, "failed": 0, "total_cost": 0}

        print(f"Processing {total} stories...\n")

        processed = 0
        failed = 0

        for story in stories:
            # Convert Row to dict for easier access
            story_dict = dict(story)
            if process_story(conn, client, story_dict, run_id):
                processed += 1
            else:
                failed += 1

        # Get total cost for this run
        cursor = conn.execute(
            "SELECT SUM(cost_usd) as total FROM llm_runs WHERE run_id = ?",
            (run_id,),
        )
        total_cost = cursor.fetchone()["total"] or 0

        finish_run(conn, run_id, total, processed)

        print(f"\nRun {run_id} complete: {processed} processed, {failed} failed")
        print(f"Total cost: ${total_cost:.6f}")

        return {
            "run_id": run_id,
            "processed": processed,
            "failed": failed,
            "total_cost": total_cost,
        }


if __name__ == "__main__":
    import sys

    limit = None
    if len(sys.argv) > 1:
        try:
            limit = int(sys.argv[1])
        except ValueError:
            pass

    process(limit=limit)
