"""
Fetch top/new stories from Hacker News Algolia API and store in SQLite.
Idempotent: running twice won't create duplicates (dedupe on objectID).
"""

import httpx
from .config import HN_API_BASE, HN_STORIES_TO_FETCH
from .db import init_db, get_connection, insert_story


def fetch_front_page_stories(limit: int = HN_STORIES_TO_FETCH) -> list[dict]:
    """
    Fetch front page stories from HN Algolia API.
    Uses the search endpoint sorted by date for recent top stories.
    """
    url = f"{HN_API_BASE}/search"
    params = {
        "tags": "front_page",
        "hitsPerPage": limit,
    }

    response = httpx.get(url, params=params, timeout=30.0)
    response.raise_for_status()

    data = response.json()
    return data.get("hits", [])


def fetch_new_stories(limit: int = HN_STORIES_TO_FETCH) -> list[dict]:
    """
    Fetch newest stories from HN Algolia API.
    """
    url = f"{HN_API_BASE}/search_by_date"
    params = {
        "tags": "story",
        "hitsPerPage": limit,
    }

    response = httpx.get(url, params=params, timeout=30.0)
    response.raise_for_status()

    data = response.json()
    return data.get("hits", [])


def ingest(fetch_new: bool = False) -> dict:
    """
    Main ingestion function.

    Args:
        fetch_new: If True, fetch newest stories. If False, fetch front page.

    Returns:
        Dict with counts: total fetched, newly inserted, already existed
    """
    init_db()

    if fetch_new:
        print(f"Fetching {HN_STORIES_TO_FETCH} newest stories...")
        stories = fetch_new_stories()
    else:
        print(f"Fetching {HN_STORIES_TO_FETCH} front page stories...")
        stories = fetch_front_page_stories()

    print(f"Retrieved {len(stories)} stories from API")

    inserted = 0
    skipped = 0

    with get_connection() as conn:
        for story in stories:
            if not story.get("title"):
                continue

            was_inserted = insert_story(conn, story)
            if was_inserted:
                inserted += 1
                print(f"  + {story.get('title', 'No title')[:60]}...")
            else:
                skipped += 1

    print(f"\nIngestion complete: {inserted} new, {skipped} already existed")

    return {
        "fetched": len(stories),
        "inserted": inserted,
        "skipped": skipped,
    }


if __name__ == "__main__":
    import sys
    fetch_new = "--new" in sys.argv
    ingest(fetch_new=fetch_new)
