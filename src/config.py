import os
from pathlib import Path
from dotenv import load_dotenv

# Load .env from project root
PROJECT_ROOT = Path(__file__).parent.parent
load_dotenv(PROJECT_ROOT / ".env")

# API Configuration
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")

# Model Configuration
LLM_MODEL = "claude-haiku-3-5-20241022"
PROMPT_VERSION = "v1"

# Pricing per token (USD) - Claude Haiku 3.5 as of 2024
PRICING = {
    "claude-haiku-3-5-20241022": {
        "input": 0.80 / 1_000_000,   # $0.80 per 1M input tokens
        "output": 4.00 / 1_000_000,  # $4.00 per 1M output tokens
    },
}

# Database
DB_PATH = PROJECT_ROOT / "db" / "hn_summaries.db"

# HN Algolia API
HN_API_BASE = "https://hn.algolia.com/api/v1"
HN_STORIES_TO_FETCH = 30  # Number of stories to fetch per run


def get_cost(model: str, input_tokens: int, output_tokens: int) -> float:
    """Calculate cost in USD for a given LLM call."""
    pricing = PRICING.get(model)
    if not pricing:
        raise ValueError(f"Unknown model: {model}")
    return (input_tokens * pricing["input"]) + (output_tokens * pricing["output"])
