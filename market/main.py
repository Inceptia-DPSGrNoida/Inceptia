"""
Market Mayhem — main.py
FastAPI + WebSockets + SQLite
Run: uvicorn main:app --reload --port 8000
Team view:  http://localhost:8000
Host panel: http://localhost:8000/host
"""

import asyncio, json, os, random, time, uuid
from pathlib import Path
from contextlib import asynccontextmanager
from typing import Dict, Optional

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException
from fastapi.responses import HTMLResponse, FileResponse
from fastapi.staticfiles import StaticFiles
import aiosqlite

# ── Config ────────────────────────────────────────────────────────────────────
DB_PATH        = Path(os.getenv("DB_PATH", "game.db"))
HOST_PASSWORD  = os.getenv("HOST_PASSWORD", "InceptiaHost2025")
STARTING_CASH      = 50_000
ROUND_DURATION     = 1200     # seconds (20 min) — host can end early
BORROW_FEE         = 0.10     # 10% short-sell borrow fee upfront
LOAN_AMOUNT        = 50_000   # fixed loan size players can take once
LOAN_INTEREST      = 0.10     # 10% interest charged at end of each round
BANKRUPTCY_RESTART = 25_000   # cash given on bankruptcy restart (no loan)
DRIFT_INTERVAL     = 120      # seconds between passive price drifts mid-round

# ── Companies ─────────────────────────────────────────────────────────────────
BASE_COMPANIES = {
    "zora":      {"name":"Zora Industries",     "sector":"Manufacturing",   "risk":"Low",
                  "price":420, "bio":"A 52-year-old industrial giant. Builds everything from steel pipes to defence components. Boring but bulletproof — never missed a dividend in 30 years.",
                  "trait":"Old money. Steady as a rock."},
    "streamvx":  {"name":"StreamVerse",          "sector":"Media / OTT",    "risk":"High",
                  "price":310, "bio":"India's fastest-growing OTT platform with 62 million subscribers. Burning cash on content but subscriber numbers keep investors happy.",
                  "trait":"Binge-worthy. Wallet-draining."},
    "freshco":   {"name":"FreshCo",              "sector":"FMCG",           "risk":"Low",
                  "price":185, "bio":"India's most trusted household brand. Makes everything from biscuits to shampoo. Rural India runs on FreshCo.",
                  "trait":"Every Indian home has one."},
    "voltex":    {"name":"Voltex Energy",        "sector":"Renewable Energy","risk":"Medium-High",
                  "price":560, "bio":"Riding the green energy wave hard. Solar parks across 6 states, two wind farm contracts pending. Government darling.",
                  "trait":"Future is bright. Profits, not yet."},
    "mediq":     {"name":"MediQ",                "sector":"Pharma",          "risk":"Medium",
                  "price":275, "bio":"Sitting on a potential blockbuster drug in clinical trials. If approved, this stock 5x's overnight. If rejected, it tanks 40%.",
                  "trait":"One approval away from the moon."},
    "skylink":   {"name":"SkyLink Tech",         "sector":"Technology",     "risk":"High",
                  "price":890, "bio":"India's answer to every Silicon Valley giant. Overvalued by most metrics but investor sentiment keeps it flying.",
                  "trait":"Overhyped. Overpriced. Irresistible."},
    "swifthaul": {"name":"SwiftHaul Logistics",  "sector":"Logistics",      "risk":"Medium",
                  "price":340, "bio":"Built on the back of India's e-commerce explosion. Delivers 2.4 million packages a day across 18,000 pin codes.",
                  "trait":"The backbone of online India."},
    "crownmart": {"name":"CrownMart",            "sector":"Retail",         "risk":"Medium",
                  "price":220, "bio":"India's largest brick-and-mortar retail chain fighting back against quick commerce. New CEO, new strategy.",
                  "trait":"Old retail trying to run new tricks."},
    "shieldgen": {"name":"ShieldGen Defence",    "sector":"Defence",        "risk":"Low",
                  "price":490, "bio":"Primary domestic defence supplier. Every escalation at the border is good news for this stock.",
                  "trait":"Fear is their product. Stability is their promise."},
}

NOVAPAY = {
    "novapay": {"name":"NovaPay",  "sector":"Fintech",  "risk":"High",
                "price":200, "bio":"A UPI-based payments startup processing 800 million transactions/month. Just filed for listing. No profits yet, but volume numbers are insane.",
                "trait":"Could be the next PhonePe. Or the next cautionary tale."}
}

COMPANY_VOL = {
    "zora":      (0.005, 0.018, 0.48),
    "streamvx":  (0.030, 0.080, 0.45),
    "freshco":   (0.004, 0.016, 0.49),
    "voltex":    (0.020, 0.060, 0.44),
    "mediq":     (0.020, 0.070, 0.46),
    "skylink":   (0.035, 0.090, 0.44),
    "swifthaul": (0.012, 0.040, 0.46),
    "crownmart": (0.025, 0.075, 0.44),
    "shieldgen": (0.005, 0.020, 0.49),
    "novapay":   (0.040, 0.100, 0.43),
}

NEWS_POOL = [
    {"type":"insider",  "label":"Insider Hint",      "affects":"zora",      "direction": 1,  "real":True,  "text":"Insider tip: Zora Industries is in final discussions for a ₹2,800 crore government infrastructure contract."},
    {"type":"event",    "label":"Market Event",      "affects":"zora",      "direction":-1,  "real":True,  "text":"BREAKING: National union calls a 3-day strike at manufacturing hubs across 5 states. Zora's Pune plant affected."},
    {"type":"event",    "label":"Market Event",      "affects":"zora",      "direction": 1,  "real":True,  "text":"Zora Industries posts its 30th consecutive year of dividend payouts. Institutional investors increase stake by 4.2%."},
    {"type":"rumour",   "label":"Unverified Rumour", "affects":"zora",      "direction":-1,  "real":False, "text":"Rumour: Whistleblower claims Zora used substandard materials in a government project. Company denies all allegations."},
    {"type":"event",    "label":"Market Event",      "affects":"streamvx",  "direction":-1,  "real":True,  "text":"BREAKING: StreamVerse reports a 14% spike in subscriber churn after hiking subscription prices by ₹100/month."},
    {"type":"event",    "label":"Market Event",      "affects":"streamvx",  "direction": 1,  "real":True,  "text":"StreamVerse's latest original series crosses 200 million watch hours in its first week — biggest debut on any Indian OTT."},
    {"type":"rumour",   "label":"Unverified Rumour", "affects":"streamvx",  "direction":-1,  "real":False, "text":"Rumour: Former StreamVerse exec claims platform inflates subscriber counts to attract advertisers."},
    {"type":"insider",  "label":"Insider Hint",      "affects":"streamvx",  "direction": 1,  "real":True,  "text":"Insider tip: StreamVerse close to signing exclusive cricket streaming deal covering 3 IPL seasons — ₹4,200 crore contract."},
    {"type":"event",    "label":"Market Event",      "affects":"freshco",   "direction": 1,  "real":True,  "text":"FMCG sector hits record rural demand. FreshCo's 6 million kirana stores give it unmatched last-mile advantage."},
    {"type":"event",    "label":"Market Event",      "affects":"freshco",   "direction":-1,  "real":True,  "text":"BREAKING: Cyclone warning across eastern coast. FreshCo's largest manufacturing cluster in Odisha faces shutdown."},
    {"type":"rumour",   "label":"Unverified Rumour", "affects":"freshco",   "direction":-1,  "real":False, "text":"Rumour: Viral post claims FreshCo biscuits contain banned additives. Company calls it fabricated."},
    {"type":"insider",  "label":"Insider Hint",      "affects":"freshco",   "direction": 1,  "real":True,  "text":"Insider tip: FreshCo launching first premium skincare line targeting urban millennials — could add ₹1,200 crore to revenues."},
    {"type":"event",    "label":"Market Event",      "affects":"voltex",    "direction": 1,  "real":True,  "text":"BREAKING: Government announces ₹4,200 crore renewable energy subsidy. Voltex named as primary beneficiary."},
    {"type":"rumour",   "label":"Unverified Rumour", "affects":"voltex",    "direction": 1,  "real":False, "text":"Rumour: Voltex allegedly in merger talks with UAE sovereign wealth fund. Could value company at 3x market cap."},
    {"type":"event",    "label":"Market Event",      "affects":"voltex",    "direction":-1,  "real":True,  "text":"BREAKING: Two Voltex solar parks in Rajasthan fail safety inspections. Ministry suspends project clearances."},
    {"type":"event",    "label":"Market Event",      "affects":"voltex",    "direction": 1,  "real":True,  "text":"Voltex signs largest contract yet — 900MW solar park for state electricity board. Price target revised +35%."},
    {"type":"insider",  "label":"Insider Hint",      "affects":"mediq",     "direction": 1,  "real":True,  "text":"Insider tip: MediQ's Phase 3 drug trial results being submitted to DCGI this week. Internal sources: 'exceptionally strong'."},
    {"type":"event",    "label":"Market Event",      "affects":"mediq",     "direction":-1,  "real":True,  "text":"BREAKING: DCGI rejects MediQ's blockbuster drug application. Additional trials required — timeline pushed back 18 months."},
    {"type":"rumour",   "label":"Unverified Rumour", "affects":"mediq",     "direction": 1,  "real":False, "text":"Rumour: Global pharma giant reportedly in acquisition talks for MediQ at 60% premium. Unconfirmed."},
    {"type":"event",    "label":"Market Event",      "affects":"mediq",     "direction": 1,  "real":True,  "text":"MediQ quietly files 4 new patents for next-generation oncology drugs — a pipeline the market hasn't priced in."},
    {"type":"event",    "label":"Market Event",      "affects":"skylink",   "direction": 1,  "real":True,  "text":"SkyLink posts 34% YoY revenue growth in Q2, beating analyst consensus by ₹420 crore."},
    {"type":"event",    "label":"Market Event",      "affects":"skylink",   "direction":-1,  "real":True,  "text":"BREAKING: Massive data breach at SkyLink exposes 11 million user records. Government issues show-cause notice."},
    {"type":"rumour",   "label":"Unverified Rumour", "affects":"skylink",   "direction":-1,  "real":False, "text":"Rumour: Three senior SkyLink engineers resign en masse over dispute with founder. 'Toxic leadership' claims."},
    {"type":"insider",  "label":"Insider Hint",      "affects":"skylink",   "direction": 1,  "real":True,  "text":"Insider tip: SkyLink to announce AI product partnership with top US tech firm next week."},
    {"type":"event",    "label":"Market Event",      "affects":"swifthaul", "direction": 1,  "real":True,  "text":"SwiftHaul reports 28% surge in same-day delivery volume. Signs exclusive 3-year contract with India's largest e-commerce platform."},
    {"type":"event",    "label":"Market Event",      "affects":"swifthaul", "direction":-1,  "real":True,  "text":"BREAKING: Fuel prices rise 12% following global crude oil surge. SwiftHaul's 18,000-vehicle fleet faces margin compression."},
    {"type":"rumour",   "label":"Unverified Rumour", "affects":"swifthaul", "direction":-1,  "real":False, "text":"Rumour: SwiftHaul allegedly under-reporting delivery failure rates to maintain contract metrics."},
    {"type":"insider",  "label":"Insider Hint",      "affects":"swifthaul", "direction": 1,  "real":True,  "text":"Insider tip: SwiftHaul finalising cold-chain logistics venture for pharma distribution — high-margin new segment."},
    {"type":"rumour",   "label":"Unverified Rumour", "affects":"crownmart", "direction": 1,  "real":False, "text":"Rumour: Private equity firm building stake in CrownMart ahead of alleged management buyout."},
    {"type":"event",    "label":"Market Event",      "affects":"crownmart", "direction":-1,  "real":True,  "text":"BREAKING: Blinkit announces 10-minute grocery delivery expansion to 50 new cities — directly attacking CrownMart's core base."},
    {"type":"event",    "label":"Market Event",      "affects":"crownmart", "direction": 1,  "real":True,  "text":"CrownMart's new CEO unveils restructuring plan: close 120 loss-making stores, double down on private label products."},
    {"type":"insider",  "label":"Insider Hint",      "affects":"crownmart", "direction":-1,  "real":True,  "text":"Insider tip: CrownMart's Q3 same-store sales show 9% decline. Results due next week. Insiders quietly reducing positions."},
    {"type":"event",    "label":"Market Event",      "affects":"shieldgen", "direction": 1,  "real":True,  "text":"BREAKING: Escalating border tensions prompt ₹18,000 crore emergency defence procurement. ShieldGen is primary supplier for 3 of 5 categories."},
    {"type":"event",    "label":"Market Event",      "affects":"shieldgen", "direction": 1,  "real":True,  "text":"ShieldGen receives export clearance to supply radar systems to two allied nations."},
    {"type":"rumour",   "label":"Unverified Rumour", "affects":"shieldgen", "direction":-1,  "real":False, "text":"Rumour: Parliamentary committee reviewing ShieldGen's pricing on a recent armoured vehicle contract. Overpricing allegations."},
    {"type":"insider",  "label":"Insider Hint",      "affects":"shieldgen", "direction": 1,  "real":True,  "text":"Insider tip: ShieldGen secured a 7-year maintenance contract for a classified drone programme worth ₹6,000 crore."},
]

QUIZ_QUESTIONS = [
    "What does IPO stand for?",
    "If a stock's P/E ratio is 50 and EPS is ₹10, what's the stock price?",
    "What does 'going short' on a stock mean?",
    "What is a market circuit breaker?",
    "What does SEBI stand for?",
    "If inflation rises sharply, what typically happens to bond prices?",
    "What is the difference between equity and debt financing?",
    "What does 'market capitalisation' mean?",
    "Name one difference between a bull market and a bear market.",
    "What is a dividend?",
    "What does 'liquid asset' mean?",
    "If a company's revenue is ₹100 crore and net profit is ₹10 crore, what is the profit margin?",
]

# ── DB setup ──────────────────────────────────────────────────────────────────
async def get_db():
    return await aiosqlite.connect(DB_PATH)

async def init_db():
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS game (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS players (
                code TEXT PRIMARY KEY,
                name TEXT,
                cash REAL DEFAULT 50000,
                holdings TEXT DEFAULT '{}',
                shorts TEXT DEFAULT '{}',
                loan REAL DEFAULT 0,
                frozen INTEGER DEFAULT 0,
                pred_stock TEXT,
                pred_amount REAL DEFAULT 0
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS codes (
                code TEXT PRIMARY KEY
            )
        """)
        await db.commit()
        # Init game state if not present
        row = await (await db.execute("SELECT value FROM game WHERE key='state'")).fetchone()
        if not row:
            await _write_state(db, _default_state())
            await db.commit()

async def _write_state(db, state: dict):
    await db.execute(
        "INSERT OR REPLACE INTO game (key, value) VALUES ('state', ?)",
        (json.dumps(state),)
    )

async def read_state() -> dict:
    async with aiosqlite.connect(DB_PATH) as db:
        row = await (await db.execute("SELECT value FROM game WHERE key='state'")).fetchone()
        if row:
            return json.loads(row[0])
    return _default_state()

async def write_state(state: dict):
    async with aiosqlite.connect(DB_PATH) as db:
        await _write_state(db, state)
        await db.commit()

def _default_state() -> dict:
    companies = {k: {**v, "prev_price": v["price"]} for k, v in BASE_COMPANIES.items()}
    return {
        "phase": "lobby",
        "round": 0,
        "round_end_time": None,
        "break_end_time": None,
        "companies": companies,
        "novapay_listed": False,
        "news": [],
        "news_used": [],
        "circuit_broken": None,       # stock id or None
        "circuit_until": None,
        "blackout": False,
        "quiz_active": False,
        "quiz_question": None,
        "quiz_buzzed": None,          # name of first buzzer
        "prev_holdings": {k: 0 for k in companies},
        "merge_bids": {},             # bid_id -> bid data
    }

# ── Connection manager ────────────────────────────────────────────────────────
class ConnectionManager:
    def __init__(self):
        self.players: Dict[str, WebSocket] = {}   # code -> ws
        self.hosts:   list[WebSocket]      = []

    async def connect_player(self, code: str, ws: WebSocket):
        await ws.accept()
        self.players[code] = ws

    def disconnect_player(self, code: str):
        self.players.pop(code, None)

    async def connect_host(self, ws: WebSocket):
        await ws.accept()
        self.hosts.append(ws)

    def disconnect_host(self, ws: WebSocket):
        if ws in self.hosts:
            self.hosts.remove(ws)

    async def send_player(self, code: str, msg: dict):
        ws = self.players.get(code)
        if ws:
            try:
                await ws.send_text(json.dumps(msg))
            except Exception:
                self.disconnect_player(code)

    async def broadcast_all(self, msg: dict):
        dead = []
        for code, ws in list(self.players.items()):
            try:
                await ws.send_text(json.dumps(msg))
            except Exception:
                dead.append(code)
        for c in dead:
            self.disconnect_player(c)

    async def broadcast_hosts(self, msg: dict):
        dead = []
        for ws in list(self.hosts):
            try:
                await ws.send_text(json.dumps(msg))
            except Exception:
                dead.append(ws)
        for ws in dead:
            self.disconnect_host(ws)

manager = ConnectionManager()

# ── Helpers ───────────────────────────────────────────────────────────────────
async def get_player(code: str) -> Optional[dict]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        row = await (await db.execute(
            "SELECT * FROM players WHERE code=?", (code,)
        )).fetchone()
        if not row:
            return None
        return {
            "code":     row["code"],
            "name":     row["name"],
            "cash":     row["cash"],
            "holdings": json.loads(row["holdings"]),
            "shorts":   json.loads(row["shorts"]),
            "loan":     row["loan"],
            "frozen":   bool(row["frozen"]),
            "pred_stock":  row["pred_stock"],
            "pred_amount": row["pred_amount"],
        }

async def save_player(p: dict):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            INSERT OR REPLACE INTO players
              (code, name, cash, holdings, shorts, loan, frozen, pred_stock, pred_amount)
            VALUES (?,?,?,?,?,?,?,?,?)
        """, (
            p["code"], p["name"], p["cash"],
            json.dumps(p["holdings"]), json.dumps(p["shorts"]),
            p["loan"], int(p["frozen"]),
            p.get("pred_stock"), p.get("pred_amount", 0)
        ))
        await db.commit()

async def all_players() -> list[dict]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        rows = await (await db.execute("SELECT * FROM players")).fetchall()
        return [{
            "code":     r["code"],
            "name":     r["name"],
            "cash":     r["cash"],
            "holdings": json.loads(r["holdings"]),
            "shorts":   json.loads(r["shorts"]),
            "loan":     r["loan"],
            "frozen":   bool(r["frozen"]),
            "pred_stock":  r["pred_stock"],
            "pred_amount": r["pred_amount"],
        } for r in rows]

async def all_codes() -> set:
    async with aiosqlite.connect(DB_PATH) as db:
        rows = await (await db.execute("SELECT code FROM codes")).fetchall()
        return {r[0] for r in rows}

def player_view(p: dict, state: dict) -> dict:
    """Compute derived fields for broadcasting to the player."""
    companies = state["companies"]
    holdings  = p["holdings"]
    shorts    = p["shorts"]

    portfolio = {}
    for cid, qty in holdings.items():
        if qty > 0 and cid in companies:
            c    = companies[cid]
            avg  = p.get("avg_cost", {}).get(cid, c["price"]) if isinstance(p.get("avg_cost"), dict) else c["price"]
            price = c["price"] if not state.get("blackout") else None
            val  = qty * (price or 0)
            portfolio[cid] = {
                "qty":   qty,
                "avg":   avg,
                "price": price,
                "value": val,
                "pnl":   val - qty * avg,
            }

    port_value = sum(h["qty"] * companies[cid]["price"]
                     for cid, h in portfolio.items() if cid in companies)
    short_pnl  = 0
    for sid, s in shorts.items():
        if s["stock"] in companies:
            cover_price = companies[s["stock"]]["price"]
            s["pnl"] = (s["sell_price"] - cover_price) * s["qty"]
            short_pnl += s["pnl"]

    return {
        "cash":      p["cash"],
        "loan":      p["loan"],
        "frozen":    p["frozen"],
        "net_worth": p["cash"] + port_value - p["loan"] + short_pnl,
        "portfolio": portfolio,
        "shorts":    shorts,
    }

def leaderboard(players: list[dict], state: dict) -> list[dict]:
    rows = []
    for p in players:
        if not p["name"]:
            continue
        pv = player_view(p, state)
        rows.append({"name": p["name"], "net_worth": pv["net_worth"]})
    rows.sort(key=lambda x: x["net_worth"], reverse=True)
    for i, r in enumerate(rows):
        r["rank"] = i + 1
    return rows

async def broadcast_prices(state: dict):
    players = await all_players()
    board   = leaderboard(players, state)
    prices  = {k: c["price"] for k, c in state["companies"].items()}
    await manager.broadcast_all({"type": "prices_bulk", "prices": prices, "board": board})
    await manager.broadcast_hosts({"type": "prices_bulk", "prices": prices, "board": board})

async def broadcast_player_update(code: str, state: dict):
    p = await get_player(code)
    if p:
        await manager.send_player(code, {"type": "player_update", "player": player_view(p, state)})

def pick_news(state: dict, count: int = 3) -> list[dict]:
    used = set(state.get("news_used", []))
    pool = [n for n in NEWS_POOL if n["text"] not in used]
    chosen = random.sample(pool, min(count, len(pool)))
    state["news_used"] = state.get("news_used", []) + [n["text"] for n in chosen]
    return chosen

def fluctuate_prices(state: dict, news: list[dict]):
    companies = state["companies"]
    circuit   = state.get("circuit_broken")
    for cid, c in companies.items():
        if cid == circuit:
            continue
        c["prev_price"] = c["price"]
        lo, hi, bias = COMPANY_VOL.get(cid, (0.02, 0.06, 0.45))
        mag = random.uniform(lo, hi)
        direction = 1 if random.random() > bias else -1
        change = direction * mag
        # News impact
        for n in news:
            if n["affects"] == cid:
                impact = random.uniform(0.06, 0.14) if n.get("real") else random.uniform(0.01, 0.03)
                change += n["direction"] * impact
        c["price"] = max(10, round(c["price"] * (1 + change)))

# ── Circuit breaker auto-lift ─────────────────────────────────────────────────
async def circuit_lift_task(state: dict, stock: str, until: float):
    delay = until - time.time()
    if delay > 0:
        await asyncio.sleep(delay)
    state2 = await read_state()
    if state2.get("circuit_broken") == stock:
        state2["circuit_broken"] = None
        state2["circuit_until"]  = None
        await write_state(state2)
        cname = state2["companies"].get(stock, {}).get("name", stock)
        await manager.broadcast_all({"type": "circuit_lifted", "msg": f"Circuit breaker lifted on {cname}. Trading resumed."})

# ── Passive price drift (runs every DRIFT_INTERVAL seconds while trading) ─────
async def price_drift_loop():
    """Background task: small random price movements mid-round so the board feels alive."""
    await asyncio.sleep(30)   # wait for server to settle on startup
    while True:
        await asyncio.sleep(DRIFT_INTERVAL)
        state = await read_state()
        if state.get("phase") != "trading":
            continue
        companies  = state["companies"]
        circuit    = state.get("circuit_broken")
        changed    = False
        for cid, c in companies.items():
            if cid == circuit:
                continue
            # Tiny drift — max ±3%
            lo, hi, bias = COMPANY_VOL.get(cid, (0.005, 0.03, 0.46))
            mag   = random.uniform(0.002, min(0.03, hi * 0.4))
            direc = 1 if random.random() > bias else -1
            c["price"] = max(10, round(c["price"] * (1 + direc * mag)))
            changed = True
        if changed:
            await write_state(state)
            players = await all_players()
            board   = leaderboard(players, state)
            prices  = {k: v["price"] for k, v in companies.items()}
            await manager.broadcast_all({"type": "prices_bulk", "prices": prices, "board": board})

# ── Lifespan ──────────────────────────────────────────────────────────────────
@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    asyncio.create_task(price_drift_loop())
    yield

app = FastAPI(lifespan=lifespan)

# ── Static files — serve team.html and host.html ──────────────────────────────
BASE_DIR = Path(__file__).parent

@app.get("/", response_class=HTMLResponse)
async def serve_team():
    p = BASE_DIR / "team.html"
    if p.exists():
        return HTMLResponse(p.read_text(encoding="utf-8"))
    return HTMLResponse("<h1>team.html not found</h1>", status_code=404)

@app.get("/host", response_class=HTMLResponse)
async def serve_host():
    p = BASE_DIR / "host.html"
    if p.exists():
        return HTMLResponse(p.read_text(encoding="utf-8"))
    return HTMLResponse("<h1>host.html not found</h1>", status_code=404)

# ── REST: code management ─────────────────────────────────────────────────────
@app.post("/api/codes/generate")
async def generate_codes(count: int = 10):
    codes = [uuid.uuid4().hex[:6].upper() for _ in range(count)]
    async with aiosqlite.connect(DB_PATH) as db:
        await db.executemany("INSERT OR IGNORE INTO codes (code) VALUES (?)", [(c,) for c in codes])
        await db.commit()
    return {"codes": codes}

@app.get("/api/codes")
async def list_codes():
    codes = await all_codes()
    players = await all_players()
    used = {p["code"] for p in players if p["name"]}
    return {"codes": sorted(codes), "used": sorted(used)}

@app.delete("/api/codes/{code}")
async def delete_code(code: str):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("DELETE FROM codes WHERE code=?", (code,))
        await db.execute("DELETE FROM players WHERE code=?", (code,))
        await db.commit()
    manager.disconnect_player(code)
    return {"ok": True}

@app.get("/api/state")
async def api_state():
    state   = await read_state()
    players = await all_players()
    board   = leaderboard(players, state)
    return {"state": state, "board": board, "player_count": len([p for p in players if p["name"]])}

@app.get("/api/players")
async def api_players():
    """Returns all joined players with their code, name, and net worth. Used by host panel."""
    state   = await read_state()
    players = await all_players()
    board   = leaderboard(players, state)
    name_to_code = {p["name"]: p["code"] for p in players if p["name"]}
    return {"players": name_to_code, "board": board}

@app.get("/api/players/detail")
async def api_players_detail():
    """Returns full player data for host panel (loans, cash, net worth)."""
    state   = await read_state()
    players = await all_players()
    result  = []
    for p in players:
        if not p["name"]:
            continue
        pv = player_view(p, state)
        result.append({
            "code":      p["code"],
            "name":      p["name"],
            "cash":      p["cash"],
            "loan":      p["loan"],
            "frozen":    p["frozen"],
            "net_worth": pv["net_worth"],
        })
    result.sort(key=lambda x: x["net_worth"], reverse=True)
    return {"players": result}

@app.delete("/api/players/{code}")
async def kick_player(code: str, pw: str):
    """Kick a player by code — removes from DB and disconnects their WebSocket."""
    if pw != HOST_PASSWORD:
        raise HTTPException(403, "Wrong password")
    async with aiosqlite.connect(DB_PATH) as db:
        row = await (await db.execute("SELECT name FROM players WHERE code=?", (code,))).fetchone()
        name = row[0] if row else code
        await db.execute("DELETE FROM players WHERE code=?", (code,))
        await db.execute("DELETE FROM codes WHERE code=?", (code,))
        await db.commit()
    # Disconnect their WebSocket
    ws = manager.players.get(code)
    if ws:
        try:
            await ws.send_text(json.dumps({"type": "kicked", "msg": "You have been removed from the game by the host."}))
            await ws.close()
        except Exception:
            pass
    manager.disconnect_player(code)
    # Notify everyone
    state   = await read_state()
    players = await all_players()
    board   = leaderboard(players, state)
    await manager.broadcast_all({"type": "leaderboard", "board": board})
    await manager.broadcast_hosts({"type": "player_kicked", "name": name, "code": code, "board": board})
    return {"ok": True, "name": name}

@app.post("/api/reset")
async def api_reset():
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("DELETE FROM players")
        await db.execute("DELETE FROM codes")
        await _write_state(db, _default_state())
        await db.commit()
    await manager.broadcast_all({"type": "reset"})
    await manager.broadcast_hosts({"type": "reset"})
    return {"ok": True}

# ── REST: host game controls ──────────────────────────────────────────────────
@app.post("/api/host/start_round")
async def start_round(pw: str):
    if pw != HOST_PASSWORD:
        raise HTTPException(403, "Wrong password")
    state = await read_state()
    if state["phase"] not in ("lobby", "break"):
        raise HTTPException(400, "Can't start round now")
    state["round"] += 1
    state["phase"]  = "trading"
    state["round_end_time"] = time.time() + ROUND_DURATION
    state["break_end_time"] = None
    # Unfreeze all players from previous insider scandal
    players = await all_players()
    for p in players:
        if p["frozen"]:
            p["frozen"] = False
            await save_player(p)
    news = pick_news(state, 2 if state["round"] == 1 else 3)
    state["news"].extend(news)
    fluctuate_prices(state, news)
    await write_state(state)
    players = await all_players()
    board   = leaderboard(players, state)
    await manager.broadcast_all({
        "type": "phase_change", "phase": "trading",
        "round": state["round"],
        "prices": {k: c["price"] for k, c in state["companies"].items()},
        "board": board,
    })
    for n in news:
        await manager.broadcast_all({"type": "news", **n})
    await manager.broadcast_hosts({"type": "state_update", "state": state, "board": board})
    return {"ok": True, "round": state["round"]}

@app.post("/api/host/end_round")
async def end_round(pw: str):
    if pw != HOST_PASSWORD:
        raise HTTPException(403)
    state = await read_state()
    if state["phase"] != "trading":
        raise HTTPException(400)
    state["phase"]         = "break"
    state["round_end_time"] = None
    state["break_end_time"] = time.time() + 300
    # Apply interest on loans
    players = await all_players()
    for p in players:
        if p["loan"] > 0:
            p["loan"] = round(p["loan"] * (1 + LOAN_INTEREST))
            await save_player(p)
    # Re-fetch after loan updates
    players = await all_players()
    # Margin call + bankruptcy check
    for p in players:
        if not p["name"]:
            continue
        pv = player_view(p, state)
        nw = pv["net_worth"]
        if p["loan"] > 0 and nw < p["loan"]:
            # Margin call — force-sell all holdings to cover loan
            total_raised = 0
            for cid, qty in list(p["holdings"].items()):
                if qty > 0 and cid in state["companies"]:
                    total_raised += qty * state["companies"][cid]["price"]
                    p["holdings"][cid] = 0
            p["cash"] += total_raised
            p["cash"]  = max(0, p["cash"] - p["loan"])
            p["loan"]  = 0
            await save_player(p)
            await manager.send_player(p["code"], {
                "type": "margin_call",
                "msg":  "⚠️ MARGIN CALL — Your net worth fell below your loan. All holdings liquidated to cover the debt.",
                "player": player_view(p, state),
            })
            await manager.broadcast_all({"type": "chaos", "event": "margin_call",
                                          "msg": f"📢 MARGIN CALL — {p['name']} was forced to liquidate their entire portfolio!"})
        # Bankruptcy — net worth fully negative (can happen if market crashed and shorts went wrong)
        pv2 = player_view(p, state)
        if pv2["net_worth"] <= 0:
            p["cash"]     = BANKRUPTCY_RESTART
            p["holdings"] = {}
            p["shorts"]   = {}
            p["loan"]     = 0
            await save_player(p)
            await manager.send_player(p["code"], {
                "type": "bankrupt",
                "msg":  f"💀 BANKRUPTCY — You've been wiped out. Restarting with ₹{BANKRUPTCY_RESTART:,}. No loan this time.",
                "player": player_view(p, state),
            })
            await manager.broadcast_all({"type": "chaos", "event": "bankrupt",
                                          "msg": f"💀 BANKRUPTCY — {p['name']} has gone bust and restarted with ₹{BANKRUPTCY_RESTART:,}!"})
    # Resolve prediction market
    await resolve_predictions(state, await all_players())
    await write_state(state)
    board = leaderboard(await all_players(), state)
    await manager.broadcast_all({"type": "phase_change", "phase": "break", "round": state["round"], "board": board})
    await manager.broadcast_hosts({"type": "state_update", "state": state, "board": board})
    return {"ok": True}

@app.post("/api/host/end_game")
async def end_game(pw: str):
    if pw != HOST_PASSWORD:
        raise HTTPException(403)
    state   = await read_state()
    players = await all_players()
    # Force-cover all shorts at current price
    for p in players:
        changed = False
        for sid, s in list(p["shorts"].items()):
            cover_price = state["companies"].get(s["stock"], {}).get("price", 0)
            pnl = (s["sell_price"] - cover_price) * s["qty"]
            p["cash"] += cover_price * s["qty"] + pnl
            del p["shorts"][sid]
            changed = True
        if changed:
            await save_player(p)
    players = await all_players()
    state["phase"] = "ended"
    await write_state(state)
    board = leaderboard(players, state)
    await manager.broadcast_all({"type": "game_ended", "board": board})
    await manager.broadcast_hosts({"type": "state_update", "state": state, "board": board})
    return {"ok": True, "board": board}

@app.post("/api/host/adjust_cash")
async def adjust_cash(data: dict, pw: str):
    """Manually add or deduct cash from a player. Direction: 1 = add, -1 = deduct."""
    if pw != HOST_PASSWORD:
        raise HTTPException(403)
    code      = data["code"]
    amount    = abs(int(data.get("amount", 0)))
    direction = int(data.get("direction", 1))
    p = await get_player(code)
    if not p:
        raise HTTPException(404, "Player not found")
    p["cash"] = max(0, p["cash"] + direction * amount)
    await save_player(p)
    state = await read_state()
    view  = player_view(p, state)
    await manager.send_player(code, {"type": "player_update", "player": view})
    sign = "+" if direction > 0 else "-"
    await manager.send_player(code, {"type": "info", "msg": f"Host adjustment: {sign}₹{amount:,} to your cash."})
    players = await all_players()
    board   = leaderboard(players, state)
    await manager.broadcast_hosts({"type": "state_update", "state": state, "board": board, "player_count": len([x for x in players if x["name"]])})
    return {"ok": True}

@app.post("/api/host/inject_news")
async def inject_news(data: dict, pw: str):
    if pw != HOST_PASSWORD:
        raise HTTPException(403)
    state = await read_state()
    n = {
        "type":      data.get("type", "event"),
        "label":     data.get("label", "Market Event"),
        "text":      data["text"],
        "affects":   data["affects"],
        "direction": data.get("direction", 1),
        "real":      data.get("real", True),
    }
    state["news"].append(n)
    c = state["companies"].get(data["affects"])
    if c:
        c["prev_price"] = c["price"]
        strength = random.uniform(0.07, 0.15) if n["real"] else random.uniform(0.01, 0.03)
        c["price"] = max(10, round(c["price"] * (1 + n["direction"] * strength)))
    await write_state(state)
    await manager.broadcast_all({"type": "news", **n})
    players = await all_players()
    board   = leaderboard(players, state)
    await manager.broadcast_all({"type": "prices_bulk", "prices": {k: v["price"] for k, v in state["companies"].items()}, "board": board})
    return {"ok": True}

@app.post("/api/host/secret_intel")
async def secret_intel(data: dict, pw: str):
    """Send private news tip to one player."""
    if pw != HOST_PASSWORD:
        raise HTTPException(403)
    code = data["code"]
    n = {"type": "insider", "label": "Secret Intel", "text": data["text"], "private": True}
    await manager.send_player(code, {"type": "news", **n})
    return {"ok": True}

@app.post("/api/host/manual_price")
async def manual_price(data: dict, pw: str):
    if pw != HOST_PASSWORD:
        raise HTTPException(403)
    state = await read_state()
    cid   = data["stock"]
    price = int(data["price"])
    if cid not in state["companies"]:
        raise HTTPException(400, "Unknown stock")
    state["companies"][cid]["prev_price"] = state["companies"][cid]["price"]
    state["companies"][cid]["price"]      = max(1, price)
    await write_state(state)
    players = await all_players()
    board   = leaderboard(players, state)
    await manager.broadcast_all({"type": "prices_bulk", "prices": {k: v["price"] for k, v in state["companies"].items()}, "board": board})
    return {"ok": True}

# ── REST: chaos events ────────────────────────────────────────────────────────
@app.post("/api/chaos/circuit_breaker")
async def chaos_circuit(data: dict, pw: str):
    if pw != HOST_PASSWORD:
        raise HTTPException(403)
    state = await read_state()
    stock = data["stock"]
    if stock not in state["companies"]:
        raise HTTPException(400)
    until = time.time() + 120
    state["circuit_broken"] = stock
    state["circuit_until"]  = until
    await write_state(state)
    cname = state["companies"][stock]["name"]
    msg = f"⚡ CIRCUIT BREAKER — Trading halted on {cname} for 2 minutes!"
    await manager.broadcast_all({"type": "chaos", "event": "circuit_breaker", "stock": stock, "msg": msg})
    asyncio.create_task(circuit_lift_task(state, stock, until))
    return {"ok": True}

@app.post("/api/chaos/tax_raid")
async def chaos_tax(pw: str):
    if pw != HOST_PASSWORD:
        raise HTTPException(403)
    players = await all_players()
    for p in players:
        tax = round(p["cash"] * 0.10)
        p["cash"] = max(0, p["cash"] - tax)
        await save_player(p)
    state   = await read_state()
    players = await all_players()
    board   = leaderboard(players, state)
    msg = "🚨 TAX RAID — SEBI freezes accounts! All players lose 10% of cash holdings instantly."
    await manager.broadcast_all({"type": "chaos", "event": "tax_raid", "msg": msg, "board": board})
    for p in players:
        if p["name"]:
            view = player_view(p, state)
            await manager.send_player(p["code"], {"type": "player_update", "player": view})
    return {"ok": True}

@app.post("/api/chaos/ipo_drop")
async def chaos_ipo(pw: str):
    if pw != HOST_PASSWORD:
        raise HTTPException(403)
    state = await read_state()
    if state.get("novapay_listed"):
        raise HTTPException(400, "NovaPay already listed")
    state["novapay_listed"] = True
    np = NOVAPAY["novapay"]
    state["companies"]["novapay"] = {**np, "prev_price": np["price"]}
    await write_state(state)
    msg = "🚀 IPO DROP — NovaPay lists on the exchange! 800 million transactions/month. Buy in now!"
    await manager.broadcast_all({
        "type":    "chaos",
        "event":   "ipo_drop",
        "msg":     msg,
        "company": {"id": "novapay", **np},
    })
    return {"ok": True}

@app.post("/api/chaos/insider_scandal")
async def chaos_insider(pw: str):
    """Freeze the top-ranked player's portfolio for 1 round."""
    if pw != HOST_PASSWORD:
        raise HTTPException(403)
    state   = await read_state()
    players = await all_players()
    board   = leaderboard(players, state)
    if not board:
        raise HTTPException(400, "No players yet")
    top_name = board[0]["name"]
    for p in players:
        if p["name"] == top_name:
            p["frozen"] = True
            await save_player(p)
            await manager.send_player(p["code"], {"type": "frozen", "msg": f"INSIDER TRADING SCANDAL — Your portfolio is frozen for this round!"})
            break
    msg = f"🔒 INSIDER TRADING SCANDAL — {top_name}'s portfolio has been frozen for this round!"
    await manager.broadcast_all({"type": "chaos", "event": "insider_scandal", "msg": msg})
    return {"ok": True}

@app.post("/api/chaos/market_crash")
async def chaos_crash(pw: str):
    if pw != HOST_PASSWORD:
        raise HTTPException(403)
    state = await read_state()
    for cid, c in state["companies"].items():
        c["prev_price"] = c["price"]
        c["price"] = max(10, round(c["price"] * 0.80))
    await write_state(state)
    players = await all_players()
    board   = leaderboard(players, state)
    prices  = {k: c["price"] for k, c in state["companies"].items()}
    msg = "📉 MARKET CRASH — All prices drop 20%! Panic selling ensues!"
    await manager.broadcast_all({"type": "chaos", "event": "market_crash", "msg": msg, "prices": prices, "board": board})
    for p in players:
        if p["name"]:
            await manager.send_player(p["code"], {"type": "player_update", "player": player_view(p, state)})
    return {"ok": True}

@app.post("/api/chaos/bull_run")
async def chaos_bull(data: dict, pw: str):
    if pw != HOST_PASSWORD:
        raise HTTPException(403)
    sector = data["sector"]
    state  = await read_state()
    boosted = []
    for cid, c in state["companies"].items():
        if c["sector"].lower() == sector.lower():
            c["prev_price"] = c["price"]
            c["price"] = round(c["price"] * 1.30)
            boosted.append(c["name"])
    if not boosted:
        raise HTTPException(400, f"No companies in sector '{sector}'")
    await write_state(state)
    players = await all_players()
    board   = leaderboard(players, state)
    prices  = {k: c["price"] for k, c in state["companies"].items()}
    msg = f"🐂 BULL RUN — {sector} sector surges 30%! {', '.join(boosted)} all up!"
    await manager.broadcast_all({"type": "chaos", "event": "bull_run", "msg": msg, "prices": prices, "board": board})
    return {"ok": True}

@app.post("/api/chaos/hostile_takeover")
async def chaos_takeover(data: dict, pw: str):
    """Force target player to sell all shares of a stock at market price."""
    if pw != HOST_PASSWORD:
        raise HTTPException(403)
    target_name = data["target"]
    stock       = data["stock"]
    state   = await read_state()
    players = await all_players()
    for p in players:
        if p["name"] == target_name:
            qty = p["holdings"].get(stock, 0)
            if qty == 0:
                raise HTTPException(400, f"{target_name} holds no {stock}")
            price = state["companies"][stock]["price"]
            p["cash"] += qty * price
            p["holdings"][stock] = 0
            await save_player(p)
            view = player_view(p, state)
            await manager.send_player(p["code"], {"type": "player_update", "player": view})
            cname = state["companies"][stock]["name"]
            await manager.send_player(p["code"], {"type": "info", "msg": f"⚔️ Hostile Takeover! You were forced to sell all {cname} shares at market price."})
            board = leaderboard(await all_players(), state)
            msg = f"⚔️ HOSTILE TAKEOVER — {target_name} forced to liquidate {cname} position!"
            await manager.broadcast_all({"type": "chaos", "event": "hostile_takeover", "msg": msg, "board": board})
            return {"ok": True}
    raise HTTPException(404, "Target not found")

@app.post("/api/chaos/blackout")
async def chaos_blackout(data: dict, pw: str):
    if pw != HOST_PASSWORD:
        raise HTTPException(403)
    state = await read_state()
    state["blackout"] = data.get("active", True)
    await write_state(state)
    msg = "🌑 BLACKOUT ROUND — All prices hidden! Trade blind." if state["blackout"] else "Prices are visible again."
    await manager.broadcast_all({"type": "blackout", "active": state["blackout"], "msg": msg,
                                  "prices": ({k: c["price"] for k, c in state["companies"].items()} if not state["blackout"] else {})})
    return {"ok": True}

@app.post("/api/chaos/quiz")
async def chaos_quiz(data: dict, pw: str):
    if pw != HOST_PASSWORD:
        raise HTTPException(403)
    state = await read_state()
    question = data.get("question") or random.choice(QUIZ_QUESTIONS)
    state["quiz_active"]   = True
    state["quiz_question"] = question
    state["quiz_buzzed"]   = None
    await write_state(state)
    await manager.broadcast_all({"type": "quiz_start", "question": question})
    return {"ok": True, "question": question}

@app.post("/api/chaos/quiz_award")
async def quiz_award(data: dict, pw: str):
    if pw != HOST_PASSWORD:
        raise HTTPException(403)
    state    = await read_state()
    winner   = data.get("winner")   # name
    correct  = data.get("correct", True)
    amount   = int(data.get("amount", 50_000))
    state["quiz_active"] = False
    await write_state(state)
    players = await all_players()
    for p in players:
        if p["name"] == winner and correct:
            p["cash"] += amount
            await save_player(p)
            view = player_view(p, await read_state())
            await manager.send_player(p["code"], {"type": "player_update", "player": view})
            break
    msg = f"⚡ QUIZ — {winner} buzzed first and {'got it right' if correct else 'got it wrong'}! {'₹' + f'{amount:,} awarded!' if correct else 'No bonus.'}"
    await manager.broadcast_all({"type": "quiz_result", "winner": winner, "correct": correct, "amount": amount if correct else 0, "msg": msg})
    return {"ok": True}

# ── Prediction market helpers ─────────────────────────────────────────────────
async def resolve_predictions(state: dict, players: list[dict]):
    """Called at end of round. Find stock that moved most; pay 2x to correct bettors."""
    companies = state["companies"]
    # Most-moved stock by % change
    best_cid, best_pct = None, 0.0
    for cid, c in companies.items():
        prev = c.get("prev_price", c["price"])
        if prev:
            pct = abs(c["price"] - prev) / prev
            if pct > best_pct:
                best_pct, best_cid = pct, cid
    if not best_cid:
        return
    for p in players:
        if p.get("pred_stock") == best_cid and p.get("pred_amount", 0) > 0:
            p["cash"] += p["pred_amount"] * 2
            await save_player(p)
        p["pred_stock"]  = None
        p["pred_amount"] = 0
        await save_player(p)
    cname = companies.get(best_cid, {}).get("name", best_cid)
    await manager.broadcast_all({"type": "news", "type": "event", "label": "Prediction Result",
                                  "text": f"Prediction Market resolved — {cname} moved most ({best_pct*100:.1f}%). Correct bettors get 2×!"})

# ── WebSocket: player ─────────────────────────────────────────────────────────
@app.websocket("/ws/player/{code}")
async def ws_player(websocket: WebSocket, code: str):
    code = code.upper()
    valid_codes = await all_codes()
    if code not in valid_codes:
        await websocket.accept()
        await websocket.send_text(json.dumps({"type": "error", "msg": "Invalid code. Check with your host."}))
        await websocket.close()
        return

    await manager.connect_player(code, websocket)
    state  = await read_state()
    player = await get_player(code)
    already_joined = player is not None and player["name"]

    # Send init
    init_msg = {
        "type":    "init",
        "phase":   state["phase"],
        "market":  state["companies"],
        "board":   leaderboard(await all_players(), state),
        "blackout": state.get("blackout", False),
        "joined":  bool(already_joined),
    }
    if already_joined:
        init_msg["name"]   = player["name"]
        init_msg["player"] = player_view(player, state)
    await websocket.send_text(json.dumps(init_msg))

    try:
        async for raw in websocket.iter_text():
            msg   = json.loads(raw)
            action = msg.get("action")
            state  = await read_state()
            player = await get_player(code)

            # ── Set name (join) ──────────────────────────────────────────────
            if action == "set_name":
                name = msg.get("name", "").strip()[:30]
                if not name:
                    await websocket.send_text(json.dumps({"type": "error", "msg": "Name can't be empty."}))
                    continue
                # Check duplicate
                players = await all_players()
                if any(p["name"] == name and p["code"] != code for p in players):
                    await websocket.send_text(json.dumps({"type": "error", "msg": "Name taken. Pick another."}))
                    continue
                if player:
                    player["name"] = name
                else:
                    player = {"code": code, "name": name, "cash": STARTING_CASH,
                              "holdings": {}, "shorts": {}, "loan": 0, "frozen": False,
                              "pred_stock": None, "pred_amount": 0, "avg_cost": {}}
                await save_player(player)
                view = player_view(player, state)
                await websocket.send_text(json.dumps({"type": "joined", "name": name, "player": view}))
                board = leaderboard(await all_players(), state)
                await manager.broadcast_all({"type": "leaderboard", "board": board})
                await manager.broadcast_hosts({"type": "player_joined", "name": name, "code": code})

            # ── Buy ──────────────────────────────────────────────────────────
            elif action == "buy":
                if state["phase"] != "trading":
                    await websocket.send_text(json.dumps({"type": "error", "msg": "Trading is closed."})); continue
                if not player:
                    await websocket.send_text(json.dumps({"type": "error", "msg": "Join first."})); continue
                if player["frozen"]:
                    await websocket.send_text(json.dumps({"type": "error", "msg": "Your portfolio is frozen this round."})); continue
                stock = msg.get("stock")
                qty   = int(msg.get("qty", 0))
                if stock not in state["companies"] or qty < 1:
                    await websocket.send_text(json.dumps({"type": "error", "msg": "Invalid trade."})); continue
                if state.get("circuit_broken") == stock:
                    await websocket.send_text(json.dumps({"type": "error", "msg": "Circuit breaker active — trading halted on this stock."})); continue
                price = state["companies"][stock]["price"]
                cost  = price * qty
                if player["cash"] < cost:
                    await websocket.send_text(json.dumps({"type": "error", "msg": f"Not enough cash. Need ₹{cost:,}."})); continue
                player["cash"] -= cost
                old_qty = player["holdings"].get(stock, 0)
                if not isinstance(player.get("avg_cost"), dict):
                    player["avg_cost"] = {}
                if old_qty > 0:
                    old_avg = player["avg_cost"].get(stock, price)
                    player["avg_cost"][stock] = (old_avg * old_qty + price * qty) / (old_qty + qty)
                else:
                    player["avg_cost"][stock] = price
                player["holdings"][stock] = old_qty + qty
                await save_player(player)
                view = player_view(player, state)
                await websocket.send_text(json.dumps({"type": "trade_ok", "msg": f"Bought {qty}× {state['companies'][stock]['name']} @ ₹{price:,}", "player": view}))
                board = leaderboard(await all_players(), state)
                await manager.broadcast_all({"type": "leaderboard", "board": board})

            # ── Sell ─────────────────────────────────────────────────────────
            elif action == "sell":
                if state["phase"] != "trading":
                    await websocket.send_text(json.dumps({"type": "error", "msg": "Trading is closed."})); continue
                if not player:
                    await websocket.send_text(json.dumps({"type": "error", "msg": "Join first."})); continue
                if player["frozen"]:
                    await websocket.send_text(json.dumps({"type": "error", "msg": "Your portfolio is frozen this round."})); continue
                stock = msg.get("stock")
                qty   = int(msg.get("qty", 0))
                owned = player["holdings"].get(stock, 0)
                if qty < 1 or qty > owned:
                    await websocket.send_text(json.dumps({"type": "error", "msg": f"You only own {owned} shares."})); continue
                if state.get("circuit_broken") == stock:
                    await websocket.send_text(json.dumps({"type": "error", "msg": "Circuit breaker active — trading halted."})); continue
                price = state["companies"][stock]["price"]
                player["cash"] += price * qty
                player["holdings"][stock] = owned - qty
                await save_player(player)
                view = player_view(player, state)
                await websocket.send_text(json.dumps({"type": "trade_ok", "msg": f"Sold {qty}× {state['companies'][stock]['name']} @ ₹{price:,}", "player": view}))
                board = leaderboard(await all_players(), state)
                await manager.broadcast_all({"type": "leaderboard", "board": board})

            # ── Short sell ───────────────────────────────────────────────────
            elif action == "short":
                if state["phase"] != "trading":
                    await websocket.send_text(json.dumps({"type": "error", "msg": "Trading is closed."})); continue
                if not player:
                    await websocket.send_text(json.dumps({"type": "error", "msg": "Join first."})); continue
                if player["frozen"]:
                    await websocket.send_text(json.dumps({"type": "error", "msg": "Portfolio frozen."})); continue
                stock = msg.get("stock")
                qty   = int(msg.get("qty", 0))
                if stock not in state["companies"] or qty < 1:
                    await websocket.send_text(json.dumps({"type": "error", "msg": "Invalid short."})); continue
                if stock in player["holdings"] and player["holdings"].get(stock, 0) > 0:
                    await websocket.send_text(json.dumps({"type": "error", "msg": "Can't short a stock you own."})); continue
                price    = state["companies"][stock]["price"]
                fee      = round(price * qty * BORROW_FEE)
                proceeds = price * qty
                if player["cash"] < fee:
                    await websocket.send_text(json.dumps({"type": "error", "msg": f"Need ₹{fee:,} borrow fee."})); continue
                player["cash"] -= fee
                player["cash"] += proceeds
                sid = uuid.uuid4().hex[:8]
                player["shorts"][sid] = {
                    "stock":      stock,
                    "qty":        qty,
                    "sell_price": price,
                    "fee":        fee,
                    "pnl":        0,
                }
                await save_player(player)
                view = player_view(player, state)
                await websocket.send_text(json.dumps({"type": "trade_ok", "msg": f"Shorted {qty}× {state['companies'][stock]['name']} @ ₹{price:,}. Fee: ₹{fee:,}.", "player": view}))

            # ── Short cover ──────────────────────────────────────────────────
            elif action == "short_cover":
                if not player:
                    await websocket.send_text(json.dumps({"type": "error", "msg": "Join first."})); continue
                sid = msg.get("short_id")
                s   = player["shorts"].get(sid)
                if not s:
                    await websocket.send_text(json.dumps({"type": "error", "msg": "Short position not found."})); continue
                cover_price = state["companies"][s["stock"]]["price"]
                cost        = cover_price * s["qty"]
                if player["cash"] < cost:
                    await websocket.send_text(json.dumps({"type": "error", "msg": f"Need ₹{cost:,} to cover."})); continue
                pnl = (s["sell_price"] - cover_price) * s["qty"]
                player["cash"] -= cost
                player["cash"] += pnl  # net: pay cover price, gain P&L
                del player["shorts"][sid]
                await save_player(player)
                sign = "+" if pnl >= 0 else ""
                view = player_view(player, state)
                await websocket.send_text(json.dumps({"type": "trade_ok", "msg": f"Short covered. P&L: {sign}₹{int(pnl):,}", "player": view}))

            # ── Quiz buzz ────────────────────────────────────────────────────
            elif action == "quiz_buzz":
                if not player or not state.get("quiz_active"):
                    continue
                if not state.get("quiz_buzzed"):
                    state["quiz_buzzed"] = player["name"]
                    await write_state(state)
                    await manager.broadcast_hosts({"type": "quiz_buzzed", "name": player["name"]})
                    await websocket.send_text(json.dumps({"type": "info", "msg": "You buzzed first! Wait for the host."}))
                else:
                    await websocket.send_text(json.dumps({"type": "info", "msg": f"{state['quiz_buzzed']} buzzed first."}))

            # ── Prediction ───────────────────────────────────────────────────
            elif action == "prediction":
                if state["phase"] != "break":
                    await websocket.send_text(json.dumps({"type": "error", "msg": "Predictions only during breaks."})); continue
                if not player:
                    await websocket.send_text(json.dumps({"type": "error", "msg": "Join first."})); continue
                stock  = msg.get("stock")
                amount = int(msg.get("amount", 0))
                if stock not in state["companies"]:
                    await websocket.send_text(json.dumps({"type": "error", "msg": "Invalid stock."})); continue
                if amount < 1 or amount > player["cash"]:
                    await websocket.send_text(json.dumps({"type": "error", "msg": "Invalid bet amount."})); continue
                player["cash"]        -= amount
                player["pred_stock"]   = stock
                player["pred_amount"]  = amount
                await save_player(player)
                view = player_view(player, state)
                cname = state["companies"][stock]["name"]
                await websocket.send_text(json.dumps({"type": "trade_ok", "msg": f"Bet ₹{amount:,} on {cname} moving most.", "player": view}))

            # ── Merger initiate ──────────────────────────────────────────────
            elif action == "merge_initiate":
                if state["phase"] != "trading" or not player:
                    continue
                partner_code = msg.get("partner_code", "").upper()
                stock  = msg.get("stock")
                qty    = int(msg.get("qty", 0))
                if stock not in state["companies"] or qty < 1:
                    await websocket.send_text(json.dumps({"type": "error", "msg": "Invalid merger request."})); continue
                partner = await get_player(partner_code)
                if not partner or not partner["name"]:
                    await websocket.send_text(json.dumps({"type": "error", "msg": "Partner not found."})); continue
                price = state["companies"][stock]["price"]
                each  = round(price * qty / 2)
                bid_id = uuid.uuid4().hex[:8]
                state["merge_bids"][bid_id] = {
                    "from_code":    code,
                    "from_name":    player["name"],
                    "partner_code": partner_code,
                    "stock": stock, "qty": qty, "each": each,
                }
                await write_state(state)
                await manager.send_player(partner_code, {
                    "type": "merge_request",
                    "bid_id": bid_id,
                    "from":  player["name"],
                    "stock": stock,
                    "qty":   qty,
                    "each":  each,
                })
                await websocket.send_text(json.dumps({"type": "info", "msg": f"Merger request sent to {partner['name']}."}))

            # ── Merger respond ───────────────────────────────────────────────
            elif action == "merge_respond":
                bid_id = msg.get("bid_id")
                accept = msg.get("accept", False)
                state  = await read_state()
                bid    = state.get("merge_bids", {}).get(bid_id)
                if not bid:
                    await websocket.send_text(json.dumps({"type": "error", "msg": "Merger bid expired."})); continue
                if not accept:
                    del state["merge_bids"][bid_id]
                    await write_state(state)
                    await manager.send_player(bid["from_code"], {"type": "info", "msg": f"{player['name']} declined the merger."})
                    continue
                # Execute merger
                p_init  = await get_player(bid["from_code"])
                p_resp  = await get_player(bid["partner_code"])
                stock   = bid["stock"]
                qty     = bid["qty"]
                each    = bid["each"]
                price   = state["companies"][stock]["price"]
                if p_init["cash"] < each or p_resp["cash"] < each:
                    await websocket.send_text(json.dumps({"type": "error", "msg": "Insufficient funds for merger."})); continue
                # Shares go to initiator
                p_init["cash"] -= each
                p_resp["cash"] -= each
                old_qty = p_init["holdings"].get(stock, 0)
                if not isinstance(p_init.get("avg_cost"), dict):
                    p_init["avg_cost"] = {}
                p_init["avg_cost"][stock] = ((p_init["avg_cost"].get(stock, price) * old_qty + price * qty) / (old_qty + qty)) if old_qty else price
                p_init["holdings"][stock]  = old_qty + qty
                await save_player(p_init)
                await save_player(p_resp)
                del state["merge_bids"][bid_id]
                await write_state(state)
                cname = state["companies"][stock]["name"]
                await manager.send_player(bid["from_code"],    {"type": "player_update", "player": player_view(p_init, state)})
                await manager.send_player(bid["partner_code"], {"type": "player_update", "player": player_view(p_resp, state)})
                await manager.send_player(bid["from_code"],    {"type": "info", "msg": f"Merger complete! Bought {qty}× {cname} jointly."})
                await websocket.send_text(json.dumps({"type": "info", "msg": f"Merger complete! {bid['from_name']} got {qty}× {cname}."}))

            # ── Take loan ────────────────────────────────────────────────────
            elif action == "take_loan":
                if not player:
                    await websocket.send_text(json.dumps({"type": "error", "msg": "Join first."})); continue
                if state["phase"] not in ("trading", "break"):
                    await websocket.send_text(json.dumps({"type": "error", "msg": "Can't take loans right now."})); continue
                if player["loan"] > 0:
                    await websocket.send_text(json.dumps({"type": "error", "msg": f"You already have a loan of ₹{int(player['loan']):,}. Repay it first."})); continue
                player["loan"] = LOAN_AMOUNT
                player["cash"] += LOAN_AMOUNT
                await save_player(player)
                view = player_view(player, state)
                await websocket.send_text(json.dumps({
                    "type":   "trade_ok",
                    "msg":    f"Loan of ₹{LOAN_AMOUNT:,} received. 10% interest charged every round.",
                    "player": view,
                }))

            # ── Repay loan ───────────────────────────────────────────────────
            elif action == "repay_loan":
                if not player:
                    await websocket.send_text(json.dumps({"type": "error", "msg": "Join first."})); continue
                if player["loan"] <= 0:
                    await websocket.send_text(json.dumps({"type": "error", "msg": "You have no loan to repay."})); continue
                repay_amt = int(msg.get("amount", player["loan"]))
                repay_amt = min(repay_amt, int(player["loan"]))
                if player["cash"] < repay_amt:
                    await websocket.send_text(json.dumps({"type": "error", "msg": f"Not enough cash. You have ₹{int(player['cash']):,}."})); continue
                player["cash"] -= repay_amt
                player["loan"] = max(0, player["loan"] - repay_amt)
                await save_player(player)
                view = player_view(player, state)
                remaining = player["loan"]
                await websocket.send_text(json.dumps({
                    "type":   "trade_ok",
                    "msg":    f"Repaid ₹{repay_amt:,}. {'Loan fully cleared! ✅' if remaining == 0 else f'₹{int(remaining):,} still outstanding.'}",
                    "player": view,
                }))

    except WebSocketDisconnect:
        pass
    finally:
        manager.disconnect_player(code)

# ── WebSocket: host ───────────────────────────────────────────────────────────
@app.websocket("/ws/host")
async def ws_host(websocket: WebSocket):
    await manager.connect_host(websocket)
    try:
        state   = await read_state()
        players = await all_players()
        board   = leaderboard(players, state)
        await websocket.send_text(json.dumps({"type": "state_update", "state": state, "board": board, "player_count": len([p for p in players if p["name"]])}))
        async for raw in websocket.iter_text():
            # Host WS is receive-only for pings / requests
            msg = json.loads(raw)
            if msg.get("type") == "ping":
                state   = await read_state()
                players = await all_players()
                board   = leaderboard(players, state)
                await websocket.send_text(json.dumps({"type": "state_update", "state": state, "board": board, "player_count": len([p for p in players if p["name"]])}))
    except WebSocketDisconnect:
        pass
    finally:
        manager.disconnect_host(websocket)