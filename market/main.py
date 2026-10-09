"""
Market Mayhem — main.py
FastAPI + WebSockets + SQLite (aiosqlite)

Local:   uvicorn main:app --reload --port 8000
Railway: uvicorn main:app --host 0.0.0.0 --port $PORT

Routes:
  /          →  team.html   (player trading UI)
  /host      →  host.html   (password-protected host panel — the only place rankings are shown)
  /board     →  board.html  (big-screen leaderboard for the host's projector)

Env vars (Railway dashboard):
  DB_PATH        = /data/game.db      (persistent volume)
  HOST_PASSWORD  = <your password>
"""

import asyncio
import re
import json
import os
import random
import time
import uuid
from collections import defaultdict
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Dict, Optional

import aiosqlite
from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles

from news_presets import NEWS_PRESETS, NEWS_POOL, FALSE_RUMOURS, ORGANISER_NOTES, PLOT_GROUPS
from apex20 import (
    BASE_COMPANIES, IPO_COMPANIES, SECTORS,
    COMPANY_VOL as _STOCK_VOL, PRICE_FLOORS as _STOCK_FLOORS,
    DIVIDEND_PER_SHARE, ACQUISITION_PAIR, HIGH_VOL, GUIDE, DOSSIER,
)

# ═══════════════════════════════════════════════════════════════
#  CONFIG
# ═══════════════════════════════════════════════════════════════
DB_PATH            = Path(os.getenv("DB_PATH", "game.db"))
HOST_PASSWORD      = os.getenv("HOST_PASSWORD", "Ich_liebe_Siya")
STARTING_CASH      = 150_000     # ₹1.5L starting cash for every player
MAX_ROUNDS         = 6
ROUND_DURATION     = 1200        # 20 min — host can end early
BREAK_DURATION     = 600         # 10 min between rounds
BANKRUPTCY_RESTART = 25_000      # cash a bankrupt player comes back with once the lock-out ends
BANKRUPTCY_LOCK_ROUNDS = 2       # a bankrupt player cannot trade or borrow for the next 2 rounds
BANKRUPTCY_MIN_DEBT_GAP = 900_000   # debt must exceed net worth by ~9 lakh to qualify
STT_RATE           = 0.002       # Securities Transaction Tax — 0.2% of every trade's value, accrued live
# ── PAUSED: wealth tax and income tax. The code paths are intact; setting a rate back above 0 turns them on. ──
INCOME_TAX_RATE    = 0.0    # (was 15% of whole-game realised gains, charged once at game end)
WEALTH_TAX_RATE    = 0.0    # (was 3% of the round-end leader's net worth)

# ── Chaos schedule: rounds 1-2 are normal; each of rounds 3-6 has exactly ONE chaos event ──
CHAOS_SCHEDULE = {
    3: "ipo_drop",         # the 2 held-back companies (different sectors) list at round start
    4: "dividend",         # the 8 dividend payers pay at round start AND again at the 10-minute mark
    5: "acquisition",      # at the 5-minute mark two companies from different sectors become linked + High volatility
    6: "truth_or_false",   # real news mixed with false rumours; only the host knows which is which
}
CHAOS_LABELS = {"ipo_drop": "IPO Drop", "dividend": "Dividend Payout",
                "acquisition": "Acquisition Rumour", "truth_or_false": "Truth or False"}
ACQUISITION_DELAY = 300          # seconds into the round before the acquisition rumour fires
DIVIDEND_SECOND_PAYOUT = ROUND_DURATION // 2   # seconds into the round for the second dividend payout
TRUTH_DROP_EVERY  = 240          # seconds between Truth-or-False drops (5 drops per 20-min round)
TRUTH_DROPS       = 5            # each drop = 1 true item + 1 false rumour, in random order


# Per-player asyncio lock to prevent concurrent buy/sell race conditions
_player_locks: Dict[str, asyncio.Lock] = defaultdict(asyncio.Lock)

# ═══════════════════════════════════════════════════════════════
#  BANKS — interest is charged on every outstanding loan at the end of EVERY round.
#  Rates are per round and tiered by balance: the lowest rate anywhere is 1% (Bharat Bank,
#  small loan) and the highest is 12% (ShadowCredit, maximum loan).
# ═══════════════════════════════════════════════════════════════
BANKS = {
    "bharat": {
        "name":    "Bharat Bank",
        "limit":   90_000,
        "options": [20_000, 40_000, 60_000, 90_000],
        "rate":    0.02,    # fallback flat rate if tiers are ever missing
        # Tiered by OUTSTANDING BALANCE at round-end: bigger balance = higher rate.
        # (threshold, rate) pairs, evaluated in order — first threshold >= balance wins.
        "rate_tiers": [(20_000, 0.01), (40_000, 0.02), (60_000, 0.03), (90_000, 0.04)],
        "desc":    "Safe, government-backed. Low rate, low limit — but borrow near the cap and the rate climbs too.",
    },
    "vcx": {
        "name":    "VentureCapX",
        "limit":   1_50_000,
        "options": [50_000, 75_000, 1_00_000, 1_50_000],
        "rate":    0.06,
        "rate_tiers": [(50_000, 0.03), (75_000, 0.05), (1_00_000, 0.07), (1_50_000, 0.09)],
        "desc":    "Aggressive growth lender. Higher limit, higher cost — and it gets steeper the more you take.",
    },
    "shadow": {
        "name":    "ShadowCredit",
        "limit":   3_00_000,
        "options": [1_00_000, 1_50_000, 2_00_000, 3_00_000],
        "rate":    0.09,
        "rate_tiers": [(1_00_000, 0.06), (1_50_000, 0.08), (2_00_000, 0.10), (3_00_000, 0.12)],
        "desc":    "No questions asked. Maximum leverage. The bigger the loan, the sharper the knife.",
    },
}

def safe_int(v, default=0) -> int:
    """Never raises — malformed/missing client input just falls back to default."""
    try:
        return int(v)
    except (TypeError, ValueError):
        return default

def safe_float(v, default=0.0) -> float:
    try:
        f = float(v)
        if f != f or f in (float("inf"), float("-inf")):  # NaN / Infinity guard
            return default
        return f
    except (TypeError, ValueError):
        return default

def bank_rate_for_balance(bank_id: str, balance: float) -> float:
    """Effective interest rate for a bank given the CURRENT outstanding balance.
    Bigger balance -> higher tier -> higher rate. Re-evaluated every round, so
    paying a loan down into a lower tier lowers next round's rate too."""
    bank = BANKS.get(bank_id)
    if not bank:
        return 0.0
    tiers = bank.get("rate_tiers")
    if not tiers:
        return bank.get("rate", 0.0)
    for threshold, rate in tiers:
        if balance <= threshold:
            return rate
    return tiers[-1][1]  # above the highest tier -> top rate

# ═══════════════════════════════════════════════════════════════
#  SECTORS
# ═══════════════════════════════════════════════════════════════
# SECTORS (sector label -> company ids) is built from the APEX-20 roster in apex20.py.
# It drives the same-direction sector ripple.

# ═══════════════════════════════════════════════════════════════
#  VOLATILITY PROFILES  (min_drift, max_drift, down_bias)
#  down_bias > 0.5  →  stock drifts down more often (higher risk)
#  These are the company's baseline "character" — actual moves also scale
#  with the stock's current price (see PRICE_VOL_REFERENCE below), so an
#  expensive stock swings harder in rupee terms than these fractions alone
#  would suggest.
# ═══════════════════════════════════════════════════════════════
COMPANY_VOL = {
    **_STOCK_VOL,   # the 20 listed companies — profiles live in apex20.py next to each company
    # ── Safe-route investments: tiny moves, biased toward steady positive drift ──
    "debtfund":     (0.001, 0.004, 0.35),
    "balancedfund": (0.003, 0.012, 0.42),
}

# Reference price used to scale volatility by how expensive a stock currently
# is — pricier stocks get a proportionally bigger swing, not just a bigger
# rupee number attached to the same percentage move. Applied as a multiplier
# in the price engine: (current_price / PRICE_VOL_REFERENCE), clamped.
PRICE_VOL_REFERENCE   = 350
PRICE_VOL_MULT_MIN    = 0.75
PRICE_VOL_MULT_MAX    = 1.85

# FY26 dividend/share (₹), straight from the updated company list — used by the
# automatic Round 3 / Round 4 dividend events (chaos schedule, see start_round).
# (DIVIDEND_PER_SHARE is imported from apex20.py — only companies with a dividend above zero appear in it.)

# Price floors per company (20% of starting price — prevents absurd crashes)
# Price floors per company (20% of starting price — prevents absurd crashes)
PRICE_FLOORS = {
    **_STOCK_FLOORS,
    "debtfund": 90, "balancedfund": 110,
}

# ═══════════════════════════════════════════════════════════════
#  COMPANIES — built from apex20.py.
#    BASE_COMPANIES : the 18 companies that trade from Round 1.
#    IPO_COMPANIES  : the 2 companies (different sectors) held back until the IPO Drop event.
# ═══════════════════════════════════════════════════════════════

# ═══════════════════════════════════════════════════════════════
#  SAFE-ROUTE INVESTMENTS — mutual funds (steady, low-volatility).
# ═══════════════════════════════════════════════════════════════
FUNDS = {
    "debtfund": {
        "name": "Bharat Debt Fund", "ticker": "BDF", "sector": "Mutual Fund", "risk": "Very Low", "price": 100,
        "is_fund": True,
        "bio": (
            "A plain, boring debt fund holding government bonds and top-rated corporate paper. "
            "It will not make you rich. It will also not ruin you. If you just want somewhere to park "
            "cash between bets without watching it evaporate, this is it."
        ),
        "trait": "The parking lot for your cash.",
    },
    "balancedfund": {
        "name": "Balanced Growth Fund", "ticker": "BGF", "sector": "Mutual Fund", "risk": "Low", "price": 150,
        "is_fund": True,
        "bio": (
            "A diversified fund split across large, stable companies and a small slice of higher-growth "
            "names. Steadier than picking individual stocks, with enough real growth that it isn't just "
            "a savings account with extra steps."
        ),
        "trait": "Diversified. Deliberately unexciting.",
    },
}

# ═══════════════════════════════════════════════════════════════
#  DATABASE
# ═══════════════════════════════════════════════════════════════
async def init_db():
    async with aiosqlite.connect(DB_PATH, timeout=5.0) as db:
        # WAL lets readers and a writer work concurrently instead of the whole
        # file locking on every write; busy_timeout makes any remaining brief
        # contention retry automatically instead of raising immediately. Both
        # matter a lot more now that price ticks fire every 4s under load.
        await db.execute("PRAGMA journal_mode=WAL;")
        await db.execute("PRAGMA busy_timeout=5000;")
        await db.execute("""
            CREATE TABLE IF NOT EXISTS game (
                key   TEXT PRIMARY KEY,
                value TEXT NOT NULL
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS players (
                code             TEXT PRIMARY KEY,
                name             TEXT,
                cash             REAL    DEFAULT 0,
                holdings         TEXT    DEFAULT '{}',
                loans            TEXT    DEFAULT '{}',
                frozen           INTEGER DEFAULT 0,
                avg_cost         TEXT    DEFAULT '{}',
                bm_log           TEXT    DEFAULT '[]',
                stop_losses      TEXT    DEFAULT '{}',
                insurance        TEXT    DEFAULT '{}',
                rate_locks       TEXT    DEFAULT '{}',
                realized_pnl_round REAL  DEFAULT 0,
                realized_pnl_total REAL  DEFAULT 0,
                stt_accrued_round  REAL  DEFAULT 0,
                trades_this_round  INTEGER DEFAULT 0,
                net_worth_at_round_start REAL DEFAULT 0,
                bankruptcy_count INTEGER DEFAULT 0,
                bankrupt_until_round INTEGER DEFAULT 0
            )
        """)
        # Migration for DBs created by an older version of this schema — add any
        # column that doesn't exist yet. Harmless no-op on a fresh database.
        existing_cols = {row[1] for row in await (await db.execute("PRAGMA table_info(players)")).fetchall()}
        migrations = [
            ("stop_losses",              "TEXT DEFAULT '{}'"),
            ("rate_locks",               "TEXT DEFAULT '{}'"),
            ("realized_pnl_round",       "REAL DEFAULT 0"),
            ("realized_pnl_total",       "REAL DEFAULT 0"),
            ("stt_accrued_round",        "REAL DEFAULT 0"),
            ("trades_this_round",        "INTEGER DEFAULT 0"),
            ("net_worth_at_round_start", "REAL DEFAULT 0"),
            ("bankruptcy_count",         "INTEGER DEFAULT 0"),
            ("bankrupt_until_round",     "INTEGER DEFAULT 0"),
        ]
        for col, decl in migrations:
            if col not in existing_cols:
                await db.execute(f"ALTER TABLE players ADD COLUMN {col} {decl}")
        await db.execute("""
            CREATE TABLE IF NOT EXISTS codes (
                code TEXT PRIMARY KEY
            )
        """)
        await db.commit()
        row = await (await db.execute("SELECT value FROM game WHERE key='state'")).fetchone()
        if not row:
            await _write_state(db, _default_state())
            await db.commit()


async def _write_state(db, state: dict):
    await db.execute(
        "INSERT OR REPLACE INTO game (key, value) VALUES ('state', ?)",
        (json.dumps(state),),
    )


async def read_state() -> dict:
    async with aiosqlite.connect(DB_PATH, timeout=5.0) as db:
        row = await (await db.execute("SELECT value FROM game WHERE key='state'")).fetchone()
        if row:
            return json.loads(row[0])
    return _default_state()


async def write_state(state: dict):
    async with aiosqlite.connect(DB_PATH, timeout=5.0) as db:
        await _write_state(db, state)
        await db.commit()


def _default_state() -> dict:
    companies = {k: {**v, "prev_price": v["price"], "target_price": v["price"]} for k, v in BASE_COMPANIES.items()}
    companies.update({k: {**v, "prev_price": v["price"], "target_price": v["price"]} for k, v in FUNDS.items()})
    return {
        "phase":              "lobby",
        "round":              0,
        "round_end_time":     None,
        "break_end_time":     None,
        "break_duration":     BREAK_DURATION,
        "companies":          companies,
        "ipo_listed":         [],          # the 2 held-back companies join this list at the IPO Drop event
        "news":               [],
        "news_used":          [],
        "acquisition_pair":   None,
        "chaos_done":         [],          # chaos events already fired this game
        "round_marks":        [],          # [[unix_ts, round_number], ...] — chart round dividers
        "truth_log":          [],          # Truth-or-False items with their real answer (host only)
        # Price history: {cid: [price_r1, price_r2, ...]}
        "price_history":      {k: [v["price"]] for k, v in BASE_COMPANIES.items()},
    }


# ═══════════════════════════════════════════════════════════════
#  PLAYER HELPERS
# ═══════════════════════════════════════════════════════════════
async def all_codes():
    async with aiosqlite.connect(DB_PATH, timeout=5.0) as db:
        rows = await (await db.execute("SELECT code FROM codes")).fetchall()
    return {r[0] for r in rows}


async def all_players():
    async with aiosqlite.connect(DB_PATH, timeout=5.0) as db:
        db.row_factory = aiosqlite.Row
        rows = await (await db.execute("SELECT * FROM players")).fetchall()
    return [_row_to_player(r) for r in rows]


async def get_player(code: str) -> Optional[dict]:
    async with aiosqlite.connect(DB_PATH, timeout=5.0) as db:
        db.row_factory = aiosqlite.Row
        row = await (await db.execute("SELECT * FROM players WHERE code=?", (code,))).fetchone()
        if not row:
            return None
        return _row_to_player(row)


def _row_to_player(row) -> dict:
    row_keys = row.keys()
    def _col(name, default):
        return row[name] if name in row_keys and row[name] is not None else default
    return {
        "code":     row["code"],
        "name":     row["name"],
        "cash":     row["cash"],
        "holdings": json.loads(row["holdings"]),
        "loans":    json.loads(row["loans"]),
        "avg_cost": json.loads(row["avg_cost"]),
        "stop_losses":              json.loads(_col("stop_losses", "{}")),
        "rate_locks":               json.loads(_col("rate_locks", "{}")),
        "realized_pnl_round":       _col("realized_pnl_round", 0) or 0,
        "realized_pnl_total":       _col("realized_pnl_total", 0) or 0,
        "stt_accrued_round":        _col("stt_accrued_round", 0) or 0,
        "trades_this_round":        _col("trades_this_round", 0) or 0,
        "net_worth_at_round_start": _col("net_worth_at_round_start", 0) or 0,
        "bankruptcy_count":         _col("bankruptcy_count", 0) or 0,
        "bankrupt_until_round":     _col("bankrupt_until_round", 0) or 0,
    }


async def save_player(p: dict):
    async with aiosqlite.connect(DB_PATH, timeout=5.0) as db:
        await db.execute(
            """INSERT OR REPLACE INTO players
               (code,name,cash,holdings,loans,avg_cost,
                stop_losses,rate_locks,realized_pnl_round,realized_pnl_total,
                stt_accrued_round,trades_this_round,net_worth_at_round_start,
                bankruptcy_count,bankrupt_until_round)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                p["code"], p.get("name"), p["cash"],
                json.dumps(p["holdings"]),
                json.dumps(p.get("loans", {})),
                json.dumps(p.get("avg_cost", {})),
                json.dumps(p.get("stop_losses", {})),
                json.dumps(p.get("rate_locks", {})),
                p.get("realized_pnl_round", 0) or 0,
                p.get("realized_pnl_total", 0) or 0,
                p.get("stt_accrued_round", 0) or 0,
                p.get("trades_this_round", 0) or 0,
                p.get("net_worth_at_round_start", 0) or 0,
                p.get("bankruptcy_count", 0) or 0,
                p.get("bankrupt_until_round", 0) or 0,
            ),
        )
        await db.commit()


def player_loans_total(p: dict) -> float:
    return sum(p.get("loans", {}).values())


def locked_rounds_left(p: dict, state: dict) -> int:
    """How many rounds (counting the current one) this player is still locked out for after a bankruptcy."""
    return max(0, int(p.get("bankrupt_until_round", 0) or 0) - int(state.get("round", 0)) + 1)


def is_locked_out(p: dict, state: dict) -> bool:
    return int(state.get("round", 0)) <= int(p.get("bankrupt_until_round", 0) or 0)


def player_view(p: dict, state: dict) -> dict:
    companies   = state["companies"]
    portfolio   = {}
    for cid, qty in p["holdings"].items():
        if qty > 0 and cid in companies:
            c    = companies[cid]
            avg  = p.get("avg_cost", {}).get(cid, c["price"])
            price = c["price"]
            val  = qty * price
            portfolio[cid] = {
                "qty":   qty,
                "avg":   round(avg),
                "price": price,
                "value": val,
                "pnl":   round(val - qty * avg),
            }
    port_value  = sum(h["value"] for h in portfolio.values())
    total_loans = player_loans_total(p)
    net_worth   = p["cash"] + port_value - total_loans
    return {
        "cash":         round(p["cash"]),
        "loans":        p.get("loans", {}),
        "total_loan":   round(total_loans),
        "net_worth":    round(net_worth),
        "portfolio":    portfolio,
        "portfolio_value":    round(port_value),
        "realized_pnl_round": round(p.get("realized_pnl_round", 0)),
        "realized_pnl_total": round(p.get("realized_pnl_total", 0)),
        "stt_accrued_round":  round(p.get("stt_accrued_round", 0)),
        "stop_losses":  p.get("stop_losses", {}),
        "locked_rounds_left": locked_rounds_left(p, state),   # >0 = bankrupt, sitting out
    }


def leaderboard(players: list, state: dict) -> list:
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





# ═══════════════════════════════════════════════════════════════
#  PRICE ENGINE
# ═══════════════════════════════════════════════════════════════
def fluctuate_prices(state: dict, news: list) -> None:
    """
    Apply one price tick. Called at round start and by the drift loop.

    Realism improvements vs original:
      - Per-company price floors (no stock below 20% of IPO price)
      - Sector ripple only goes in the SAME direction (contagion),
        not opposite (that was backwards)
      - Acquisition correlation is bi-directional (both legs move)
      - News strength is applied exactly (no double-random on verified)
      - Unverified news: 40% chance it lands, 60% chance it's noise
    """
    companies = state["companies"]
    acq_pair  = state.get("acquisition_pair")
    moved: dict[str, float] = {}

    for cid, c in companies.items():
        c["prev_price"] = c["price"]
        lo, hi, bias = vol_for(state, cid)
        mag       = random.uniform(lo, hi)
        direction = 1 if random.random() > bias else -1
        change    = direction * mag

        # ── News impact ──────────────────────────────────────────────
        for n in news:
            aff = n["affects"]
            if aff == cid:
                if n.get("real", True):
                    # Verified or real-unverified: apply stated strength
                    change += n["direction"] * n.get("strength", 0.10)
                else:
                    # False rumour: 40% chance of small random noise
                    if random.random() < 0.4:
                        change += n["direction"] * random.uniform(0.01, 0.03)
            elif aff.startswith("sector:"):
                sector = aff.split(":", 1)[1]
                if c.get("sector") == sector and n.get("real", True):
                    # Sector news affects all peers at 70% strength
                    change += n["direction"] * n.get("strength", 0.07) * 0.70

        # ── Acquisition pair: correlated movement ────────────────────
        # Both legs move together (acquirer up, target up — M&A premium)
        if acq_pair and cid in acq_pair:
            partner = acq_pair[1] if cid == acq_pair[0] else acq_pair[0]
            if partner in moved:
                # Blend: 60% own movement, 40% partner's
                change = 0.60 * change + 0.40 * moved[partner]

        floor = PRICE_FLOORS.get(cid, 10)
        c["price"]        = max(floor, round(c["price"] * (1 + change)))
        c["target_price"] = c["price"]
        moved[cid] = change

    # ── Sector ripple: large move drags peers in same direction ──────
    # Models real-world sector contagion (e.g. a tech sell-off pulls all tech)
    for sector, members in SECTORS.items():
        for cid in members:
            if cid not in companies or cid not in moved:
                continue
            pct = moved[cid]
            if abs(pct) > 0.06:  # only ripple on significant moves
                for peer in members:
                    if peer == cid or peer not in companies:
                        continue
                    # Peer moves in SAME direction at 30–50% magnitude
                    ripple = pct * random.uniform(0.30, 0.50)
                    floor  = PRICE_FLOORS.get(peer, 10)
                    companies[peer]["price"] = max(
                        floor,
                        round(companies[peer]["price"] * (1 + ripple)),
                    )
                    companies[peer]["target_price"] = companies[peer]["price"]


# ═══════════════════════════════════════════════════════════════
#  PASSIVE DRIFT LOOP
# ═══════════════════════════════════════════════════════════════
# ═══════════════════════════════════════════════════════════════
#  PRICE ENGINE — two-tier: a "target" recalculated every 20s using the same
#  volatility/news-driven factors as before, and the REAL tradable price
#  ticking every 4s toward/around that target. The 4s number is what trades
#  actually execute at — this isn't cosmetic, it's the authoritative price.
# ═══════════════════════════════════════════════════════════════
TARGET_INTERVAL = 20   # seconds — how often the underlying "fair value" moves
TICK_INTERVAL   = 4    # seconds — how often the tradable price re-samples around it

# Serializes the background price loops (and other host-triggered state writes)
# against each other so a target recalc, a tick, a news injection, and a chaos
# event can never clobber one another's write. Player trades/loans/bets (inside
# the main ws_player loop) are not yet covered by this lock — a larger refactor
# for another pass — but the much-higher-frequency system writes below are.
STATE_LOCK = asyncio.Lock()

def vol_for(state: dict, cid: str):
    """(min_move, max_move, down_bias) for a company right now. During the Acquisition Rumour event
    both linked companies are bumped up to the High profile until the round ends."""
    lo, hi, bias = COMPANY_VOL.get(cid, (0.02, 0.06, 0.45))
    pair = state.get("acquisition_pair")
    if pair and cid in pair:
        lo, hi = max(lo, HIGH_VOL[0]), max(hi, HIGH_VOL[1])
    return lo, hi, bias


# ── Chart history: server-side price series (one point per 4 s tick). Kept in memory — a server
#    restart clears the chart, never the prices. Sent to a player when they (re)connect. ──
TICK_HISTORY: Dict[str, list] = {}
TICK_HISTORY_MAX = 2400          # ≈ 2h40m at one point per 4 s — more than a whole 6-round game


def record_history(companies: dict, ts: float = None) -> None:
    ts = round(ts or time.time(), 1)
    for cid, c in companies.items():
        h = TICK_HISTORY.setdefault(cid, [])
        if h and ts - h[-1][0] < 1.0:
            h[-1] = [ts, c["price"]]
            continue
        h.append([ts, c["price"]])
        if len(h) > TICK_HISTORY_MAX:
            del h[: len(h) - TICK_HISTORY_MAX]


def price_vol_mult(price: float) -> float:
    """Expensive stocks swing harder in absolute terms — scale the base
    volatility magnitude by how far the current price sits above/below
    PRICE_VOL_REFERENCE, clamped to [PRICE_VOL_MULT_MIN, PRICE_VOL_MULT_MAX]."""
    mult = price / PRICE_VOL_REFERENCE
    return max(PRICE_VOL_MULT_MIN, min(PRICE_VOL_MULT_MAX, mult))

ELASTICITY_FACTOR     = 0.015    # base price-impact scaling per trade
ELASTICITY_REF_VALUE  = 150_000  # ₹1.5L traded ≈ one "unit" of market impact
ELASTICITY_MAX_IMPACT = 0.05     # cap: a single trade can move price at most 5%

def trade_impact(state: dict, cid: str, qty: int, price: float) -> float:
    """Fractional price impact of a trade of this size (0 for funds/ETFs)."""
    c = state["companies"].get(cid)
    if not c or c.get("is_fund"):
        return 0.0
    return min(ELASTICITY_MAX_IMPACT, ELASTICITY_FACTOR * (qty * price / ELASTICITY_REF_VALUE))


def apply_trade_elasticity(state: dict, cid: str, qty: int, price: float, is_buy: bool) -> None:
    """A buy nudges the stock's price up, a sell nudges it down — bigger
    trades (and higher trade values) move it more, up to a per-trade cap.
    Mutates state["companies"][cid] in place; caller is responsible for
    write_state() afterwards."""
    c = state["companies"].get(cid)
    if not c or c.get("is_fund"):
        return
    trade_value = qty * price
    impact = min(ELASTICITY_MAX_IMPACT, ELASTICITY_FACTOR * (trade_value / ELASTICITY_REF_VALUE))
    if impact <= 0:
        return
    direction  = 1 if is_buy else -1
    floor      = PRICE_FLOORS.get(cid, 10)
    new_price  = max(floor, round(c["price"] * (1 + direction * impact)))
    c["price"]        = new_price
    c["target_price"] = new_price








AMBIENT_NEWS_GAP      = 150    # seconds between auto-generated 'explainer' headlines
AMBIENT_NEWS_MIN_MAG  = 0.012  # ...and only for a queued move at least this big (1.2%)


def link_pending_moves(pending: dict, pair) -> None:
    """Acquisition Rumour: the two linked companies always move in the SAME direction, by a similar
    amount (each leg is the pair's average size, give or take 15%)."""
    if not pair or pair[0] not in pending or pair[1] not in pending:
        return
    a, b = pending[pair[0]], pending[pair[1]]
    sa, sb = a["direc"] * a["mag"], b["direc"] * b["mag"]
    direc  = 1 if (sa + sb) >= 0 else -1
    base   = 0.5 * (abs(sa) + abs(sb))
    for leg in (a, b):
        leg["direc"] = direc
        leg["mag"]   = base * random.uniform(0.85, 1.15)


async def price_target_loop():
    """Every 20s, two things happen in the same tick, one cycle apart:
      1) APPLY the move that was computed and announced last cycle — so the
         price change lands exactly when its headline said it would.
      2) COMPUTE the next cycle's move and announce ITS headline right now,
         ~20s ahead of when it will actually land.
    This gives every price move a headline that shows up first, instead of
    news and price changes arriving at the same instant (or not lining up
    at all). state['pending_moves'] carries the queued-but-not-yet-applied
    moves across the gap between cycles."""
    await asyncio.sleep(15)
    while True:
        await asyncio.sleep(TARGET_INTERVAL)
        try:
            headline_n = None
            async with STATE_LOCK:
                state = await read_state()
                if state.get("phase") != "trading":
                    continue
                companies = state["companies"]

                # ── Stage 1: apply whatever was queued last cycle ──────────
                pending = state.get("pending_moves", {})
                for cid, mv in pending.items():
                    c = companies.get(cid)
                    if not c or c.get("is_fund"):
                        continue
                    floor = PRICE_FLOORS.get(cid, 10)
                    base  = c.get("target_price", c["price"])
                    c["target_price"] = max(floor, round(base * (1 + mv["direc"] * mv["mag"])))

                # ── Stage 2: compute next cycle's moves, queue them ────────
                new_pending = {}
                for cid, c in companies.items():
                    if c.get("is_fund"):
                        continue
                    lo, hi, bias = vol_for(state, cid)
                    mag   = random.uniform(lo * 0.5, hi * 0.65) * price_vol_mult(c["price"])
                    direc = 1 if random.random() > bias else -1
                    new_pending[cid] = {"direc": direc, "mag": mag}
                # Acquisition Rumour: the two linked companies share most of their queued move.
                link_pending_moves(new_pending, state.get("acquisition_pair"))
                state["pending_moves"] = new_pending

                # One headline now, for the single biggest of the QUEUED
                # (not-yet-applied) moves — this is the advance-warning story.
                # Throttled: presets now match the real companies, so an unthrottled headline every
                # 20s cycle would bury the round's real news under ~60 "verified" items per round.
                # At most one ambient headline every AMBIENT_NEWS_GAP seconds, and only for a move
                # big enough to be worth a headline.
                ambient_ok = (time.time() - state.get("last_ambient_news_ts", 0) >= AMBIENT_NEWS_GAP)
                if new_pending and ambient_ok and max(v["mag"] for v in new_pending.values()) >= AMBIENT_NEWS_MIN_MAG:
                    state["last_ambient_news_ts"] = time.time()
                    top_cid       = max(new_pending, key=lambda k: new_pending[k]["mag"])
                    mv            = new_pending[top_cid]
                    dir_key       = "up" if mv["direc"] > 0 else "down"
                    text          = pick_preset(state, top_cid, dir_key)
                    if text:
                        headline_n = make_news_item(text, top_cid, mv["direc"], real=True, src="news", state=state)
                        state["news"].append(headline_n)
                await write_state(state)
            if headline_n:
                await manager.broadcast_all({"type": "news", **headline_n})
                players = await all_players()
                board   = leaderboard(players, state)
                await manager.broadcast_hosts({"type": "state_update", "state": state, "board": board})
        except Exception as e:
            print(f"[price_target_loop] iteration failed, will retry next cycle: {e}")

async def price_tick_loop():
    """Every 4s: the REAL tradable price re-samples around the current target.
    Small, fast, always-on noise — this is what a buy/sell actually executes
    at, so it has to be real and server-authoritative, not just a visual."""
    await asyncio.sleep(17)
    while True:
        await asyncio.sleep(TICK_INTERVAL)
        try:
            async with STATE_LOCK:
                state = await read_state()
                if state.get("phase") != "trading":
                    continue
                companies = state["companies"]
                for cid, c in companies.items():
                    target = c.get("target_price", c["price"])
                    lo, hi, _ = vol_for(state, cid)
                    jitter = (random.uniform(-lo * 0.9, lo * 0.9) or random.uniform(-0.01, 0.01)) * price_vol_mult(c["price"])
                    floor  = PRICE_FLOORS.get(cid, 10)
                    c["prev_price"] = c["price"]
                    c["price"]      = max(floor, round(target * (1 + jitter)))
                await write_state(state)
            # Broadcast outside the lock — sending to N sockets shouldn't hold up
            # other writers (news injection, chaos events, the next tick, etc.)
            players = await all_players()
            # Check every player's stop-loss orders against the prices that just landed.
            # Fires as a plain market sell — no protection against slippage, same as
            # if they'd hit sell manually the instant it crossed the trigger.
            notify_list = []
            for p in players:
                stops = p.get("stop_losses") or {}
                if not stops:
                    continue
                fired = []
                for cid, trigger in list(stops.items()):
                    c     = companies.get(cid)
                    owned = p.get("holdings", {}).get(cid, 0)
                    if not c or owned < 1:
                        stops.pop(cid, None)  # no longer held — stale order, drop it
                        continue
                    if c["price"] <= trigger:
                        price = c["price"]
                        p["cash"]              += price * owned
                        p["holdings"][cid]       = 0
                        p["trades_this_round"]   = p.get("trades_this_round", 0) + 1
                        realized                 = (price - p.get("avg_cost", {}).get(cid, price)) * owned
                        p["realized_pnl_round"]  = p.get("realized_pnl_round", 0) + realized
                        p["stt_accrued_round"]   = p.get("stt_accrued_round", 0) + round(price * owned * STT_RATE)
                        stops.pop(cid, None)
                        fired.append((c["name"], owned, price))
                if fired:
                    p["stop_losses"] = stops
                    await save_player(p)
                    lines = "; ".join(f"{q}× {n} @ ₹{pr:,}" for n, q, pr in fired)
                    notify_list.append((p["code"], f"🛑 Stop-loss triggered: {lines}"))
            board = leaderboard(players, state)
            record_history(companies)
            pb = {"type": "prices_bulk", "ts": time.time(),
                  "prices": {k: v["price"] for k, v in companies.items()}}
            await manager.broadcast_all(pb)                       # players: prices only — never rankings
            await manager.broadcast_hosts({**pb, "board": board})  # host console + projector board
            for code_, msg_ in notify_list:
                fresh_p = await get_player(code_)
                if fresh_p:
                    await manager.send_player(code_, {
                        "type": "player_update", "player": player_view(fresh_p, state), "msg": msg_,
                    })
        except Exception as e:
            print(f"[price_tick_loop] iteration failed, will retry next cycle: {e}")


# ═══════════════════════════════════════════════════════════════
#  NEWS PICKER
# ═══════════════════════════════════════════════════════════════
def plot_group_of(text: str):
    """Which storyline (if any) a headline belongs to — see PLOT_GROUPS in news_presets.py."""
    for g, needles in PLOT_GROUPS.items():
        if any(nd in text for nd in needles):
            return g
    return None


def pick_preset(state: dict, cid: str, dir_key: str):
    """Pick a preset headline for (stock, direction), skipping any storyline whose outcome
    has already been reported this game, and marking the chosen one's storyline as spent.
    Returns None when nothing suitable is left."""
    options = NEWS_PRESETS.get(cid, {}).get(dir_key, [])
    spent   = set(state.get("used_plot_groups", []))
    open_   = [o for o in options if plot_group_of(o) not in spent]
    if not open_:
        return None
    used  = set(state.get("news_used", []))
    fresh = [o for o in open_ if o not in used] or open_
    text  = random.choice(fresh)
    g = plot_group_of(text)
    if g:
        state.setdefault("used_plot_groups", []).append(g)
    state.setdefault("news_used", []).append(text)
    return text


def make_news_item(text: str, affects: str, direction: int, real: bool = True, src: str = "news",
                   strength: float = None, state: dict = None) -> dict:
    """One news item. Players only ever see id / text / affects / direction / ts / round —
    `real`, `strength` and `src` are host-only (see _HIDDEN_NEWS_KEYS)."""
    n = {
        "id":        uuid.uuid4().hex[:8],
        "text":      text,
        "affects":   affects,
        "direction": direction,
        "real":      real,
        "src":       src,                     # "news" | "rumour"
        "ts":        time.time(),
        "round":     (state or {}).get("round", 0),
    }
    if strength is not None:
        n["strength"] = strength
    if state is not None:
        state.setdefault("news", []).append(n)
    return n


def _pool_ok(n: dict, state: dict, used: set, spent_groups: set, listed: set) -> bool:
    if n["text"] in used:
        return False
    if plot_group_of(n["text"]) in spent_groups:
        return False                           # that storyline already has an outcome this game
    if n["affects"] in IPO_COMPANIES and n["affects"] not in listed:
        return False                           # held-back companies get no news until they list
    return True


def pick_news(state: dict, count: int = 3) -> list:
    """Round-start news. Everything in NEWS_POOL is TRUE and moves the price as stated."""
    listed = set(state.get("ipo_listed", []))
    used   = set(state.get("news_used", []))
    spent  = set(state.get("used_plot_groups", []))
    pool   = [n for n in NEWS_POOL if _pool_ok(n, state, used, spent, listed)]
    if not pool:
        return []
    chosen_raw = random.sample(pool, min(count, len(pool)))
    chosen = []
    for n in chosen_raw:
        item = make_news_item(n["text"], n["affects"], n["direction"], real=True, src=n.get("src", "news"),
                              strength=n.get("strength"), state=None)
        item["round"] = state.get("round", 0)
        chosen.append(item)
    state["news_used"] = list(used) + [n["text"] for n in chosen_raw]
    seen_now = {g for g in (plot_group_of(n["text"]) for n in chosen_raw) if g}
    if seen_now:
        state["used_plot_groups"] = list(spent | seen_now)
    return chosen


def pick_truth_pair(state: dict) -> list:
    """Truth-or-False drop: one TRUE item (real news or a correct rumour) and one FALSE rumour about a
    different company, returned in random order. Only the host ever learns which is which."""
    listed = set(state.get("ipo_listed", []))
    used   = set(state.get("news_used", []))
    spent  = set(state.get("used_plot_groups", []))
    true_pool  = [n for n in NEWS_POOL if _pool_ok(n, state, used, spent, listed)]
    false_pool = [n for n in FALSE_RUMOURS if _pool_ok(n, state, used, spent, listed)]
    if not true_pool or not false_pool:
        return []
    t = random.choice(true_pool)
    f = random.choice([n for n in false_pool if n["affects"] != t["affects"]] or false_pool)
    items = [
        make_news_item(t["text"], t["affects"], t["direction"], real=True,  src=t.get("src", "news"), strength=t.get("strength")),
        make_news_item(f["text"], f["affects"], f["direction"], real=False, src="rumour",             strength=f.get("strength")),
    ]
    for it in items:
        it["round"] = state.get("round", 0)
    state["news_used"] = list(used) + [t["text"], f["text"]]
    g = plot_group_of(t["text"])
    if g:
        state["used_plot_groups"] = list(spent | {g})
    random.shuffle(items)
    return items


def apply_news_now(state: dict, n: dict) -> None:
    """Move the price immediately for one news item (host injection, Truth-or-False drops).
    True items move it by their full strength; a false rumour only has a 40% chance of a small blip."""
    c = state["companies"].get(n["affects"])
    if not c or state.get("phase") != "trading":
        return
    if n.get("real", True):
        move = n.get("strength", 0.10)
    else:
        move = random.uniform(0.01, 0.03) if random.random() < 0.4 else 0.0
    if not move:
        return
    c["prev_price"]   = c["price"]
    floor             = PRICE_FLOORS.get(n["affects"], 10)
    new_price         = max(floor, round(c["price"] * (1 + n["direction"] * move)))
    c["price"]        = new_price
    c["target_price"] = new_price     # move the "fair value" too, so the next 4s tick samples around the news price





# ═══════════════════════════════════════════════════════════════
#  CONNECTION MANAGER
# ═══════════════════════════════════════════════════════════════
_HIDDEN_NEWS_KEYS   = ("real", "strength", "src")     # would reveal whether an item is true / how big the move is
_HIDDEN_COMPANY_KEYS = ("target_price", "_baseline_avg", "risk")  # the hidden fair value the price is steered toward


def public_news(n: dict) -> dict:
    return {k: v for k, v in n.items() if k not in _HIDDEN_NEWS_KEYS}


def public_companies(companies: dict) -> dict:
    return {cid: {k: v for k, v in c.items() if k not in _HIDDEN_COMPANY_KEYS} for cid, c in companies.items()}


def _player_safe(msg: dict) -> dict:
    """Strip host-only fields from anything sent to a player. Applied centrally so no individual
    broadcast site can forget it. Players never receive rankings, risk labels or truth flags."""
    t = msg.get("type")
    if t == "news":
        return public_news(msg)
    out = {k: v for k, v in msg.items() if k not in ("board", "players")}     # rankings are host-only
    if t == "init":
        if isinstance(out.get("news"), list):
            out["news"] = [public_news(n) for n in out["news"]]
        if isinstance(out.get("market"), dict):
            out["market"] = public_companies(out["market"])
    return out


class ConnectionManager:
    def __init__(self):
        self.players: Dict[str, WebSocket] = {}
        self.hosts:   list = []     # authenticated host consoles — get EVERYTHING
        self.viewers: list = []     # public big-screen leaderboard — get round/phase/timer + ranking only

    async def connect_player(self, code: str, ws: WebSocket):
        await ws.accept()
        self.players[code] = ws

    def disconnect_player(self, code: str):
        self.players.pop(code, None)

    async def connect_host(self, ws: WebSocket, admin: bool = True):
        await ws.accept()
        (self.hosts if admin else self.viewers).append(ws)

    def disconnect_host(self, ws: WebSocket):
        if ws in self.hosts:
            self.hosts.remove(ws)
        if ws in self.viewers:
            self.viewers.remove(ws)

    async def send_player(self, code: str, msg: dict):
        ws = self.players.get(code)
        if ws:
            try:
                await ws.send_text(json.dumps(_player_safe(msg)))
            except Exception:
                self.disconnect_player(code)

    async def broadcast_all(self, msg: dict):
        dead = []
        safe = _player_safe(msg)
        for code, ws in list(self.players.items()):
            try:
                await ws.send_text(json.dumps(safe))
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
        if msg.get("type") == "prices_bulk" and self.viewers and msg.get("board") is not None:
            live = json.dumps({"type": "board_update", "board": msg["board"]})
            gone = []
            for ws in list(self.viewers):
                try:
                    await ws.send_text(live)
                except Exception:
                    gone.append(ws)
            for ws in gone:
                self.disconnect_host(ws)
        if msg.get("type") == "state_update" and self.viewers:
            st = msg.get("state") or {}
            pub = json.dumps({
                "type":  "state_update",
                "state": {k: st.get(k) for k in ("round", "phase", "round_end_time", "break_end_time")},
                "board": msg.get("board", []),
            })
            gone = []
            for ws in list(self.viewers):
                try:
                    await ws.send_text(pub)
                except Exception:
                    gone.append(ws)
            for ws in gone:
                self.disconnect_host(ws)


manager = ConnectionManager()


# ═══════════════════════════════════════════════════════════════
#  LIFESPAN
# ═══════════════════════════════════════════════════════════════
@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    if HOST_PASSWORD == "Ich_liebe_Siya":
        print("\n" + "!" * 70 +
              "\n  WARNING: the host password is still the built-in default from the source code."
              "\n  Anyone who has seen the code can run your game. Set a private one before going"
              "\n  live, e.g.   HOST_PASSWORD=your-own-password python main.py"
              "\n" + "!" * 70 + "\n")
    # Databases created before the ₹1.5L starting cash change hold players with ₹0. If the game is
    # still in the lobby nobody can have traded yet, so bring them up to the current starting cash.
    try:
        st = await read_state()
        if st.get("round", 0) == 0 and st.get("phase") == "lobby":
            for pl in await all_players():
                if pl["name"] and pl["cash"] == 0 and not pl["holdings"] and not pl.get("loans"):
                    pl["cash"] = STARTING_CASH
                    pl["net_worth_at_round_start"] = STARTING_CASH
                    await save_player(pl)
    except Exception as e:
        print(f"[startup] starting-cash top-up skipped: {e}")
    asyncio.create_task(price_target_loop())
    asyncio.create_task(price_tick_loop())
    yield


app = FastAPI(lifespan=lifespan)
BASE_DIR = Path(__file__).parent

# Mount static files (sounds, music) — create the folder if it doesn't exist
STATIC_DIR = BASE_DIR / "static"
STATIC_DIR.mkdir(exist_ok=True)
(STATIC_DIR / "sounds").mkdir(exist_ok=True)
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


# ═══════════════════════════════════════════════════════════════
#  HTML ROUTES
# ═══════════════════════════════════════════════════════════════
@app.get("/", response_class=HTMLResponse)
async def serve_team():
    p = BASE_DIR / "team.html"
    return HTMLResponse(p.read_text(encoding="utf-8") if p.exists() else "<h1>team.html not found</h1>")


@app.get("/host", response_class=HTMLResponse)
async def serve_host():
    p = BASE_DIR / "host.html"
    return HTMLResponse(p.read_text(encoding="utf-8") if p.exists() else "<h1>host.html not found</h1>")


@app.get("/board", response_class=HTMLResponse)
async def serve_board():
    p = BASE_DIR / "board.html"
    return HTMLResponse(p.read_text(encoding="utf-8") if p.exists() else "<h1>board.html not found</h1>")


# ═══════════════════════════════════════════════════════════════
#  REST: CODE MANAGEMENT
# ═══════════════════════════════════════════════════════════════
@app.post("/api/codes/generate")
async def generate_codes(pw: str, count: int = 10):
    # SECURITY FIX: this endpoint used to have NO password check at all — anyone
    # who found the URL could mint themselves a brand-new valid join code and
    # get into the game without the host ever handing one out. That's almost
    # certainly the "I could join even with a wrong code" bug — it wasn't a
    # wrong code being accepted, it was players generating their own right one.
    if pw != HOST_PASSWORD:
        raise HTTPException(403, "Wrong password")
    # Generate slightly more than needed to account for rare collisions
    candidates = [uuid.uuid4().hex[:6].upper() for _ in range(max(count, 20))]
    async with aiosqlite.connect(DB_PATH, timeout=5.0) as db:
        # Get existing codes to avoid duplicates in this batch
        existing = {r[0] for r in await (await db.execute("SELECT code FROM codes")).fetchall()}
        new_codes = [c for c in candidates if c not in existing][:count]
        if len(new_codes) < count:
            # Fill any remaining slots
            while len(new_codes) < count:
                c = uuid.uuid4().hex[:6].upper()
                if c not in existing and c not in new_codes:
                    new_codes.append(c)
        await db.executemany("INSERT OR IGNORE INTO codes (code) VALUES (?)", [(c,) for c in new_codes])
        await db.commit()
    return {"codes": new_codes, "count": len(new_codes)}


@app.get("/api/host/organiser_notes")
async def organiser_notes(pw: str):
    """Host-only: cross-links + plot hooks from the dossier. Never sent to players."""
    if pw != HOST_PASSWORD:
        raise HTTPException(403, "Wrong password")
    return ORGANISER_NOTES


@app.get("/api/host/dossier")
async def company_dossier(pw: str):
    """Host-only: the full APEX-20 company dossiers (52-week range, FY23-FY26 financials,
    price history, policy and international exposure). Never sent to players."""
    if pw != HOST_PASSWORD:
        raise HTTPException(403, "Wrong password")
    return DOSSIER


@app.get("/api/codes/check")
async def check_code(code: str):
    """Lightweight pre-check the join screen calls BEFORE letting someone past
    the code field — mirrors exactly the same gate ws_player enforces at
    connect time, so a code that passes this will also be accepted there."""
    code = (code or "").strip().upper()
    valid_codes = await all_codes()
    return {"valid": code in valid_codes}


@app.get("/api/codes")
async def list_codes(pw: str):
    if pw != HOST_PASSWORD:
        raise HTTPException(403, "Wrong password")
    codes   = await all_codes()
    players = await all_players()
    used    = {p["code"] for p in players if p["name"]}
    return {"codes": sorted(codes), "used": sorted(used)}


@app.delete("/api/codes/{code}")
async def delete_code(code: str, pw: str):
    if pw != HOST_PASSWORD:
        raise HTTPException(403, "Wrong password")
    # Send kicked message to the player's WS before disconnecting
    ws = manager.players.get(code)
    if ws:
        try:
            await ws.send_text(json.dumps({"type": "kicked", "msg": "Your access code was removed by the host."}))
        except Exception:
            pass
    async with aiosqlite.connect(DB_PATH, timeout=5.0) as db:
        await db.execute("DELETE FROM codes WHERE code=?", (code,))
        await db.execute("DELETE FROM players WHERE code=?", (code,))
        await db.commit()
    manager.disconnect_player(code)
    return {"ok": True}


# ═══════════════════════════════════════════════════════════════
#  REST: STATE / LEADERBOARD
# ═══════════════════════════════════════════════════════════════
@app.get("/api/state")
async def api_state(pw: str):
    if pw != HOST_PASSWORD:
        raise HTTPException(403, "Wrong password")
    state   = await read_state()
    players = await all_players()
    board   = leaderboard(players, state)
    return {
        "state":        state,
        "board":        board,
        "player_count": len([p for p in players if p["name"]]),
    }


@app.get("/api/banks")
async def api_banks():
    return {"banks": BANKS}


@app.get("/api/players")
async def api_players(pw: str):
    if pw != HOST_PASSWORD:
        raise HTTPException(403, "Wrong password")
    state        = await read_state()
    players      = await all_players()
    board        = leaderboard(players, state)
    name_to_code = {p["name"]: p["code"] for p in players if p["name"]}
    return {"players": name_to_code, "board": board}


@app.get("/api/players/detail")
async def api_players_detail(pw: str):
    if pw != HOST_PASSWORD:
        raise HTTPException(403, "Wrong password")
    state   = await read_state()
    players = await all_players()
    result  = []
    for p in players:
        if not p["name"]:
            continue
        pv = player_view(p, state)
        result.append({
            "code":       p["code"],
            "name":       p["name"],
            "cash":       round(p["cash"]),
            "loans":      p.get("loans", {}),
            "total_loan": round(player_loans_total(p)),
            "locked_rounds_left": locked_rounds_left(p, state),
            "net_worth":  pv["net_worth"],
            "portfolio_value": sum(h["value"] for h in pv["portfolio"].values()),
        })
    result.sort(key=lambda x: x["net_worth"], reverse=True)
    return {"players": result}


# ═══════════════════════════════════════════════════════════════
#  REST: PLAYER MANAGEMENT (host)
# ═══════════════════════════════════════════════════════════════
@app.delete("/api/players/{code}")
async def kick_player(code: str, pw: str):
    if pw != HOST_PASSWORD:
        raise HTTPException(403, "Wrong password")
    async with aiosqlite.connect(DB_PATH, timeout=5.0) as db:
        row  = await (await db.execute("SELECT name FROM players WHERE code=?", (code,))).fetchone()
        name = row[0] if row else code
        await db.execute("DELETE FROM players WHERE code=?", (code,))
        await db.execute("DELETE FROM codes   WHERE code=?", (code,))
        await db.commit()
    ws = manager.players.get(code)
    if ws:
        try:
            await ws.send_text(json.dumps({"type": "kicked", "msg": "You have been removed from the game."}))
            await ws.close()
        except Exception:
            pass
    manager.disconnect_player(code)
    state   = await read_state()
    players = await all_players()
    board   = leaderboard(players, state)
    await manager.broadcast_hosts({"type": "player_kicked", "name": name, "code": code, "board": board})
    return {"ok": True, "name": name}


@app.post("/api/reset")
async def api_reset(pw: str):
    """Full game reset — password required."""
    if pw != HOST_PASSWORD:
        raise HTTPException(403, "Wrong password")
    async with STATE_LOCK:
        async with aiosqlite.connect(DB_PATH, timeout=5.0) as db:
            await db.execute("DELETE FROM players")
            await db.execute("DELETE FROM codes")
            await _write_state(db, _default_state())
            await db.commit()
    TICK_HISTORY.clear()
    await manager.broadcast_all({"type": "reset"})
    await manager.broadcast_hosts({"type": "reset"})
    return {"ok": True}


# ═══════════════════════════════════════════════════════════════
#  REST: HOST GAME CONTROLS
# ═══════════════════════════════════════════════════════════════
@app.post("/api/host/start_round")
async def start_round(pw: str):
    if pw != HOST_PASSWORD:
        raise HTTPException(403, "Wrong password")
    async with STATE_LOCK:
        state = await read_state()
        if state["phase"] not in ("lobby", "break"):
            raise HTTPException(400, "Can't start round now")
        if state["round"] >= MAX_ROUNDS:
            raise HTTPException(400, f"All {MAX_ROUNDS} rounds are already complete — end the game instead.")
        state["round"] += 1
        state["phase"]          = "trading"
        state["round_end_time"] = time.time() + ROUND_DURATION
        state["break_end_time"] = None
        state["acquisition_pair"] = None          # per-round chaos effects reset
        state["pending_moves"]    = {}            # clear stale queued price moves from the previous round
        state.setdefault("round_marks", []).append([round(time.time(), 1), state["round"]])
        round_num = state["round"]
        event     = CHAOS_SCHEDULE.get(round_num)
        # Snapshot round-start net worth, reset per-round counters, and release anyone whose
        # bankruptcy lock-out has now run its course (they come back with the restart cash).
        players = await all_players()
        returned = []
        for p in players:
            changed = False
            if p["name"]:
                if p.get("bankrupt_until_round", 0) and round_num > p["bankrupt_until_round"]:
                    p["bankrupt_until_round"] = 0
                    p["cash"] = BANKRUPTCY_RESTART
                    returned.append(p["code"])
                p["net_worth_at_round_start"] = player_view(p, state)["net_worth"]
                p["trades_this_round"]        = 0
                p["realized_pnl_round"]       = 0
                changed = True
            if changed:
                await save_player(p)
        # Round-start news. The Truth-or-False round replaces it with timed mixed drops (see _run_truth_or_false).
        if event == "truth_or_false":
            news = []
        else:
            news = pick_news(state, 2 if round_num == 1 else 3)
        state["news"].extend(news)
        fluctuate_prices(state, news)
        ph = state.setdefault("price_history", {})
        for cid, c in state["companies"].items():
            ph.setdefault(cid, []).append(c["price"])
        record_history(state["companies"])
        await write_state(state)
    players = await all_players()
    board   = leaderboard(players, state)
    await manager.broadcast_all({
        "type":           "phase_change",
        "phase":          "trading",
        "round":          state["round"],
        "round_end_time": state["round_end_time"],
        "prices":         {k: c["price"] for k, c in state["companies"].items()},
    })
    for code_ in returned:
        pl = await get_player(code_)
        if pl:
            await manager.send_player(code_, {"type": "player_update", "player": player_view(pl, state),
                                              "msg": f"✅ Your bankruptcy lock-out is over. You're back with ₹{BANKRUPTCY_RESTART:,}."})
    for n in news:
        await manager.broadcast_all({"type": "news", **n})
    await manager.broadcast_hosts({
        "type":  "state_update",
        "state": state,
        "board": board,
        "player_count": len([p for p in players if p["name"]]),
    })
    # Run this round's chaos event (rounds 3-6). The round has already started and players have seen the
    # prices settle; a chaos hiccup must never turn into a failed request.
    if event:
        try:
            await run_chaos_event(event, round_num)
        except Exception as e:
            print(f"[start_round] chaos event {event!r} failed (round {round_num}): {e}")
    return {"ok": True, "round": round_num, "chaos": event}


@app.post("/api/host/end_round")
async def end_round(pw: str):
    if pw != HOST_PASSWORD:
        raise HTTPException(403, "Wrong password")
    async with STATE_LOCK:
        state = await read_state()
        if state["phase"] != "trading":
            raise HTTPException(400, "Not in trading phase")
        state["phase"]          = "break"
        state["round_end_time"] = None
        state["break_end_time"] = time.time() + BREAK_DURATION
        state["break_duration"] = BREAK_DURATION
        state["acquisition_pair"]  = None
        # Interest: charged on every loan at the end of EVERY round (1%–12% per round, tiered by balance)
        players = await all_players()
        for p in players:
            loans   = p.get("loans", {})
            locks   = p.get("rate_locks") or {}
            changed = False
            for bank_id, bal in list(loans.items()):
                if bal > 0 and bank_id in BANKS:
                    if bank_id in locks:
                        rate = locks.pop(bank_id)  # one-shot — consumed here
                    else:
                        rate = bank_rate_for_balance(bank_id, bal)
                    loans[bank_id] = round(bal * (1 + rate))
                    changed = True
            if locks != (p.get("rate_locks") or {}):
                p["rate_locks"] = locks
                changed = True
            if changed:
                p["loans"] = loans
                await save_player(p)
                pv = player_view(p, state)
                await manager.send_player(p["code"], {
                    "type":   "player_update",
                    "player": pv,
                    "msg":    "Interest applied to your loans at round end.",
                })

        # ── STT (Securities Transaction Tax): 0.2% of every trade's value, accrued live on every
        # buy/sell and charged here at round end. Wealth tax / income tax are PAUSED (rates are 0). ──
        board_pre_tax = leaderboard(players, state)
        leader_names  = {board_pre_tax[0]["name"]} if board_pre_tax else set()
        tax_summary   = []
        for p in players:
            if not p["name"]:
                continue
            stt = round(p.get("stt_accrued_round", 0))
            wealth_tax = 0
            if p["name"] in leader_names:
                wealth_tax = round(player_view(p, state)["net_worth"] * WEALTH_TAX_RATE)
            taxed = False
            if stt or wealth_tax:
                p["cash"] -= (stt + wealth_tax)
                taxed = True
                tax_summary.append({"name": p["name"], "stt": stt, "wealth_tax": wealth_tax})
                parts = []
                if stt:        parts.append(f"STT ₹{stt:,} (0.2% of this round's trades)")
                if wealth_tax: parts.append(f"Wealth tax ₹{wealth_tax:,}")
                await manager.send_player(p["code"], {
                    "type": "player_update", "player": player_view(p, state),
                    "msg":  "🧾 " + " + ".join(parts),
                })
            # Roll this round's realized P/L into the game-long total (taxed
            # once at end_game), then reset the per-round counters.
            p["realized_pnl_total"] = p.get("realized_pnl_total", 0) + p.get("realized_pnl_round", 0)
            p["stt_accrued_round"]  = 0
            if taxed or p.get("realized_pnl_round", 0) != 0:
                await save_player(p)

        # ── Round summary: for every player, their current holdings value,
        # this round's realized P/L (from anything sold), STT charged, and
        # net worth change — shown to each of them as the break begins. ────
        stt_by_name = {t["name"]: t["stt"] for t in tax_summary}
        summary_rows = []
        for p in players:
            if not p["name"]:
                continue
            start_nw = p.get("net_worth_at_round_start", 0)
            pv       = player_view(p, state)
            row = {
                "name":            p["name"],
                "delta":           round(pv["net_worth"] - start_nw),
                "trades":          p.get("trades_this_round", 0),
                "portfolio_value": pv["portfolio_value"],
                "realized_pnl":    round(p.get("realized_pnl_round", 0)),
                "stt":             stt_by_name.get(p["name"], 0),  # already charged above; kept for display
                "net_worth":       pv["net_worth"],
            }
            summary_rows.append(row)
            await manager.send_player(p["code"], {"type": "personal_round_summary", "summary": row})
        round_summary = {
            "round":       state["round"],
            "winner":      max(summary_rows, key=lambda r: r["delta"],  default=None),
            "loser":       min(summary_rows, key=lambda r: r["delta"],  default=None),
            "most_active": max(summary_rows, key=lambda r: r["trades"], default=None),
            "taxes":       tax_summary,
            "players":     summary_rows,
        }
        state["last_round_summary"] = round_summary
        state.setdefault("round_summaries", []).append(round_summary)
        # NOW reset the per-round realized-P/L counter, having used it above.
        for p in players:
            if p["name"] and p.get("realized_pnl_round", 0) != 0:
                p["realized_pnl_round"] = 0
                await save_player(p)
        await write_state(state)
    players = await all_players()
    board   = leaderboard(players, state)
    await manager.broadcast_all({
        "type":           "phase_change",
        "phase":          "break",
        "round":          state["round"],
        "break_end_time": state["break_end_time"],
        "break_duration": state["break_duration"],
    })
    await manager.broadcast_hosts({"type": "round_summary", "summary": round_summary})   # rankings/winners: host only
    await manager.broadcast_hosts({
        "type":  "state_update",
        "state": state,
        "board": board,
        "player_count": len([p for p in players if p["name"]]),
    })
    return {"ok": True}


@app.post("/api/host/end_game")
async def end_game(pw: str):
    if pw != HOST_PASSWORD:
        raise HTTPException(403, "Wrong password")
    async with STATE_LOCK:
        state     = await read_state()
        players   = await all_players()
        companies = state["companies"]

        # ── Force-liquidate everything so net worth becomes pure cash. ─────────
        for p in players:
            if not p["name"]:
                continue
            changed = False

            # Sell every held stock at its current price
            for cid, qty in list(p.get("holdings", {}).items()):
                if qty <= 0 or cid not in companies:
                    continue
                price    = companies[cid]["price"]
                avg_cost = p.get("avg_cost", {}).get(cid, price)
                realized = (price - avg_cost) * qty
                p["cash"] += price * qty
                p["realized_pnl_round"] = p.get("realized_pnl_round", 0) + realized
                p["stt_accrued_round"]  = p.get("stt_accrued_round", 0) + round(price * qty * STT_RATE)
                p["holdings"][cid] = 0
                changed = True
            p["stop_losses"] = {}

            if changed:
                await save_player(p)

        players = await all_players()

        # 3) FINAL charges pass. (Income tax and wealth tax are PAUSED — rates are 0 — so only leftover STT applies.)
        # It's 15% of the player's WHOLE-GAME realized gains: everything sold
        # across every round (realized_pnl_total, rolled up at each end_round)
        # plus whatever this final liquidation just realized. STT was already
        # charged round-by-round and is not touched again here. Wealth tax
        # still applies once more to whoever ends the game in 1st place.
        board_pre_tax     = leaderboard(players, state)
        leader_names      = {board_pre_tax[0]["name"]} if board_pre_tax else set()
        final_tax_summary = []
        for p in players:
            if not p["name"]:
                continue
            total_realized = p.get("realized_pnl_total", 0) + p.get("realized_pnl_round", 0)
            income_tax = 0
            if total_realized > 0:
                income_tax = round(total_realized * INCOME_TAX_RATE)
            wealth_tax = 0
            if p["name"] in leader_names:
                wealth_tax = round(player_view(p, state)["net_worth"] * WEALTH_TAX_RATE)
            # STT still owed: the final liquidation's own STT, plus this round's accrued STT if the
            # host ended the game straight from a live round (end_round never ran to charge it).
            stt = round(p.get("stt_accrued_round", 0))
            if income_tax or wealth_tax or stt:
                p["cash"] -= (income_tax + wealth_tax + stt)
                final_tax_summary.append({
                    "name": p["name"], "income_tax": income_tax, "wealth_tax": wealth_tax, "stt": stt,
                    "total_realized_gains": round(total_realized),
                })
            p["stt_accrued_round"] = 0
            p["realized_pnl_round"] = 0
            p["realized_pnl_total"] = total_realized
            await save_player(p)

        state["phase"] = "ended"
        state["final_liquidation_taxes"] = final_tax_summary
        await write_state(state)

    players = await all_players()
    board   = leaderboard(players, state)
    final_by_name = {t["name"]: t for t in final_tax_summary}
    for p in players:
        if not p["name"]:
            continue
        t  = final_by_name.get(p["name"], {})
        pv = player_view(p, state)
        # Sent BEFORE game_ended so the client already has it when the results screen opens.
        await manager.send_player(p["code"], {"type": "final_summary", "summary": {
            "net_worth":            pv["net_worth"],
            "cash":                 pv["cash"],
            "total_loan":           pv["total_loan"],
            "total_realized_gains": t.get("total_realized_gains", round(p.get("realized_pnl_total", 0))),
            "income_tax":           t.get("income_tax", 0),
            "wealth_tax":           t.get("wealth_tax", 0),
            "stt":                  t.get("stt", 0),
        }})
        await manager.send_player(p["code"], {
            "type": "player_update", "player": pv,
            "msg":  "🏁 Game over — everything has been converted to cash and final charges applied.",
        })
    await manager.broadcast_all({"type": "game_ended"})
    await manager.broadcast_hosts({
        "type":  "state_update",
        "state": state,
        "board": board,
        "player_count": len([p for p in players if p["name"]]),
    })
    return {"ok": True}


@app.get("/api/host/recap")
async def host_recap(pw: str):
    if pw != HOST_PASSWORD:
        raise HTTPException(403, "Wrong password")
    state = await read_state()
    if state["phase"] != "ended":
        raise HTTPException(400, "The game hasn't ended yet.")
    players = await all_players()
    board   = leaderboard(players, state)

    richest = board[0] if board else None
    poorest = board[-1] if board else None

    bankrupt_players = [
        {"name": p["name"], "count": p.get("bankruptcy_count", 0)}
        for p in players if p.get("bankruptcy_count")
    ]
    bankrupt_players.sort(key=lambda r: -r["count"])

    rumours = [
        {"text": t["text"], "real": bool(t["real"]), "affects": t.get("affects")}
        for t in state.get("truth_log", [])
    ]
    real_count  = sum(1 for r in rumours if r["real"])
    fake_count  = sum(1 for r in rumours if not r["real"])

    summaries = state.get("round_summaries", [])
    final_taxes = state.get("final_liquidation_taxes", [])
    total_income_tax = sum(t["income_tax"] for t in final_taxes)  # income tax is only charged once, at end_game
    total_stt        = sum(t.get("stt", 0) for s in summaries for t in s.get("taxes", [])) + sum(t.get("stt", 0) for t in final_taxes)
    total_wealth_tax  = sum(t.get("wealth_tax", 0) for s in summaries for t in s.get("taxes", []))  + sum(t["wealth_tax"] for t in final_taxes)

    # Biggest single-round swing across the whole game (best "winner" delta seen in any round)
    best_round = max(
        (s["winner"] for s in summaries if s.get("winner")),
        key=lambda w: w["delta"], default=None,
    )
    most_active_overall = max(
        (s["most_active"] for s in summaries if s.get("most_active")),
        key=lambda m: m["trades"], default=None,
    )

    return {
        "board":              board,
        "richest":            richest,
        "poorest":            poorest,
        "bankrupt_players":   bankrupt_players,
        "rumours":            rumours,
        "real_count":         real_count,
        "fake_count":         fake_count,
        "total_income_tax":   round(total_income_tax),
        "total_stt":          round(total_stt),
        "total_wealth_tax":   round(total_wealth_tax),
        "best_round_swing":   best_round,
        "most_active_overall": most_active_overall,
        "round_summaries":    summaries,
    }


@app.post("/api/host/adjust_cash")
async def adjust_cash(data: dict, pw: str):
    if pw != HOST_PASSWORD:
        raise HTTPException(403, "Wrong password")
    code      = data["code"]
    amount    = int(data["amount"])
    direction = 1 if data.get("direction", 1) > 0 else -1
    p = await get_player(code)
    if not p:
        raise HTTPException(404, "Player not found")
    p["cash"] = max(0, p["cash"] + direction * amount)
    await save_player(p)
    state = await read_state()
    pv    = player_view(p, state)
    sign  = "+" if direction > 0 else "-"
    await manager.send_player(code, {"type": "player_update", "player": pv})
    await manager.send_player(code, {"type": "info", "msg": f"Host adjustment: {sign}₹{amount:,}"})
    players = await all_players()
    board   = leaderboard(players, state)
    await manager.broadcast_hosts({
        "type":  "state_update",
        "state": state,
        "board": board,
        "player_count": len([p for p in players if p["name"]]),
    })
    return {"ok": True}


@app.post("/api/host/inject_news")
async def inject_news(data: dict, pw: str):
    if pw != HOST_PASSWORD:
        raise HTTPException(403, "Wrong password")
    async with STATE_LOCK:
        state       = await read_state()
        strength    = safe_float(data.get("strength"), 0.10)
        affects     = data.get("affects")
        if affects not in state["companies"]:
            raise HTTPException(400, "Unknown company")
        direction   = 1 if safe_int(data.get("direction"), 1) > 0 else -1
        text        = re.sub(r"[<>]", "", (data.get("text") or "").strip())
        if not text:
            # Host left the text field blank — auto-pick a matching preset headline.
            text = pick_preset(state, affects, "up" if direction > 0 else "down")
            if not text:
                cname = state["companies"][affects]["name"]
                text  = (f"Market update: {cname} sees notable "
                         f"{'gains' if direction > 0 else 'losses'} amid shifting investor sentiment.")
        n = make_news_item(text, affects, direction, real=True, src="news", strength=strength, state=state)
        apply_news_now(state, n)
        record_history(state["companies"])
        await write_state(state)
    await manager.broadcast_all({"type": "news", **n})
    players = await all_players()
    board   = leaderboard(players, state)
    pb = {"type": "prices_bulk", "ts": time.time(), "prices": {k: v["price"] for k, v in state["companies"].items()}}
    await manager.broadcast_all(pb)
    await manager.broadcast_hosts({**pb, "board": board})
    await manager.broadcast_hosts({"type": "state_update", "state": state, "board": board})
    return {"ok": True, "text": text}


@app.post("/api/host/manual_price")
async def manual_price(data: dict, pw: str):
    if pw != HOST_PASSWORD:
        raise HTTPException(403, "Wrong password")
    async with STATE_LOCK:
        state = await read_state()
        cid   = data["stock"]
        price = int(data["price"])
        if cid not in state["companies"]:
            raise HTTPException(400, "Unknown stock")
        state["companies"][cid]["prev_price"]   = state["companies"][cid]["price"]
        state["companies"][cid]["price"]        = max(1, price)
        state["companies"][cid]["target_price"] = max(1, price)
        await write_state(state)
    players = await all_players()
    board   = leaderboard(players, state)
    await manager.broadcast_all({
        "type":   "prices_bulk",
        "prices": {k: v["price"] for k, v in state["companies"].items()},
        "board":  board,
    })
    return {"ok": True}


@app.post("/api/host/wipe_loan")
async def wipe_loan(data: dict, pw: str):
    """Host manually clears a player's loan at a specific bank."""
    if pw != HOST_PASSWORD:
        raise HTTPException(403, "Wrong password")
    code    = data["code"]
    bank_id = data["bank_id"]
    p = await get_player(code)
    if not p:
        raise HTTPException(404, "Player not found")
    p["loans"].pop(bank_id, None)
    await save_player(p)
    state = await read_state()
    await manager.send_player(code, {
        "type":   "player_update",
        "player": player_view(p, state),
        "msg":    f"Host cleared your {BANKS.get(bank_id, {}).get('name', bank_id)} loan.",
    })
    return {"ok": True}


# ═══════════════════════════════════════════════════════════════
#  REST: CHAOS EVENTS
# ═══════════════════════════════════════════════════════════════






# ═══════════════════════════════════════════════════════════════
#  WEBSOCKET: PLAYER
# ═══════════════════════════════════════════════════════════════
# ═══════════════════════════════════════════════════════════════
#  CHAOS EVENTS — exactly four, one per round in rounds 3-6 (see CHAOS_SCHEDULE):
#    ipo_drop · dividend · acquisition · truth_or_false
#  Each is fired automatically by start_round; the host panel can also fire one early (once per game).
# ═══════════════════════════════════════════════════════════════
_BG_TASKS: set = set()


def _spawn(coro) -> None:
    t = asyncio.create_task(coro)
    _BG_TASKS.add(t)                      # keep a reference so it isn't garbage-collected mid-flight
    t.add_done_callback(_BG_TASKS.discard)


async def _still_in_round(round_num: int) -> bool:
    st = await read_state()
    return st.get("phase") == "trading" and st.get("round") == round_num


async def _after(delay: float, round_num: int, coro_fn) -> None:
    """Run coro_fn() after `delay` seconds — but only if this round is still going."""
    try:
        await asyncio.sleep(delay)
        if await _still_in_round(round_num):
            await coro_fn()
    except Exception as e:
        print(f"[chaos] delayed event failed: {e}")


async def _host_refresh(state: dict) -> None:
    players = await all_players()
    await manager.broadcast_hosts({"type": "state_update", "state": state, "board": leaderboard(players, state),
                                   "player_count": len([p for p in players if p["name"]])})


# ── a) IPO DROP ───────────────────────────────────────────────────────────
async def _event_ipo_drop() -> None:
    """The two held-back companies (different sectors) list on the exchange at the same moment."""
    async with STATE_LOCK:
        state = await read_state()
        newly = []
        for ipo_id, ipo in IPO_COMPANIES.items():
            if ipo_id in state.get("ipo_listed", []):
                continue
            state["companies"][ipo_id] = {**ipo, "prev_price": ipo["price"], "target_price": ipo["price"]}
            state.setdefault("ipo_listed", []).append(ipo_id)
            state.setdefault("price_history", {})[ipo_id] = [ipo["price"]]
            newly.append(ipo_id)
        if not newly:
            return
        record_history(state["companies"])
        await write_state(state)
    names = " and ".join(IPO_COMPANIES[i]["name"] for i in newly)
    listed = public_companies({i: state["companies"][i] for i in newly})
    await manager.broadcast_all({
        "type":      "chaos",
        "event":     "ipo_drop",
        "msg":       f"🚀 IPO DROP — {names} just listed on the exchange! Both are now open for trading.",
        "companies": [{"id": i, **listed[i]} for i in newly],
    })
    await _host_refresh(state)


# ── b) DIVIDEND PAYOUT ────────────────────────────────────────────────────
async def _pay_dividends(nth: int = 1) -> None:
    """Pay the per-share dividend on every dividend-paying company (8 of them) to all holders."""
    state = await read_state()
    items = {cid: ps for cid, ps in DIVIDEND_PER_SHARE.items() if cid in state["companies"]}
    if not items:
        return
    players = await all_players()
    for p in players:
        lines, total = [], 0
        for cid, ps in items.items():
            qty = p["holdings"].get(cid, 0)
            if qty > 0:
                div = qty * ps
                total += div
                lines.append(f"{qty}× {state['companies'][cid]['name']} = ₹{div:,.0f}")
        if total:
            p["cash"] += total
            await save_player(p)
            await manager.send_player(p["code"], {
                "type": "player_update", "player": player_view(p, state),
                "msg":  "💰 Dividends paid: " + "; ".join(lines) + f" — total +₹{total:,.0f}",
            })
    per_line = ", ".join(f"{state['companies'][cid].get('ticker', cid.upper())} ₹{ps:g}" for cid, ps in items.items())
    await manager.broadcast_all({
        "type": "chaos", "event": "dividend",
        "msg":  f"💰 DIVIDEND PAYOUT ({nth} of 2) — per share: {per_line}. Holders have been paid.",
    })
    await _host_refresh(state)


async def _event_dividend(round_num: int, immediate_second: bool = False) -> None:
    await _pay_dividends(1)
    _spawn(_after(DIVIDEND_SECOND_PAYOUT, round_num, lambda: _pay_dividends(2)))      # second payout, mid-round


# ── c) ACQUISITION RUMOUR ─────────────────────────────────────────────────
async def _link_companies() -> None:
    """Two companies from different sectors become linked (their moves are blended) and both run at High
    volatility until the round ends. Announced as an acquisition rumour."""
    cid1, cid2 = ACQUISITION_PAIR
    async with STATE_LOCK:
        state = await read_state()
        if cid1 not in state["companies"] or cid2 not in state["companies"]:
            return
        state["acquisition_pair"] = [cid1, cid2]
        n1, n2 = state["companies"][cid1]["name"], state["companies"][cid2]["name"]
        msg  = f"🤝 ACQUISITION RUMOUR — {n1} and {n2} are reportedly in merger talks. Expect their share prices to move together."
        item = make_news_item(msg, cid1, 1, real=True, src="rumour", state=state)
        await write_state(state)
    await manager.broadcast_all({"type": "chaos", "event": "acquisition_rumour", "msg": msg})
    await manager.broadcast_all({"type": "news", **item})
    await _host_refresh(state)


# ── d) TRUTH OR FALSE ────────────────────────────────────────────────────
async def _run_truth_or_false(round_num: int) -> None:
    """For one round, drop real news mixed with false rumours. Players see every item as ordinary news —
    no banner, no label. The host panel (and the end-game recap) show which items were TRUE."""
    try:
        for i in range(TRUTH_DROPS):
            if i:
                await asyncio.sleep(TRUTH_DROP_EVERY)
            if not await _still_in_round(round_num):
                return
            async with STATE_LOCK:
                state = await read_state()
                if state.get("phase") != "trading" or state.get("round") != round_num:
                    return
                items = pick_truth_pair(state)
                for n in items:
                    state["news"].append(n)
                    apply_news_now(state, n)
                    state.setdefault("truth_log", []).append(
                        {"id": n["id"], "text": n["text"], "real": n["real"], "affects": n["affects"], "round": round_num})
                record_history(state["companies"])
                await write_state(state)
            for n in items:
                await manager.broadcast_all({"type": "news", **n})
            pb = {"type": "prices_bulk", "ts": time.time(), "prices": {k: v["price"] for k, v in state["companies"].items()}}
            await manager.broadcast_all(pb)
            await _host_refresh(state)
    except Exception as e:
        print(f"[truth_or_false] failed: {e}")


async def run_chaos_event(event: str, round_num: int, immediate: bool = False) -> None:
    """Fire one chaos event. `immediate` (host pressing 'Fire now') skips the in-round delay of the
    acquisition rumour. Each event can fire once per game."""
    async with STATE_LOCK:
        state = await read_state()
        if event in state.get("chaos_done", []):
            raise HTTPException(400, f"{CHAOS_LABELS.get(event, event)} has already happened this game.")
        state.setdefault("chaos_done", []).append(event)
        await write_state(state)
    if event == "ipo_drop":
        await _event_ipo_drop()
    elif event == "dividend":
        await _event_dividend(round_num)
    elif event == "acquisition":
        if immediate:
            await _link_companies()
        else:
            _spawn(_after(ACQUISITION_DELAY, round_num, _link_companies))
    elif event == "truth_or_false":
        _spawn(_run_truth_or_false(round_num))
    else:
        raise HTTPException(400, f"Unknown chaos event: {event}")


@app.get("/api/host/chaos")
async def chaos_status(pw: str):
    if pw != HOST_PASSWORD:
        raise HTTPException(403, "Wrong password")
    state = await read_state()
    return {"schedule": CHAOS_SCHEDULE, "labels": CHAOS_LABELS, "done": state.get("chaos_done", []),
            "round": state.get("round", 0), "phase": state.get("phase"),
            "acquisition_pair": state.get("acquisition_pair")}


@app.post("/api/host/chaos/{event}")
async def chaos_fire(event: str, pw: str):
    """Fire one of the four chaos events right now (normally they fire on their own at the start of their round)."""
    if pw != HOST_PASSWORD:
        raise HTTPException(403, "Wrong password")
    if event not in CHAOS_LABELS:
        raise HTTPException(400, "Unknown chaos event")
    state = await read_state()
    if state.get("phase") != "trading":
        raise HTTPException(400, "Chaos events can only be fired while a round is in progress.")
    await run_chaos_event(event, state["round"], immediate=True)
    return {"ok": True, "event": event}


@app.get("/api/company_guide")
async def company_guide():
    """Public (players): history, financials and background for every company that is currently listed.
    Held-back companies stay out of the guide until the IPO Drop lists them."""
    state = await read_state()
    return {"companies": {cid: GUIDE[cid] for cid in state["companies"] if cid in GUIDE}}


@app.websocket("/ws/player/{code}")
async def ws_player(websocket: WebSocket, code: str):
    code        = code.upper()
    valid_codes = await all_codes()
    if code not in valid_codes:
        await websocket.accept()
        await websocket.send_text(json.dumps({"type": "error", "msg": "Invalid code. Check with your host."}))
        await websocket.close()
        return

    # ── Single-use code guard ─────────────────────────────────────────────────
    # If someone is already connected on this code AND they have a name (i.e.
    # they've fully joined), reject the new connection to prevent code-sharing.
    existing_ws = manager.players.get(code)
    if existing_ws is not None:
        player_check = await get_player(code)
        if player_check and bool(player_check.get("name")):
            await websocket.accept()
            await websocket.send_text(json.dumps({
                "type": "error",
                "msg":  "This code is already in use by another device. Each code is single-use. Contact your host if you need a new one."
            }))
            await websocket.close()
            return

    await manager.connect_player(code, websocket)
    state  = await read_state()
    player = await get_player(code)
    already_joined = player is not None and bool(player["name"])

    await websocket.send_text(json.dumps({
        "type":          "init",
        "phase":         state["phase"],
        "round":         state["round"],
        "round_end_time": state.get("round_end_time"),
        "break_end_time": state.get("break_end_time"),
        "break_duration": state.get("break_duration", BREAK_DURATION),
        "market":        public_companies(state["companies"]),
        "banks":         BANKS,
        "joined":        already_joined,
        "price_history": state.get("price_history", {}),
        "history":       TICK_HISTORY,                       # server-side price series for the chart
        "round_marks":   state.get("round_marks", []),
        "server_time":   time.time(),
        "news":          [public_news(n) for n in state.get("news", [])],
        **({"name": player["name"], "player": player_view(player, state)} if already_joined else {}),
    }))

    try:
        async for raw in websocket.iter_text():
            try:
                msg = json.loads(raw)
                if not isinstance(msg, dict):
                    raise ValueError("payload must be a JSON object")
            except Exception:
                await websocket.send_text(json.dumps({"type": "error", "msg": "Malformed message — ignored."}))
                continue
            action = msg.get("action")
            try:
                # Always re-read state and player for freshness
                state  = await read_state()
                player = await get_player(code)

                # ── Set name ──────────────────────────────────────────────
                if action == "set_name":
                    raw_name = (msg.get("name") or "").strip()[:30]
                    # Names get interpolated into innerHTML in a few places across
                    # team/host/board — strip angle brackets so nobody can plant a
                    # <script>/<img onerror> tag as their display name.
                    name = re.sub(r"[<>]", "", raw_name).strip()
                    if not name:
                        await websocket.send_text(json.dumps({"type": "error", "msg": "Name can't be empty."}))
                        continue
                    players = await all_players()
                    if any(p["name"] == name and p["code"] != code for p in players):
                        await websocket.send_text(json.dumps({"type": "error", "msg": "Name taken. Pick another."}))
                        continue
                    if player:
                        player["name"] = name
                    else:
                        player = {
                            "code": code, "name": name, "cash": STARTING_CASH,
                            "holdings": {}, "loans": {},
                            "avg_cost": {},
                        }
                    # Baseline for the break summary — otherwise someone joining mid-game would see
                    # their ENTIRE net worth reported as "gained this round".
                    if not player.get("net_worth_at_round_start"):
                        player["net_worth_at_round_start"] = player_view(player, state)["net_worth"]
                    await save_player(player)
                    pv = player_view(player, state)
                    await websocket.send_text(json.dumps({
                        "type":           "joined",
                        "name":           name,
                        "player":         pv,
                        "banks":          BANKS,
                        "round_end_time": state.get("round_end_time"),
                        "break_end_time": state.get("break_end_time"),
                        "break_duration": state.get("break_duration", BREAK_DURATION),
                    }))
                    players = await all_players()
                    board   = leaderboard(players, state)
                    await manager.broadcast_hosts({"type": "leaderboard", "board": board})
                    await manager.broadcast_hosts({"type": "player_online", "code": code, "name": name})

                # ── Buy ───────────────────────────────────────────────────
                elif action == "buy":
                    if state["phase"] != "trading":
                        await websocket.send_text(json.dumps({"type": "error", "msg": "Trading is closed."})); continue
                    if not player:
                        await websocket.send_text(json.dumps({"type": "error", "msg": "Join first."})); continue
                    if is_locked_out(player, state):
                        await websocket.send_text(json.dumps({"type": "error", "msg": f"💀 You're bankrupt — locked out for {locked_rounds_left(player, state)} more round(s)."})); continue
                    stock = msg.get("stock")
                    qty   = safe_int(msg.get("qty"), 0)
                    if stock not in state["companies"] or qty < 1:
                        await websocket.send_text(json.dumps({"type": "error", "msg": "Invalid stock or quantity."})); continue
                    # Use per-player lock to prevent race conditions
                    async with _player_locks[code]:
                        player = await get_player(code)   # re-read inside lock
                        state  = await read_state()
                        quote  = state["companies"][stock]["price"]
                        # Slippage: a big order fills at the MIDPOINT of the price move it causes,
                        # so buying then instantly selling back can't be a free profit.
                        price  = round(quote * (1 + trade_impact(state, stock, qty, quote) / 2))
                        cost   = price * qty
                        if player["cash"] < cost:
                            await websocket.send_text(json.dumps({"type": "error", "msg": f"Need ₹{cost:,}. You have ₹{int(player['cash']):,}."})); continue
                        old_qty = player["holdings"].get(stock, 0)
                        old_avg = player["avg_cost"].get(stock, price)
                        player["avg_cost"][stock] = ((old_avg * old_qty + price * qty) / (old_qty + qty)) if old_qty else price
                        player["holdings"][stock]  = old_qty + qty
                        player["cash"]            -= cost
                        player["trades_this_round"] = player.get("trades_this_round", 0) + 1
                        # STT: 0.2% of trade value, accrued now, actually charged at round end.
                        stt = round(cost * STT_RATE)
                        player["stt_accrued_round"] = player.get("stt_accrued_round", 0) + stt
                        await save_player(player)
                        # Price elasticity: buying nudges the price up, proportional to trade size.
                        async with STATE_LOCK:   # re-read fresh so we don't clobber a price tick that landed meanwhile
                            state = await read_state()
                            apply_trade_elasticity(state, stock, qty, quote, is_buy=True)
                            await write_state(state)
                    pv = player_view(player, state)
                    await websocket.send_text(json.dumps({
                        "type":   "trade_ok",
                        "msg":    f"Bought {qty}× {state['companies'][stock]['name']} @ ₹{price:,}",
                        "player": pv,
                    }))
                    board = leaderboard(await all_players(), state)
                    await manager.broadcast_hosts({"type": "leaderboard", "board": board})

                # ── Sell ──────────────────────────────────────────────────
                elif action == "sell":
                    if state["phase"] != "trading":
                        await websocket.send_text(json.dumps({"type": "error", "msg": "Trading is closed."})); continue
                    if not player:
                        await websocket.send_text(json.dumps({"type": "error", "msg": "Join first."})); continue
                    if is_locked_out(player, state):
                        await websocket.send_text(json.dumps({"type": "error", "msg": f"💀 You're bankrupt — locked out for {locked_rounds_left(player, state)} more round(s)."})); continue
                    stock = msg.get("stock")
                    qty   = safe_int(msg.get("qty"), 0)
                    if stock not in state["companies"]:
                        await websocket.send_text(json.dumps({"type": "error", "msg": "Invalid stock."})); continue
                    async with _player_locks[code]:
                        player = await get_player(code)
                        state  = await read_state()
                        owned  = player["holdings"].get(stock, 0)
                        if qty < 1 or qty > owned:
                            await websocket.send_text(json.dumps({"type": "error", "msg": f"You only own {owned} shares."})); continue
                        quote = state["companies"][stock]["price"]
                        price = round(quote * (1 - trade_impact(state, stock, qty, quote) / 2))
                        avg_cost = player.get("avg_cost", {}).get(stock, price)
                        realized = (price - avg_cost) * qty
                        proceeds = price * qty
                        player["cash"]             += proceeds
                        player["holdings"][stock]   = owned - qty
                        player["trades_this_round"]  = player.get("trades_this_round", 0) + 1
                        player["realized_pnl_round"] = player.get("realized_pnl_round", 0) + realized
                        # STT: 0.2% of trade value, accrued now, actually charged at round end.
                        stt = round(proceeds * STT_RATE)
                        player["stt_accrued_round"] = player.get("stt_accrued_round", 0) + stt
                        await save_player(player)
                        # Price elasticity: selling nudges the price down, proportional to trade size.
                        async with STATE_LOCK:   # re-read fresh so we don't clobber a price tick that landed meanwhile
                            state = await read_state()
                            apply_trade_elasticity(state, stock, qty, quote, is_buy=False)
                            await write_state(state)
                    pv = player_view(player, state)
                    await websocket.send_text(json.dumps({
                        "type":   "trade_ok",
                        "msg":    f"Sold {qty}× {state['companies'][stock]['name']} @ ₹{price:,}",
                        "player": pv,
                    }))
                    board = leaderboard(await all_players(), state)
                    await manager.broadcast_hosts({"type": "leaderboard", "board": board})

                # ── Set / Cancel Stop-Loss ──────────────────────────────────
                elif action == "set_stop_loss":
                    if not player:
                        await websocket.send_text(json.dumps({"type": "error", "msg": "Join first."})); continue
                    stock   = msg.get("stock")
                    trigger = safe_float(msg.get("trigger"), 0)
                    if stock not in player.get("holdings", {}) or player["holdings"][stock] < 1:
                        await websocket.send_text(json.dumps({"type": "error", "msg": "You don't hold any shares of that stock."})); continue
                    if trigger <= 0:
                        await websocket.send_text(json.dumps({"type": "error", "msg": "Enter a valid trigger price."})); continue
                    async with _player_locks[code]:
                        player = await get_player(code)
                        stops  = player.get("stop_losses", {})
                        stops[stock] = trigger
                        player["stop_losses"] = stops
                        await save_player(player)
                    pv = player_view(player, state)
                    await websocket.send_text(json.dumps({
                        "type":   "player_update", "player": pv,
                        "msg":    f"🛑 Stop-loss set on {state['companies'][stock]['name']} at ₹{trigger:,.0f}.",
                    }))

                elif action == "cancel_stop_loss":
                    if not player:
                        await websocket.send_text(json.dumps({"type": "error", "msg": "Join first."})); continue
                    stock = msg.get("stock")
                    async with _player_locks[code]:
                        player = await get_player(code)
                        stops  = player.get("stop_losses", {})
                        stops.pop(stock, None)
                        player["stop_losses"] = stops
                        await save_player(player)
                    pv = player_view(player, state)
                    await websocket.send_text(json.dumps({
                        "type": "player_update", "player": pv, "msg": "Stop-loss cancelled.",
                    }))

                # ── Take loan ─────────────────────────────────────────────
                elif action == "take_loan":
                    if not player:
                        await websocket.send_text(json.dumps({"type": "error", "msg": "Join first."})); continue
                    if is_locked_out(player, state):
                        await websocket.send_text(json.dumps({"type": "error", "msg": "💀 You're bankrupt — no borrowing until your lock-out ends."})); continue
                    bank_id = msg.get("bank_id")
                    amount  = safe_int(msg.get("amount"), 0)
                    if bank_id not in BANKS:
                        await websocket.send_text(json.dumps({"type": "error", "msg": "Invalid bank."})); continue
                    bank        = BANKS[bank_id]
                    current_bal = player.get("loans", {}).get(bank_id, 0)
                    if current_bal + amount > bank["limit"]:
                        remain = max(0, bank["limit"] - current_bal)
                        await websocket.send_text(json.dumps({"type": "error", "msg": f"Exceeds {bank['name']} limit. Max additional: ₹{remain:,}."})); continue
                    if amount <= 0:
                        await websocket.send_text(json.dumps({"type": "error", "msg": "Amount must be positive."})); continue
                    async with _player_locks[code]:
                        player = await get_player(code)
                        player["cash"]               += amount
                        player.setdefault("loans", {})[bank_id] = player["loans"].get(bank_id, 0) + amount
                        await save_player(player)
                    pv       = player_view(player, state)
                    new_bal  = player["loans"][bank_id]
                    rate     = bank_rate_for_balance(bank_id, new_bal)
                    await websocket.send_text(json.dumps({
                        "type":   "trade_ok",
                        "msg":    f"₹{amount:,} from {bank['name']}. Balance: ₹{int(new_bal):,}. Current rate: {rate*100:.0f}%/round.",
                        "player": pv,
                    }))

                # ── Repay loan ────────────────────────────────────────────
                elif action == "repay_loan":
                    if not player:
                        await websocket.send_text(json.dumps({"type": "error", "msg": "Join first."})); continue
                    if state["phase"] != "break":
                        await websocket.send_text(json.dumps({"type": "error", "msg": "Loans can only be repaid during the break."})); continue
                    bank_id   = msg.get("bank_id")
                    repay_amt = safe_int(msg.get("amount"), 0)
                    if bank_id not in BANKS:
                        await websocket.send_text(json.dumps({"type": "error", "msg": "Invalid bank."})); continue
                    if repay_amt <= 0:
                        await websocket.send_text(json.dumps({"type": "error", "msg": "Amount must be positive."})); continue
                    async with _player_locks[code]:
                        player    = await get_player(code)
                        bal       = player.get("loans", {}).get(bank_id, 0)
                        if bal <= 0:
                            await websocket.send_text(json.dumps({"type": "error", "msg": f"No balance at {BANKS[bank_id]['name']}."})); continue
                        repay_amt = min(repay_amt, int(bal))
                        if player["cash"] < repay_amt:
                            await websocket.send_text(json.dumps({"type": "error", "msg": f"Not enough cash. You have ₹{int(player['cash']):,}."})); continue
                        player["cash"] -= repay_amt
                        remaining       = max(0, bal - repay_amt)
                        if remaining == 0:
                            player["loans"].pop(bank_id, None)
                        else:
                            player["loans"][bank_id] = remaining
                        await save_player(player)
                    pv        = player_view(player, state)
                    bank_name = BANKS[bank_id]["name"]
                    await websocket.send_text(json.dumps({
                        "type":   "trade_ok",
                        "msg":    f"Repaid ₹{repay_amt:,} to {bank_name}. {'Fully cleared! ✅' if remaining == 0 else f'₹{int(remaining):,} still owed.'}",
                        "player": pv,
                    }))

                # ── Voluntary bankruptcy ──────────────────────────────────
                elif action == "declare_bankruptcy":
                    if not player:
                        await websocket.send_text(json.dumps({"type": "error", "msg": "Join first."})); continue
                    pre_check = player_view(player, state)
                    debt_gap  = pre_check["total_loan"] - pre_check["net_worth"]
                    if debt_gap < BANKRUPTCY_MIN_DEBT_GAP:
                        shortfall = BANKRUPTCY_MIN_DEBT_GAP - debt_gap
                        await websocket.send_text(json.dumps({
                            "type": "error",
                            "msg":  (f"Bankruptcy isn't available yet. Your debt needs to exceed your net worth "
                                     f"by ₹{BANKRUPTCY_MIN_DEBT_GAP:,}+ (you're ₹{int(shortfall):,} short)."),
                        })); continue
                    if is_locked_out(player, state):
                        await websocket.send_text(json.dumps({"type": "error", "msg": "You're already bankrupt."})); continue
                    async with _player_locks[code]:
                        player = await get_player(code)
                        # Wiped clean AND locked out: no trading or borrowing for the next BANKRUPTCY_LOCK_ROUNDS rounds.
                        # They come back (with BANKRUPTCY_RESTART cash) when the round after the lock-out starts.
                        player["cash"]        = 0
                        player["holdings"]    = {}
                        player["loans"]       = {}
                        player["avg_cost"]    = {}
                        player["stop_losses"] = {}
                        player["bankruptcy_count"]    = player.get("bankruptcy_count", 0) + 1
                        player["bankrupt_until_round"] = state["round"] + BANKRUPTCY_LOCK_ROUNDS
                        await save_player(player)
                    state = await read_state()
                    pv = player_view(player, state)
                    await websocket.send_text(json.dumps({
                        "type":   "bankrupt",
                        "msg":    (f"💀 Bankruptcy declared. Everything is wiped. You cannot trade or borrow for the next "
                                   f"{BANKRUPTCY_LOCK_ROUNDS} rounds. You'll return with ₹{BANKRUPTCY_RESTART:,} when the lock-out ends."),
                        "player": pv,
                    }))
                    await manager.broadcast_all({
                        "type":  "chaos",
                        "event": "bankrupt",
                        "msg":   f"💀 {player['name']} declared bankruptcy and is out for {BANKRUPTCY_LOCK_ROUNDS} rounds!",
                    })
                    await manager.broadcast_hosts({"type": "leaderboard", "board": leaderboard(await all_players(), state)})

            except WebSocketDisconnect:
                raise
            except Exception as e:
                print(f"[ws_player:{code}] action '{action}' failed: {e}")
                try:
                    await websocket.send_text(json.dumps({"type": "error", "msg": "Something went wrong processing that action — try again."}))
                except Exception:
                    pass
                continue

    except WebSocketDisconnect:
        pass
    finally:
        manager.disconnect_player(code)
        # Notify host that this player went offline (include name so the host
        # panel can show a proper alert instead of just a bare code)
        p_off = await get_player(code)
        await manager.broadcast_hosts({
            "type": "player_offline",
            "code": code,
            "name": (p_off["name"] if p_off and p_off.get("name") else code),
        })


# ═══════════════════════════════════════════════════════════════
#  WEBSOCKET: HOST
# ═══════════════════════════════════════════════════════════════
@app.websocket("/ws/host")
async def ws_host(websocket: WebSocket):
    # Only a connection presenting the host password is a real host console. Anyone else
    # (the public /board screen) is a "viewer" and only ever sees round/phase/timer + ranking.
    is_admin = websocket.query_params.get("pw") == HOST_PASSWORD
    await manager.connect_host(websocket, admin=is_admin)
    try:
        state   = await read_state()
        players = await all_players()
        board   = leaderboard(players, state)
        if is_admin:
            first = {
                "type":         "state_update",
                "state":        state,
                "board":        board,
                "player_count": len([p for p in players if p["name"]]),
            }
        else:
            first = {
                "type":  "state_update",
                "state": {k: state.get(k) for k in ("round", "phase", "round_end_time", "break_end_time")},
                "board": board,
            }
        await websocket.send_text(json.dumps(first))
        async for raw in websocket.iter_text():
            try:
                msg = json.loads(raw)
                if not isinstance(msg, dict):
                    continue
            except Exception:
                continue
            if msg.get("type") == "ping":
                state   = await read_state()
                players = await all_players()
                board   = leaderboard(players, state)
                await websocket.send_text(json.dumps({
                    "type":         "state_update",
                    "state":        state,
                    "board":        board,
                    "player_count": len([p for p in players if p["name"]]),
                }))
    except WebSocketDisconnect:
        pass
    finally:
        manager.disconnect_host(websocket)