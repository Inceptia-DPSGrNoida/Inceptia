#!/bin/bash
# ─────────────────────────────────────────────
#  Market Mayhem — Local Runner
#  Usage: bash run_local.sh
# ─────────────────────────────────────────────

# Install dependencies if needed
pip install fastapi uvicorn[standard] aiosqlite --break-system-packages -q 2>/dev/null || \
pip install fastapi "uvicorn[standard]" aiosqlite -q 2>/dev/null

# Set local environment variables
export DB_PATH="game.db"
export HOST_PASSWORD="RasnaKaGuavaJuice"   # ← change this to whatever you want locally

echo ""
echo "  ⚡  Market Mayhem"
echo "  ──────────────────────────────────────"
echo "  Player UI  →  http://localhost:5000"
echo "  Host Panel →  http://localhost:5000/host"
echo "  Black Mkt  →  http://localhost:5000/bm"
echo "  Password   →  $HOST_PASSWORD"
echo "  ──────────────────────────────────────"
echo "  Press Ctrl+C to stop"
echo ""

uvicorn main:app --host 0.0.0.0 --port 5000 --reload
