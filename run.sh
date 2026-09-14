#!/bin/bash
set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

echo -e "${GREEN}=== HN Story Summarizer ===${NC}"
echo ""

# Get script directory (works even if called from elsewhere)
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# Check for .env file
if [ ! -f ".env" ]; then
    echo -e "${RED}ERROR: .env file not found${NC}"
    echo ""
    echo "Create it from the example:"
    echo "  cp .env.example .env"
    echo ""
    echo "Then edit .env and add your Anthropic API key:"
    echo "  ANTHROPIC_API_KEY=sk-ant-..."
    exit 1
fi

# Check that .env has an API key (not just the placeholder)
if grep -q "your-api-key-here" .env; then
    echo -e "${RED}ERROR: .env still contains placeholder value${NC}"
    echo ""
    echo "Edit .env and replace 'your-api-key-here' with your actual Anthropic API key"
    exit 1
fi

echo -e "${GREEN}✓${NC} .env file found"

# Create virtual environment if it doesn't exist
if [ ! -d "venv" ]; then
    echo -e "${YELLOW}Creating virtual environment...${NC}"
    python3 -m venv venv
fi

# Activate virtual environment
source venv/bin/activate

# Install dependencies
echo -e "${YELLOW}Installing dependencies...${NC}"
pip install -q -r requirements.txt

echo -e "${GREEN}✓${NC} Dependencies installed"
echo ""

# Run ingestion
echo -e "${YELLOW}Step 1: Fetching stories from Hacker News...${NC}"
python -m src.ingest

echo ""

# Run processing
echo -e "${YELLOW}Step 2: Processing stories with Claude...${NC}"
python -m src.process

echo ""

# Start server
echo -e "${GREEN}Step 3: Starting web server...${NC}"
echo ""
echo -e "Open ${GREEN}http://localhost:8000${NC} in your browser"
echo "Press Ctrl+C to stop"
echo ""

python -m src.server
