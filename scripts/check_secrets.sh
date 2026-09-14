#!/bin/bash
# Check git history for leaked secrets

echo "=== Checking git history for leaked secrets ==="
echo ""

# Get script directory and go to repo root
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR/.."

FOUND=0

# Check for API key patterns in git history
echo "Searching for API key patterns in git history..."

# Search for Anthropic API keys
MATCHES=$(git log -p --all 2>/dev/null | grep -c "sk-ant-" || true)
if [ "$MATCHES" -gt 0 ]; then
    echo "  WARNING: Found $MATCHES occurrences of 'sk-ant-'"
    FOUND=1
else
    echo "  OK: No 'sk-ant-' patterns found"
fi

# Search for exposed API key assignments
MATCHES=$(git log -p --all 2>/dev/null | grep -cE "ANTHROPIC_API_KEY\s*=\s*sk-" || true)
if [ "$MATCHES" -gt 0 ]; then
    echo "  WARNING: Found $MATCHES exposed API key assignments"
    FOUND=1
else
    echo "  OK: No exposed API key assignments found"
fi

echo ""

# Check if .env was ever committed
echo "Checking if .env was ever committed..."
if git log --all --full-history -- .env 2>/dev/null | grep -q .; then
    echo "  WARNING: .env appears in git history!"
    git log --all --full-history -- .env
    FOUND=1
else
    echo "  OK: .env was never committed"
fi

echo ""

# Check current .env is gitignored
echo "Checking .env is currently ignored..."
if git check-ignore .env >/dev/null 2>&1; then
    echo "  OK: .env is in .gitignore"
else
    echo "  WARNING: .env is NOT ignored by git!"
    FOUND=1
fi

echo ""
if [ $FOUND -eq 0 ]; then
    echo "=== ALL CHECKS PASSED ==="
    exit 0
else
    echo "=== WARNINGS FOUND - Review above ==="
    exit 1
fi
