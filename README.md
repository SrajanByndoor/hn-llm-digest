# HN Story Summarizer

A pipeline that fetches Hacker News stories, generates AI summaries using Claude, stores everything in SQLite, and serves a browsable web UI with cost tracking per run.

## Quick Start

```bash
cp .env.example .env        # Create config file
# Edit .env and add your ANTHROPIC_API_KEY
./run.sh                    # Fetch, process, and serve
```

## Stack

- **Python 3** 
- **FastAPI + Uvicorn** 
- **SQLite** 
- **Anthropic SDK** — Claude API (claude-haiku-4-5-20251001)
- **HTML/JS** 

## Design Choices

**SQLite** — single file, no server to run or manage, trivially portable and inspectable via CLI. At this scale (hundreds to low-thousands of rows) it has no real downside versus Postgres, and the schema/queries aren't SQLite-specific, so migrating later would be straightforward if scale or concurrent writers demanded it.

**Status machine (`stories.status`: pending → processing → done/failed)** — this is what makes crash recovery possible at all. Without persisted per-item state, a restarted process can't tell what it already finished — it would either redo everything (re-billing) or silently skip things. The `processing` state in particular is what lets a restart distinguish "never started" from "was interrupted mid-flight."

**Prompt versioning** — LLM output is a function of (story, prompt, model), not just the story. Versioning the prompt lets me improve it later and reprocess only stories below the current version, without re-billing stories already processed under it. Known limitation: only prompt text bumps the version today — swapping models alone won't trigger reprocessing, even though the model is logged per-row for audit.

**Separate `llm_runs` table** — `stories` reflects current best-known output; `llm_runs` is an append-only ledger of every attempt, ever, at any cost. This split is what makes "what did run X cost me" answerable (`SELECT SUM(cost_usd) FROM llm_runs WHERE run_id = ?`), and it's why I store raw token counts rather than just a precomputed dollar figure — when I caught a wrong per-token rate partway through building this, I could recompute historical costs without re-calling the API.

## One Thing I'd Do Differently

There's a narrow gap in crash-safety: the LLM API call happens outside any DB transaction, so if the process is hard-killed in the window between the API responding and the result being committed, that call is billed but never logged so a resume would call the LLM again for the same story, paying twice with only one row to show for it. The fix should be structural: add a `status` column to `llm_runs` (`attempted` → `completed`) [schema change] and commit an `attempted` row *before* making the API call, not after [code patch]. On resume, a story with an unresolved `attempted` row can't be safely auto-retried, since there's no way to know locally whether the prior call actually succeeded so it would need to be flagged for manual review (or reconciled against Anthropic's own usage dashboard) rather than silently retried, since guessing wrong either double-bills or drops a paid-for result.
## Project Structure

```
├── run.sh              # Single entry point
├── .env.example        # Config template
├── src/
│   ├── config.py       # Settings, model pricing
│   ├── db.py           # Schema, connection helpers
│   ├── ingest.py       # Fetch from HN Algolia API
│   ├── process.py      # LLM calls, status machine, cost logging
│   └── server.py       # FastAPI endpoints
├── static/
│   └── index.html      # Web UI (vanilla JS)
└── scripts/
    ├── check_secrets.sh              # Audit git history for leaked keys
    └── migrate_fix_haiku_pricing.py  # One-off cost recalculation
```
