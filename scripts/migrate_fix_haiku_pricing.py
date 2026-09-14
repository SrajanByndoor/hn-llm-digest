#!/usr/bin/env python3
"""
One-off migration to fix cost_usd values for claude-haiku-4-5-20251001.

Safe to run multiple times - recomputes from stored token counts using
the corrected rates from src/config.py.
"""

import sys
from pathlib import Path

# Add project root to path so we can import src modules
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from src.config import PRICING, get_cost, DB_PATH
from src.db import get_connection

MODEL = "claude-haiku-4-5-20251001"


def migrate():
    if MODEL not in PRICING:
        print(f"Error: No pricing defined for {MODEL} in src/config.py")
        sys.exit(1)

    pricing = PRICING[MODEL]
    print(f"Using rates from src/config.py for {MODEL}:")
    print(f"  Input:  ${pricing['input'] * 1_000_000:.2f} per 1M tokens")
    print(f"  Output: ${pricing['output'] * 1_000_000:.2f} per 1M tokens")
    print()

    with get_connection() as conn:
        # Get all rows for this model
        cursor = conn.execute(
            """
            SELECT id, input_tokens, output_tokens, cost_usd
            FROM llm_runs
            WHERE model = ?
            """,
            (MODEL,),
        )
        rows = cursor.fetchall()

        if not rows:
            print(f"No rows found for model {MODEL}. Nothing to migrate.")
            return

        # Calculate before total and prepare updates
        before_total = sum(row["cost_usd"] for row in rows)
        updates = []

        for row in rows:
            new_cost = get_cost(MODEL, row["input_tokens"], row["output_tokens"])
            updates.append((new_cost, row["id"]))

        after_total = sum(u[0] for u in updates)

        # Check if already correct (idempotent)
        if abs(before_total - after_total) < 0.0000001:
            print(f"Costs already correct. No changes needed.")
            print(f"  Rows checked: {len(rows)}")
            print(f"  Total cost:   ${before_total:.6f}")
            return

        # Run update in a single transaction
        conn.execute("BEGIN IMMEDIATE")
        try:
            for new_cost, row_id in updates:
                conn.execute(
                    "UPDATE llm_runs SET cost_usd = ? WHERE id = ?",
                    (new_cost, row_id),
                )
            conn.commit()
        except Exception as e:
            conn.rollback()
            print(f"Error during migration: {e}")
            sys.exit(1)

        # Print summary
        print(f"Migration complete!")
        print(f"  Rows updated:  {len(rows)}")
        print(f"  Before total:  ${before_total:.6f}")
        print(f"  After total:   ${after_total:.6f}")
        print(f"  Difference:    ${after_total - before_total:+.6f}")


if __name__ == "__main__":
    migrate()
