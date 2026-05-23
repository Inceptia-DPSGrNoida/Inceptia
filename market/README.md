# Market Mayhem — Setup Guide

## Local setup (your laptop)

### 1. Put all files in one folder
```
market-mayhem/
  main.py
  host.html
  team.html
  bm.html          ← keep your existing one
  game.db          ← auto-created on first run
  run_local.sh
```

### 2. Install Python dependencies (once)
```bash
pip install fastapi "uvicorn[standard]" aiosqlite
```

### 3. Run
```bash
bash run_local.sh
```
Or directly:
```bash
HOST_PASSWORD=host123 uvicorn main:app --host 0.0.0.0 --port 8000 --reload
```

### 4. Open in browser (must be via the server URL, NOT file://)
| Page | URL |
|------|-----|
| Player UI | http://localhost:8000 |
| Host Panel | http://localhost:8000/host |
| Black Market | http://localhost:8000/bm |

**⚠️ Do NOT open host.html by double-clicking the file.**
It must be opened through `http://localhost:8000/host` — otherwise all API calls fail silently.

### 5. Other devices on the same WiFi
Find your laptop's local IP (`ipconfig` on Windows, `ifconfig` on Mac/Linux).
Players open `http://192.168.x.x:8000` on their phones.

---

## Railway deployment

Set these environment variables in the Railway dashboard:
| Variable | Value |
|----------|-------|
| `HOST_PASSWORD` | Your chosen password |
| `DB_PATH` | `/data/game.db` (if using a persistent volume) |

`railway.json` and `Procfile` are already configured.

---

## Default host password (local)
```
host123
```
Change it in `run_local.sh` or set `HOST_PASSWORD=yourpassword` before running.

---

## Reset between games
Hit the **Reset** button in the host panel, or delete `game.db` and restart.
