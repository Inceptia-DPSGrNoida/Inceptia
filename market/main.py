"""
Market Mayhem — main.py
FastAPI + WebSockets + SQLite (aiosqlite)

Local:   uvicorn main:app --reload --port 8000
Railway: uvicorn main:app --host 0.0.0.0 --port $PORT

Routes:
  /          →  team.html   (player trading UI)
  /host      →  host.html   (password-protected host panel)

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

from news_presets import NEWS_PRESETS, ORGANISER_NOTES, PLOT_GROUPS

# ═══════════════════════════════════════════════════════════════
#  CONFIG
# ═══════════════════════════════════════════════════════════════
DB_PATH            = Path(os.getenv("DB_PATH", "game.db"))
HOST_PASSWORD      = os.getenv("HOST_PASSWORD", "Ich_liebe_Siya")
STARTING_CASH      = 150_000     # ₹1.5L starting cash for every player
ROUND_DURATION     = 1200        # 20 min — host can end early
BREAK_DURATION     = 600         # 10 min between rounds
BANKRUPTCY_RESTART = 25_000
INCOME_TAX_RATE    = 0.15   # on realized gains — charged ONCE, at the end of the final round only
WEALTH_TAX_RATE    = 0.03   # on the round-end leader's net worth
INSURANCE_PREMIUM_PCT  = 0.08   # cost to insure a position = 8% of its value at purchase
INSURANCE_COVERAGE_PCT = 0.60   # covers 60% of the loss below your locked cost, if you still hold it at round end
STT_RATE                = 0.002  # Securities Transaction Tax — 0.2% of every trade's value, accrued live, charged at round end
NEWS_REACTION_EMOJIS = {"🔥", "📈", "📉", "😱", "💀", "🤔"}
BANKRUPTCY_MIN_DEBT_GAP = 900_000   # debt must exceed net worth by ~9 lakh to qualify
MAX_ROUNDS         = 4

# Per-player asyncio lock to prevent concurrent buy/sell race conditions
_player_locks: Dict[str, asyncio.Lock] = defaultdict(asyncio.Lock)

# ═══════════════════════════════════════════════════════════════
#  BANKS
# ═══════════════════════════════════════════════════════════════
BANKS = {
    "bharat": {
        "name":    "Bharat Bank",
        "limit":   90_000,
        "options": [20_000, 40_000, 60_000, 90_000],
        "rate":    0.09,    # fallback flat rate if tiers are ever missing
        # Tiered by OUTSTANDING BALANCE at round-end: bigger balance = higher rate.
        # (threshold, rate) pairs, evaluated in order — first threshold >= balance wins.
        "rate_tiers": [(20_000, 0.07), (40_000, 0.09), (60_000, 0.11), (90_000, 0.13)],
        "desc":    "Safe, government-backed. Low rate, low limit — but borrow near the cap and the rate climbs too.",
    },
    "vcx": {
        "name":    "VentureCapX",
        "limit":   1_50_000,
        "options": [50_000, 75_000, 1_00_000, 1_50_000],
        "rate":    0.13,
        "rate_tiers": [(50_000, 0.10), (75_000, 0.13), (1_00_000, 0.16), (1_50_000, 0.19)],
        "desc":    "Aggressive growth lender. Higher limit, higher cost — and it gets steeper the more you take.",
    },
    "shadow": {
        "name":    "ShadowCredit",
        "limit":   3_00_000,
        "options": [1_00_000, 1_50_000, 2_00_000, 3_00_000],
        "rate":    0.20,
        "rate_tiers": [(1_00_000, 0.16), (1_50_000, 0.20), (2_00_000, 0.25), (3_00_000, 0.30)],
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
SECTORS = {
    "Technology":        ["nexus"],
    "Banking":           ["pioneer"],
    "Pharma":            ["genesis"],
    "Automobile":        ["apex"],
    "Renewable Energy":  ["vortex"],
    "FMCG":              ["aura"],
    "Infrastructure":    ["skyline"],
    "Telecom":           ["pulse"],
}

# ═══════════════════════════════════════════════════════════════
#  VOLATILITY PROFILES  (min_drift, max_drift, down_bias)
#  down_bias > 0.5  →  stock drifts down more often (higher risk)
#  These are the company's baseline "character" — actual moves also scale
#  with the stock's current price (see PRICE_VOL_REFERENCE below), so an
#  expensive stock swings harder in rupee terms than these fractions alone
#  would suggest.
# ═══════════════════════════════════════════════════════════════
COMPANY_VOL = {
    "nexus":    (0.010, 0.035, 0.46),   # Medium-High — global tech, forex/visa exposure
    "pioneer":  (0.006, 0.022, 0.47),   # Medium — bank, rate-sensitive
    "genesis":  (0.012, 0.045, 0.45),   # Medium-High — binary regulatory/FDA risk
    "apex":     (0.018, 0.060, 0.44),   # High — capital-intensive EV pivot bet
    "vortex":   (0.014, 0.048, 0.45),   # Medium-High — capex-heavy, tender-dependent
    "aura":     (0.003, 0.012, 0.49),   # Low — defensive FMCG anchor
    "skyline":  (0.025, 0.075, 0.43),   # Very High — lumpy infra order book
    "pulse":    (0.011, 0.040, 0.46),   # Medium-High — tariff/regulatory sensitive
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

# FY26 dividend/share (₹), straight from the organiser dossier — used by the
# automatic Round 3 / Round 4 dividend events (chaos schedule, see start_round).
DIVIDEND_PER_SHARE = {
    "nexus": 13, "pioneer": 5.5, "genesis": 18, "apex": 4, "aura": 7.5,
    "vortex": 3, "skyline": 5, "pulse": 2,
}

# ── Automatic Round-by-Round chaos schedule ───────────────────────────────
# Round 1: nothing — a clean, normal round so players learn the mechanics.
# Round 2: Vortex Clean Energy lists (New Listing).
# Round 3: Skyline Infraprojects lists (New Listing) + dividend payout at round start.
# Round 4: dividend payout at round start + an acquisition rumour (Nexus/Pulse,
#          matching the pre-written MERGER_PAIRS story) fires once ~15 minutes
#          remain in the round, correlating their prices for the rest of the game.
_BG_TASKS: set = set()
ROUND4_ACQUISITION_PAIR = ("nexus", "pulse")

# Price floors per company (20% of starting price — prevents absurd crashes)
PRICE_FLOORS = {
    "nexus": 92, "pioneer": 57, "genesis": 79, "apex": 104,
    "vortex": 62, "aura": 33, "skyline": 122, "pulse": 51,
    "debtfund": 90, "balancedfund": 110,
}

# ═══════════════════════════════════════════════════════════════
#  BASE COMPANIES — live and tradeable from Round 1.
#  Bios are condensed from the full organiser dossier (see uploaded doc) —
#  not shown in the buy/sell trade view anymore, but kept in the data model
#  for host reference and the News/Guide tabs.
# ═══════════════════════════════════════════════════════════════
BASE_COMPANIES = {
    "nexus": {
        "name": "Nexus Technologies Ltd.", "sector": "Technology", "risk": "Medium-High",
        "price": 460,
        "bio": ("A mid-tier IT services challenger, founded 2001, that made its name underbidding the "
                "big players and delivering anyway. About 68% of revenue comes from US clients, so it "
                "lives and dies by American budgets, the rupee-dollar rate, and whichever way visa "
                "policy swings this year. Pushing hard into AI services now."),
        "trait": "Scrappy IT challenger, exposed to every US budget cycle.",
    },
    "pioneer": {
        "name": "Pioneer Trust Bank Ltd.", "sector": "Banking", "risk": "Medium",
        "price": 285,
        "bio": ("A private-sector bank built on conservative lending and an unusually strong low-cost "
                "deposit base. Its digital lending/NBFC arm is the fast-growing part of the story. "
                "Reliable until a rate cycle or a credit scare says otherwise."),
        "trait": "Boring lending book, exciting digital arm.",
    },
    "genesis": {
        "name": "Genesis Life Sciences Ltd.", "sector": "Pharma", "risk": "Medium-High",
        "price": 395,
        "bio": ("A pharma major with a large generics export business and a newer vaccine manufacturing "
                "line. The kind of stock that can jump or crater on a single FDA inspection report or "
                "approval letter — regulatory risk as a personality trait."),
        "trait": "One FDA letter away from a very different stock.",
    },
    "apex": {
        "name": "Apex Mobility Ltd.", "sector": "Automobile", "risk": "High",
        "price": 520,
        "bio": ("A legacy two-wheeler manufacturer pouring everything into an EV pivot. Government "
                "subsidy policy and its own execution are doing all the work here — this either becomes "
                "the mobility story of the decade or a very expensive lesson in capital allocation."),
        "trait": "Betting the whole company on the EV transition.",
    },
    "aura": {
        "name": "Aura Daily Essentials Ltd.", "sector": "FMCG", "risk": "Low",
        "price": 165,
        "bio": ("An old-guard FMCG name selling the household staples nobody stops buying, recession or "
                "not. Deliberately unexciting — this is the stock for people who'd rather sleep at night "
                "than chase a headline."),
        "trait": "The anchor. Steady on purpose.",
    },
    "pulse": {
        "name": "Pulse Telecom Ltd.", "sector": "Telecom", "risk": "Medium-High",
        "price": 255,
        "bio": ("A telecom operator in the middle of a slow, real recovery — but still one tariff hike, "
                "spectrum auction, or AGR-style regulatory demand away from a very bad quarter."),
        "trait": "Recovering, but regulation holds the leash.",
    },
}

# ═══════════════════════════════════════════════════════════════
#  NEW LISTINGS — held back from Round 1, added mid-game via the host's
#  "New Listing" trigger (reuses the same mechanic that used to be called
#  IPO_COMPANIES/ipo_drop — kept internally for minimal code churn, but
#  every player-facing label says "New Listing", not "IPO", since these are
#  established companies newly listing on this exchange, not startups going
#  public for the first time).
# ═══════════════════════════════════════════════════════════════
IPO_COMPANIES = {
    "vortex": {
        "name": "Vortex Clean Energy Ltd.", "sector": "Renewable Energy", "risk": "Medium-High",
        "price": 310,
        "bio": ("A solar and wind independent power producer with a green-hydrogen pilot underway. "
                "Capital-intensive and tender-dependent, but riding the renewable-energy policy tailwind "
                "as hard as it can."),
        "trait": "Newly listed. Rides the green-energy wave.",
    },
    "skyline": {
        "name": "Skyline Infraprojects Ltd.", "sector": "Infrastructure", "risk": "Very High",
        "price": 610,
        "bio": ("An infrastructure developer with a famously lumpy order book — a single contract win "
                "or loss can move this stock double digits in a day. Debt-heavy, execution-dependent, "
                "not for anyone who needs to sleep well."),
        "trait": "Newly listed. One contract from a double-digit swing.",
    },
}

# ═══════════════════════════════════════════════════════════════
#  SAFE-ROUTE INVESTMENTS — mutual funds (steady, low-volatility).
# ═══════════════════════════════════════════════════════════════
FUNDS = {
    "debtfund": {
        "name": "Bharat Debt Fund", "sector": "Mutual Fund", "risk": "Very Low", "price": 100,
        "is_fund": True,
        "bio": (
            "A plain, boring debt fund holding government bonds and top-rated corporate paper. "
            "It will not make you rich. It will also not ruin you. If you just want somewhere to park "
            "cash between bets without watching it evaporate, this is it."
        ),
        "trait": "The parking lot for your cash.",
    },
    "balancedfund": {
        "name": "Balanced Growth Fund", "sector": "Mutual Fund", "risk": "Low", "price": 150,
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
#  SECTOR ETFS — intentionally empty. With one company per sector in this
#  roster, a "sector ETF" would just be a 1:1 mirror of a single stock, which
#  isn't a real instrument. Left as an empty dict (rather than removed) so
#  every piece of code that loops over SECTOR_ETFS.items() still works —
#  it just does nothing, safely.
# ═══════════════════════════════════════════════════════════════
SECTOR_ETFS = {}

# ═══════════════════════════════════════════════════════════════
#  COMPANY MERGERS — curated pairs only, each with its own resulting name.
#  Keyed by "cid1|cid2" with cid1 < cid2 alphabetically.
# ═══════════════════════════════════════════════════════════════
def _mkey(a: str, b: str) -> str:
    return "|".join(sorted([a, b]))

MERGER_PAIRS = {
    _mkey("nexus", "pulse"): {
        "name": "Nexus Pulse Communications", "sector": "Technology", "risk": "Medium-High",
        "bio": ("Nexus's IT services stack merged with Pulse's telecom network — the pitch is "
                "vertically integrated digital infrastructure, from the network layer up to the "
                "software running on it. One combined balance sheet, two regulatory regimes to answer to."),
        "trait": "The network and the software running on it.",
    },
    _mkey("apex", "skyline"): {
        "name": "Apex Skyline Infrastructure", "sector": "Infrastructure", "risk": "Very High",
        "bio": ("Apex's EV manufacturing scale combined with Skyline's infrastructure execution arm — "
                "aimed squarely at building the charging and logistics infrastructure its own vehicles "
                "will need. Ambitious. Also now carries both companies' execution risk in one stock."),
        "trait": "Builds the vehicles and the roads they need.",
    },
    _mkey("pioneer", "pulse"): {
        "name": "Pioneer Pulse Digital Finance", "sector": "Banking", "risk": "Medium-High",
        "bio": ("Pioneer's lending book paired with Pulse's telecom distribution reach, aimed at "
                "mobile-first digital banking and payments for a customer base neither could fully "
                "reach alone."),
        "trait": "Banking, distributed over the phone network.",
    },
    _mkey("genesis", "vortex"): {
        "name": "Genesis Vortex Sciences", "sector": "Pharma", "risk": "Medium-High",
        "bio": ("Genesis's manufacturing footprint now runs partly on Vortex's renewable power assets — "
                "a sustainability story as much as an industrial one. Analysts like the ESG angle; "
                "they also note it's still two very different businesses sharing a ticker."),
        "trait": "Pharma manufacturing, powered by its own renewables.",
    },
    _mkey("aura", "pioneer"): {
        "name": "Aura Pioneer Consumer Finance", "sector": "FMCG", "risk": "Medium",
        "bio": ("Aura's retail distribution network combined with Pioneer's lending arm, aimed at "
                "consumer credit at the point of sale — buy-now-pay-later for household staples, "
                "essentially. Steady meets steady."),
        "trait": "Groceries, now with financing attached.",
    },
}


#  NEWS POOL
# ═══════════════════════════════════════════════════════════════
NEWS_POOL = [
    # ── NEXUS (6) ──────────────────────────────────────────────────────────
    {"type_tag":"verified",   "label":"Market Event",      "affects":"nexus", "direction": 1, "strength":0.11, "real":True,
     "text":"Nexus Technologies signs a multi-year $180M deal with a US healthcare major, its largest contract win in three years."},
    {"type_tag":"verified",   "label":"Market Event",      "affects":"nexus", "direction": 1, "strength":0.08, "real":True,
     "text":"Nexus's new AI-services division posts its first profitable quarter, ahead of internal targets."},
    {"type_tag":"verified",   "label":"Market Event",      "affects":"nexus", "direction":-1, "strength":0.10, "real":True,
     "text":"A key US client trims its contract with Nexus by 20%, citing its own budget cuts."},
    {"type_tag":"verified",   "label":"Market Event",      "affects":"nexus", "direction":-1, "strength":0.09, "real":True,
     "text":"Visa delays for Nexus's onsite US consultants disrupt delivery timelines on two large accounts."},

    # ── PIONEER (6) ────────────────────────────────────────────────────────
    {"type_tag":"verified",   "label":"Market Event",      "affects":"pioneer", "direction": 1, "strength":0.08, "real":True,
     "text":"Pioneer Trust Bank's digital lending arm crosses ₹10,000 crore in disbursals, six months ahead of guidance."},
    {"type_tag":"verified",   "label":"Market Event",      "affects":"pioneer", "direction": 1, "strength":0.07, "real":True,
     "text":"Credit rating agency upgrades Pioneer Trust Bank, citing a strengthening low-cost deposit base."},
    {"type_tag":"verified",   "label":"Market Event",      "affects":"pioneer", "direction":-1, "strength":0.09, "real":True,
     "text":"Pioneer Trust Bank flags a rise in bad loans from its SME lending book this quarter."},
    {"type_tag":"verified",   "label":"Market Event",      "affects":"pioneer", "direction":-1, "strength":0.07, "real":True,
     "text":"RBI tightens provisioning norms for digital lenders — Pioneer's NBFC arm directly affected."},

    # ── GENESIS (6) ────────────────────────────────────────────────────────
    {"type_tag":"verified",   "label":"Market Event",      "affects":"genesis", "direction": 1, "strength":0.13, "real":True,
     "text":"Genesis Life Sciences receives US FDA approval for a key generic drug, clearing the way for exports."},
    {"type_tag":"verified",   "label":"Market Event",      "affects":"genesis", "direction": 1, "strength":0.10, "real":True,
     "text":"Genesis's new vaccine facility completes a clean regulatory inspection with zero observations."},
    {"type_tag":"verified",   "label":"Market Event",      "affects":"genesis", "direction":-1, "strength":0.13, "real":True,
     "text":"Genesis Life Sciences receives an FDA warning letter over quality-control lapses at one plant."},
    {"type_tag":"verified",   "label":"Market Event",      "affects":"genesis", "direction":-1, "strength":0.09, "real":True,
     "text":"A patent dispute delays Genesis's launch of a high-value generic drug in a key export market."},

    # ── APEX (6) ───────────────────────────────────────────────────────────
    {"type_tag":"verified",   "label":"Market Event",      "affects":"apex", "direction": 1, "strength":0.14, "real":True,
     "text":"Apex Mobility's EV sales cross 50,000 units for the quarter, beating its own guidance comfortably."},
    {"type_tag":"verified",   "label":"Market Event",      "affects":"apex", "direction": 1, "strength":0.10, "real":True,
     "text":"Government extends EV purchase subsidies for another two years — a direct tailwind for Apex Mobility."},
    {"type_tag":"verified",   "label":"Market Event",      "affects":"apex", "direction":-1, "strength":0.14, "real":True,
     "text":"Apex Mobility recalls a batch of its flagship EV model over a battery safety concern."},
    {"type_tag":"verified",   "label":"Market Event",      "affects":"apex", "direction":-1, "strength":0.11, "real":True,
     "text":"Apex Mobility's legacy two-wheeler sales slump as the EV pivot eats into factory capacity."},

    # ── AURA (6) ───────────────────────────────────────────────────────────
    {"type_tag":"verified",   "label":"Market Event",      "affects":"aura", "direction": 1, "strength":0.05, "real":True,
     "text":"Aura Daily Essentials posts steady same-store sales growth on strong festive-season demand."},
    {"type_tag":"verified",   "label":"Market Event",      "affects":"aura", "direction": 1, "strength":0.04, "real":True,
     "text":"Falling input costs ease margin pressure across Aura's household staples portfolio."},
    {"type_tag":"verified",   "label":"Market Event",      "affects":"aura", "direction":-1, "strength":0.05, "real":True,
     "text":"A weak rural demand quarter dents volumes for Aura Daily Essentials outside metro markets."},
    {"type_tag":"verified",   "label":"Market Event",      "affects":"aura", "direction":-1, "strength":0.04, "real":True,
     "text":"A newer, cheaper competitor gains shelf space at Aura's expense in a key product category."},

    # ── SKYLINE (6) ────────────────────────────────────────────────────────
    {"type_tag":"verified",   "label":"Market Event",      "affects":"skyline", "direction": 1, "strength":0.18, "real":True,
     "text":"Skyline Infraprojects wins a ₹4,200 crore highway contract, its largest single order this year."},
    {"type_tag":"verified",   "label":"Market Event",      "affects":"skyline", "direction": 1, "strength":0.13, "real":True,
     "text":"Skyline Infraprojects completes a flagship project ahead of schedule, unlocking a performance bonus."},
    {"type_tag":"verified",   "label":"Market Event",      "affects":"skyline", "direction":-1, "strength":0.18, "real":True,
     "text":"Skyline Infraprojects loses a major tender to a rival bidder after a sharp price undercut."},
    {"type_tag":"verified",   "label":"Market Event",      "affects":"skyline", "direction":-1, "strength":0.14, "real":True,
     "text":"Cost overruns force Skyline Infraprojects to write down a stalled project."},

    # ── PULSE (6) ──────────────────────────────────────────────────────────
    {"type_tag":"verified",   "label":"Market Event",      "affects":"pulse", "direction": 1, "strength":0.10, "real":True,
     "text":"Pulse Telecom raises tariffs across prepaid plans, its first hike in two years — margins expected to improve."},
    {"type_tag":"verified",   "label":"Market Event",      "affects":"pulse", "direction": 1, "strength":0.08, "real":True,
     "text":"Pulse Telecom adds its highest quarterly subscriber count in three years."},
    {"type_tag":"verified",   "label":"Market Event",      "affects":"pulse", "direction":-1, "strength":0.11, "real":True,
     "text":"Government raises spectrum usage charges — a direct cost hit to Pulse Telecom's balance sheet."},
    {"type_tag":"verified",   "label":"Market Event",      "affects":"pulse", "direction":-1, "strength":0.09, "real":True,
     "text":"Pulse Telecom faces a fresh AGR-related dues demand from the telecom regulator."},

    # ── VORTEX (5, listed later — but present in the pool once it lists) ──
    {"type_tag":"verified",   "label":"Market Event",      "affects":"vortex", "direction": 1, "strength":0.12, "real":True,
     "text":"Vortex Clean Energy wins a 400MW solar tender, its largest single award to date."},
    {"type_tag":"verified",   "label":"Market Event",      "affects":"vortex", "direction": 1, "strength":0.09, "real":True,
     "text":"Falling solar panel import costs improve project economics across Vortex Clean Energy's pipeline."},
    {"type_tag":"verified",   "label":"Market Event",      "affects":"vortex", "direction":-1, "strength":0.12, "real":True,
     "text":"Land acquisition delays push back Vortex Clean Energy's flagship wind project by two quarters."},

    # ── SKYLINE listed separately above; ARMOR/etc removed — pool complete.

    # ── UNVERIFIED RUMOURS: 4 per company. Realness is independent of direction and wording,
    #    so nothing in the headline gives away whether it will actually play out. ──
    {"type_tag":"verified",   "label":"Market Event",      "affects":"vortex", "direction":-1, "strength":0.10, "real":True,
     "text":"A fresh slump in global solar panel prices squeezes margins on equipment Vortex Clean Energy imported earlier at higher costs."},
    {"type_tag":"unverified", "label":"Unverified Rumour", "affects":"nexus", "direction":1, "strength":0.09, "real":True,
     "text":"Whispers on the floor: Nexus is preparing a bid for a mid-sized European IT firm."},
    {"type_tag":"unverified", "label":"Unverified Rumour", "affects":"nexus", "direction":-1, "strength":0.08, "real":True,
     "text":"Word is a US visa policy review may land harder on mid-tier outsourcers like Nexus than expected."},
    {"type_tag":"unverified", "label":"Unverified Rumour", "affects":"nexus", "direction":1, "strength":0.08, "real":False,
     "text":"Chatter: Nexus is about to announce a second ₹2,000 crore-plus AI contract with a US insurer."},
    {"type_tag":"unverified", "label":"Unverified Rumour", "affects":"nexus", "direction":-1, "strength":0.09, "real":False,
     "text":"Talk of a fresh whistleblower complaint at Nexus over visa compliance."},
    {"type_tag":"unverified", "label":"Unverified Rumour", "affects":"pioneer", "direction":1, "strength":0.08, "real":True,
     "text":"Buzz: Pioneer Trust Bank is close to acquiring a small NBFC to add to its vehicle-loan arm."},
    {"type_tag":"unverified", "label":"Unverified Rumour", "affects":"pioneer", "direction":-1, "strength":0.07, "real":True,
     "text":"Word is RBI is unhappy with parts of Pioneer's digital-lending partnership set-up."},
    {"type_tag":"unverified", "label":"Unverified Rumour", "affects":"pioneer", "direction":1, "strength":0.07, "real":False,
     "text":"Chatter: Pioneer is set to announce a surprise special dividend."},
    {"type_tag":"unverified", "label":"Unverified Rumour", "affects":"pioneer", "direction":-1, "strength":0.08, "real":False,
     "text":"Talk that Pioneer must raise capital at a steep discount to the current price."},
    {"type_tag":"unverified", "label":"Unverified Rumour", "affects":"genesis", "direction":1, "strength":0.1, "real":True,
     "text":"Whispers: Genesis is close to in-licensing a promising biosimilar from a global developer."},
    {"type_tag":"unverified", "label":"Unverified Rumour", "affects":"genesis", "direction":-1, "strength":0.09, "real":True,
     "text":"Word is the pending FDA re-inspection of Genesis's third facility is not going smoothly."},
    {"type_tag":"unverified", "label":"Unverified Rumour", "affects":"genesis", "direction":1, "strength":0.09, "real":False,
     "text":"Chatter: Genesis is about to win a large new vaccine contract from a Gulf government."},
    {"type_tag":"unverified", "label":"Unverified Rumour", "affects":"genesis", "direction":-1, "strength":0.1, "real":False,
     "text":"Talk that a supply arbitration in Africa is about to be decided against Genesis."},
    {"type_tag":"unverified", "label":"Unverified Rumour", "affects":"apex", "direction":1, "strength":0.11, "real":True,
     "text":"Buzz: Apex's battery-cell joint venture may begin trial production earlier than planned."},
    {"type_tag":"unverified", "label":"Unverified Rumour", "affects":"apex", "direction":-1, "strength":0.11, "real":True,
     "text":"Word is a foreign EV brand is about to announce its India entry with aggressive pricing."},
    {"type_tag":"unverified", "label":"Unverified Rumour", "affects":"apex", "direction":1, "strength":0.1, "real":False,
     "text":"Chatter: Apex has landed a huge export order for electric two-wheelers."},
    {"type_tag":"unverified", "label":"Unverified Rumour", "affects":"apex", "direction":-1, "strength":0.1, "real":False,
     "text":"Talk of a second battery-related recall being quietly prepared at Apex."},
    {"type_tag":"unverified", "label":"Unverified Rumour", "affects":"vortex", "direction":1, "strength":0.09, "real":True,
     "text":"Whispers: Vortex is close to signing a green-hydrogen off-take agreement."},
    {"type_tag":"unverified", "label":"Unverified Rumour", "affects":"vortex", "direction":-1, "strength":0.09, "real":True,
     "text":"Word is the government may raise solar import duties again, raising Vortex's project costs."},
    {"type_tag":"unverified", "label":"Unverified Rumour", "affects":"vortex", "direction":1, "strength":0.08, "real":False,
     "text":"Chatter: Vortex has won the big state PPA tender it was rumoured to be bidding for."},
    {"type_tag":"unverified", "label":"Unverified Rumour", "affects":"vortex", "direction":-1, "strength":0.08, "real":False,
     "text":"Talk that Vortex's lenders are about to tighten terms on its debt."},
    {"type_tag":"unverified", "label":"Unverified Rumour", "affects":"aura", "direction":1, "strength":0.05, "real":True,
     "text":"Buzz: Aura is looking at buying a challenger D2C brand to bolster its portfolio."},
    {"type_tag":"unverified", "label":"Unverified Rumour", "affects":"aura", "direction":-1, "strength":0.05, "real":True,
     "text":"Word is a GST slab reclassification could hit one of Aura's core product categories."},
    {"type_tag":"unverified", "label":"Unverified Rumour", "affects":"aura", "direction":1, "strength":0.04, "real":False,
     "text":"Chatter: Aura is about to announce a big buyback."},
    {"type_tag":"unverified", "label":"Unverified Rumour", "affects":"aura", "direction":-1, "strength":0.05, "real":False,
     "text":"Talk that Aura is planning steep price hikes across its soaps range."},
    {"type_tag":"unverified", "label":"Unverified Rumour", "affects":"skyline", "direction":1, "strength":0.11, "real":True,
     "text":"Whispers: Skyline is the frontrunner for a large metro-adjacent tender."},
    {"type_tag":"unverified", "label":"Unverified Rumour", "affects":"skyline", "direction":-1, "strength":0.11, "real":True,
     "text":"Word is the court is leaning against Skyline in its land-dispute case."},
    {"type_tag":"unverified", "label":"Unverified Rumour", "affects":"skyline", "direction":1, "strength":0.1, "real":False,
     "text":"Chatter: Skyline is about to close a huge pre-sale of its tier-2 commercial towers."},
    {"type_tag":"unverified", "label":"Unverified Rumour", "affects":"skyline", "direction":-1, "strength":0.1, "real":False,
     "text":"Talk that Skyline's lenders may pull back after the last restructuring."},
    {"type_tag":"unverified", "label":"Unverified Rumour", "affects":"pulse", "direction":1, "strength":0.08, "real":True,
     "text":"Buzz: Pulse is in talks to sell a further stake in its tower subsidiary."},
    {"type_tag":"unverified", "label":"Unverified Rumour", "affects":"pulse", "direction":-1, "strength":0.09, "real":True,
     "text":"Word is a fourth spectrum auction is coming with a steep reserve price."},
    {"type_tag":"unverified", "label":"Unverified Rumour", "affects":"pulse", "direction":1, "strength":0.08, "real":False,
     "text":"Chatter: Pulse's next tariff hike is set to be far bigger than the market expects."},
    {"type_tag":"unverified", "label":"Unverified Rumour", "affects":"pulse", "direction":-1, "strength":0.09, "real":False,
     "text":"Talk that a rival is about to trigger a fresh tariff war."},
]

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
                bankruptcy_count INTEGER DEFAULT 0
            )
        """)
        # Migration for DBs created by an older version of this schema — add any
        # column that doesn't exist yet. Harmless no-op on a fresh database.
        existing_cols = {row[1] for row in await (await db.execute("PRAGMA table_info(players)")).fetchall()}
        migrations = [
            ("stop_losses",              "TEXT DEFAULT '{}'"),
            ("insurance",                "TEXT DEFAULT '{}'"),
            ("rate_locks",               "TEXT DEFAULT '{}'"),
            ("realized_pnl_round",       "REAL DEFAULT 0"),
            ("realized_pnl_total",       "REAL DEFAULT 0"),
            ("stt_accrued_round",        "REAL DEFAULT 0"),
            ("trades_this_round",        "INTEGER DEFAULT 0"),
            ("net_worth_at_round_start", "REAL DEFAULT 0"),
            ("bankruptcy_count",         "INTEGER DEFAULT 0"),
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
    companies.update({k: {**v, "prev_price": v["price"], "target_price": v["price"]} for k, v in SECTOR_ETFS.items()})
    for etf_id, etf_cfg in SECTOR_ETFS.items():
        companies[etf_id]["_baseline_avg"] = _etf_sector_avg(companies, etf_cfg["tracks_sectors"])
    return {
        "phase":              "lobby",
        "round":              0,
        "round_end_time":     None,
        "break_end_time":     None,
        "break_duration":     BREAK_DURATION,
        "companies":          companies,
        "ipo_listed":         [],
        "news":               [],
        "news_used":          [],
        "regulatory_freeze":  None,
        "acquisition_pair":   None,
        "credit_crunch":      False,
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
        "frozen":   bool(row["frozen"]),
        "avg_cost": json.loads(row["avg_cost"]),
        "bm_log":   json.loads(row["bm_log"]),
        "stop_losses":              json.loads(_col("stop_losses", "{}")),
        "insurance":                json.loads(_col("insurance", "{}")),
        "rate_locks":               json.loads(_col("rate_locks", "{}")),
        "realized_pnl_round":       _col("realized_pnl_round", 0) or 0,
        "realized_pnl_total":       _col("realized_pnl_total", 0) or 0,
        "stt_accrued_round":        _col("stt_accrued_round", 0) or 0,
        "trades_this_round":        _col("trades_this_round", 0) or 0,
        "net_worth_at_round_start": _col("net_worth_at_round_start", 0) or 0,
        "bankruptcy_count":         _col("bankruptcy_count", 0) or 0,
    }


async def save_player(p: dict):
    async with aiosqlite.connect(DB_PATH, timeout=5.0) as db:
        await db.execute(
            """INSERT OR REPLACE INTO players
               (code,name,cash,holdings,loans,frozen,avg_cost,bm_log,
                stop_losses,insurance,rate_locks,realized_pnl_round,realized_pnl_total,
                stt_accrued_round,trades_this_round,net_worth_at_round_start,bankruptcy_count)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                p["code"], p.get("name"), p["cash"],
                json.dumps(p["holdings"]),
                json.dumps(p.get("loans", {})),
                int(p.get("frozen", False)),
                json.dumps(p.get("avg_cost", {})),
                json.dumps(p.get("bm_log", [])),
                json.dumps(p.get("stop_losses", {})),
                json.dumps(p.get("insurance", {})),
                json.dumps(p.get("rate_locks", {})),
                p.get("realized_pnl_round", 0) or 0,
                p.get("realized_pnl_total", 0) or 0,
                p.get("stt_accrued_round", 0) or 0,
                p.get("trades_this_round", 0) or 0,
                p.get("net_worth_at_round_start", 0) or 0,
                p.get("bankruptcy_count", 0) or 0,
            ),
        )
        await db.commit()


def player_loans_total(p: dict) -> float:
    return sum(p.get("loans", {}).values())


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
        "frozen":       p["frozen"],
        "net_worth":    round(net_worth),
        "portfolio":    portfolio,
        "portfolio_value":    round(port_value),
        "realized_pnl_round": round(p.get("realized_pnl_round", 0)),
        "realized_pnl_total": round(p.get("realized_pnl_total", 0)),
        "stt_accrued_round":  round(p.get("stt_accrued_round", 0)),
        "stop_losses":  p.get("stop_losses", {}),
        "insurance":    p.get("insurance", {}),
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


async def broadcast_prices(state: dict):
    players = await all_players()
    board   = leaderboard(players, state)
    prices  = {k: c["price"] for k, c in state["companies"].items()}
    msg = {"type": "prices_bulk", "prices": prices, "board": board}
    await manager.broadcast_all(msg)
    await manager.broadcast_hosts(msg)


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
    freeze    = state.get("regulatory_freeze")
    acq_pair  = state.get("acquisition_pair")
    moved: dict[str, float] = {}

    for cid, c in companies.items():
        c["prev_price"] = c["price"]
        if freeze and c.get("sector") == freeze:
            continue
        lo, hi, bias = COMPANY_VOL.get(cid, (0.02, 0.06, 0.45))
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
                    if freeze and companies[peer].get("sector") == freeze:
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
    if not c or c.get("is_etf") or c.get("is_fund"):
        return 0.0
    return min(ELASTICITY_MAX_IMPACT, ELASTICITY_FACTOR * (qty * price / ELASTICITY_REF_VALUE))


def apply_trade_elasticity(state: dict, cid: str, qty: int, price: float, is_buy: bool) -> None:
    """A buy nudges the stock's price up, a sell nudges it down — bigger
    trades (and higher trade values) move it more, up to a per-trade cap.
    Mutates state["companies"][cid] in place; caller is responsible for
    write_state() afterwards."""
    c = state["companies"].get(cid)
    if not c or c.get("is_etf") or c.get("is_fund"):
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


def _etf_sector_avg(companies: dict, sectors: list) -> float:
    """Average current price of every listed, non-fund, non-ETF company in the given sectors."""
    prices = [c["price"] for c in companies.values()
              if c.get("sector") in sectors and not c.get("is_etf") and not c.get("is_fund")]
    return (sum(prices) / len(prices)) if prices else 1.0

def _update_etf_prices(companies: dict) -> None:
    """ETFs don't random-walk — their price tracks a basket of real companies."""
    for etf_id, etf_cfg in SECTOR_ETFS.items():
        c = companies.get(etf_id)
        if not c:
            continue
        baseline = c.get("_baseline_avg") or 1.0
        current_avg = _etf_sector_avg(companies, etf_cfg["tracks_sectors"])
        floor = PRICE_FLOORS.get(etf_id, 10)
        new_price = max(floor, round(etf_cfg["price"] * (current_avg / baseline)))
        c["prev_price"]   = c["price"]
        c["price"]        = new_price
        c["target_price"] = new_price

AMBIENT_NEWS_GAP      = 150    # seconds between auto-generated 'explainer' headlines
AMBIENT_NEWS_MIN_MAG  = 0.012  # ...and only for a queued move at least this big (1.2%)


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
                freeze    = state.get("regulatory_freeze")
                frozen_bm = state.get("price_freezes", {})
                now       = time.time()
                companies = state["companies"]

                # ── Stage 1: apply whatever was queued last cycle ──────────
                pending = state.get("pending_moves", {})
                for cid, mv in pending.items():
                    c = companies.get(cid)
                    if not c or c.get("is_etf") or c.get("is_fund"):
                        continue
                    if freeze and c.get("sector") == freeze:
                        continue
                    if frozen_bm.get(cid, 0) > now:
                        continue
                    floor = PRICE_FLOORS.get(cid, 10)
                    base  = c.get("target_price", c["price"])
                    c["target_price"] = max(floor, round(base * (1 + mv["direc"] * mv["mag"])))

                # ── Stage 2: compute next cycle's moves, queue them ────────
                new_pending = {}
                for cid, c in companies.items():
                    if c.get("is_etf") or c.get("is_fund"):
                        continue
                    if freeze and c.get("sector") == freeze:
                        continue
                    if frozen_bm.get(cid, 0) > now:
                        continue
                    lo, hi, bias = COMPANY_VOL.get(cid, (0.005, 0.03, 0.46))
                    mag   = random.uniform(lo * 0.5, hi * 0.65) * price_vol_mult(c["price"])
                    direc = 1 if random.random() > bias else -1
                    new_pending[cid] = {"direc": direc, "mag": mag}
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
                        headline_n = {
                            "id":        uuid.uuid4().hex[:8],
                            "type_tag":  "verified",
                            "label":     "Market Event",
                            "text":      text,
                            "affects":   top_cid,
                            "direction": mv["direc"],
                            "real":      True,
                            "reactions": {},
                        }
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
                freeze    = state.get("regulatory_freeze")
                frozen_bm = state.get("price_freezes", {})
                now       = time.time()
                companies = state["companies"]
                for cid, c in companies.items():
                    if c.get("is_etf"):
                        continue  # handled by _update_etf_prices below
                    if freeze and c.get("sector") == freeze:
                        continue
                    if frozen_bm.get(cid, 0) > now:
                        continue
                    target = c.get("target_price", c["price"])
                    lo, hi, _ = COMPANY_VOL.get(cid, (0.005, 0.03, 0.46))
                    jitter = (random.uniform(-lo * 0.9, lo * 0.9) or random.uniform(-0.01, 0.01)) * price_vol_mult(c["price"])
                    floor  = PRICE_FLOORS.get(cid, 10)
                    c["prev_price"] = c["price"]
                    c["price"]      = max(floor, round(target * (1 + jitter)))
                _update_etf_prices(companies)
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
            await manager.broadcast_all({
                "type":   "prices_bulk",
                "prices": {k: v["price"] for k, v in companies.items()},
                "board":  board,
            })
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


def pick_news(state: dict, count: int = 3) -> list:
    listed = set(state.get("ipo_listed", []))
    used   = set(state.get("news_used", []))
    pool   = []
    spent_groups = set(state.get("used_plot_groups", []))
    for n in NEWS_POOL:
        if n["text"] in used:
            continue
        if plot_group_of(n["text"]) in spent_groups:
            continue   # that storyline already has an outcome this game
        aff = n["affects"]
        # Skip IPO company news if not yet listed
        if aff in IPO_COMPANIES and aff not in listed:
            continue
        pool.append(n)
    if not pool:
        return []
    chosen_raw = random.sample(pool, min(count, len(pool)))
    chosen = []
    for n in chosen_raw:
        item = dict(n)  # copy — NEVER mutate the shared NEWS_POOL entries directly
        item["id"]        = uuid.uuid4().hex[:8]
        item["reactions"] = {}
        chosen.append(item)
    state["news_used"] = list(used) + [n["text"] for n in chosen_raw]
    seen_now = set()
    for n in chosen_raw:                      # one batch must not hold two outcomes of one storyline either
        g = plot_group_of(n["text"])
        if g:
            seen_now.add(g)
    if seen_now:
        state["used_plot_groups"] = list(spent_groups | seen_now)
    return chosen


async def ambient_news_loop():
    """DEPRECATED — folded into price_target_loop, which now generates a
    matching headline for the biggest mover every 20s cycle instead of this
    running on its own disconnected ~2min timer with its own separate price
    impact. Kept as a no-op stub in case anything still references it."""
    return


# ═══════════════════════════════════════════════════════════════
#  CONNECTION MANAGER
# ═══════════════════════════════════════════════════════════════
_HIDDEN_NEWS_KEYS   = ("real", "strength")            # would reveal whether a rumour is true / how big it is
_HIDDEN_COMPANY_KEYS = ("target_price", "_baseline_avg")  # the hidden fair value the price is steered toward


def public_news(n: dict) -> dict:
    return {k: v for k, v in n.items() if k not in _HIDDEN_NEWS_KEYS}


def public_companies(companies: dict) -> dict:
    return {cid: {k: v for k, v in c.items() if k not in _HIDDEN_COMPANY_KEYS} for cid, c in companies.items()}


def _player_safe(msg: dict) -> dict:
    """Strip host-only fields from anything sent to a player. Applied centrally so no
    individual broadcast site can forget it."""
    t = msg.get("type")
    if t == "news":
        return public_news(msg)
    if t == "init":
        out = dict(msg)
        if isinstance(out.get("news"), list):
            out["news"] = [public_news(n) for n in out["news"]]
        if isinstance(out.get("market"), dict):
            out["market"] = public_companies(out["market"])
        return out
    return msg


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
    asyncio.create_task(ambient_news_loop())
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
            "frozen":     p["frozen"],
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
    await manager.broadcast_all({"type": "leaderboard", "board": board})
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
        # Reset per-round chaos effects
        state["regulatory_freeze"] = None
        state["acquisition_pair"]  = None
        state["credit_crunch"]     = False
        # Clear any stale queued price moves from a previous round/break
        state["pending_moves"] = {}
        # Unfreeze all players, snapshot round-start net worth, reset per-round counters
        players = await all_players()
        for p in players:
            changed = False
            if p["frozen"]:
                p["frozen"] = False
                changed = True
            if p["name"]:
                p["net_worth_at_round_start"] = player_view(p, state)["net_worth"]
                p["trades_this_round"]        = 0
                p["realized_pnl_round"]       = 0
                changed = True
            if changed:
                await save_player(p)
        # Pick and apply news — use the pre-generated batch from the break (so an
        # Early Word purchase during that break matches what actually happens),
        # falling back to a fresh pick if none was pre-generated (e.g. Round 1).
        pending = state.pop("pending_news", None)
        if pending:
            news = pending
        else:
            news_count = 2 if state["round"] == 1 else 3
            news = pick_news(state, news_count)
        state["news"].extend(news)
        fluctuate_prices(state, news)
        # Record price history snapshot
        ph = state.setdefault("price_history", {})
        for cid, c in state["companies"].items():
            ph.setdefault(cid, []).append(c["price"])
        await write_state(state)
    players = await all_players()
    board   = leaderboard(players, state)
    await manager.broadcast_all({
        "type":          "phase_change",
        "phase":         "trading",
        "round":         state["round"],
        "round_end_time": state["round_end_time"],
        "prices":        {k: c["price"] for k, c in state["companies"].items()},
        "board":         board,
    })
    for n in news:
        await manager.broadcast_all({"type": "news", **n})
    await manager.broadcast_hosts({
        "type":  "state_update",
        "state": state,
        "board": board,
        "player_count": len([p for p in players if p["name"]]),
    })

    # ── Automatic chaos schedule for this round (see ROUND4_ACQUISITION_PAIR
    # comment above). Runs after the lock is released and the round-start
    # broadcast has already gone out, so players see prices settle first. ──
    round_num = state["round"]
    try:
        if round_num == 2:
            await _apply_ipo_drop("vortex")
        elif round_num == 3:
            await _apply_ipo_drop("skyline")
            await _apply_dividends_batch({cid: DIVIDEND_PER_SHARE[cid] for cid in ("nexus", "pioneer", "genesis", "apex", "aura")})
        elif round_num == 4:
            await _apply_dividends_batch(dict(DIVIDEND_PER_SHARE))
            cid1, cid2 = ROUND4_ACQUISITION_PAIR
            _t = asyncio.create_task(_delayed_round4_acquisition_rumour(
                ROUND_DURATION - 900, round_num, cid1, cid2  # fires with 15 min left
            ))
            _BG_TASKS.add(_t); _t.add_done_callback(_BG_TASKS.discard)   # keep a reference so it isn't garbage-collected
    except Exception as e:   # the round has already started — never turn a chaos hiccup into a failed request
        print(f"[start_round] automatic chaos event failed (round {round_num}): {e}")

    return {"ok": True, "round": state["round"]}


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
        state["regulatory_freeze"] = None
        state["acquisition_pair"]  = None
        # Apply per-bank compounding interest
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
                    if state.get("credit_crunch"):
                        rate += 0.05
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
        state["credit_crunch"] = False

        # ── STT (Securities Transaction Tax): 0.2% of every trade's value,
        # accrued live on every buy/sell (see the ws buy/sell handlers), and
        # actually charged here at round end. Income tax is NOT charged per
        # round anymore — only once, at end_game, on the whole game's realized
        # gains. Wealth tax still applies every round to whoever's in 1st. ──
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
                if wealth_tax: parts.append(f"Wealth tax ₹{wealth_tax:,} (you're #1)")
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

        # ── Insurance: pay out policies that are still valid and underwater ──
        for p in players:
            ins = p.get("insurance") or {}
            if not ins:
                continue
            payouts = []
            for cid, pol in list(ins.items()):
                held  = p.get("holdings", {}).get(cid, 0)
                c     = state["companies"].get(cid)
                covered_qty = min(pol["qty"], held)
                if c and covered_qty > 0 and c["price"] < pol["avg_cost_locked"]:
                    loss_per_share = pol["avg_cost_locked"] - c["price"]
                    payout = round(loss_per_share * covered_qty * INSURANCE_COVERAGE_PCT)
                    if payout > 0:
                        p["cash"] += payout
                        payouts.append({"stock": cid, "name": c["name"], "payout": payout})
                del ins[cid]  # policies always expire at round end, win or not
            p["insurance"] = ins
            if payouts:
                await save_player(p)
                lines = "; ".join(f"₹{pay['payout']:,} on {pay['name']}" for pay in payouts)
                await manager.send_player(p["code"], {
                    "type": "player_update", "player": player_view(p, state),
                    "msg":  f"🛡️ Insurance payout: {lines}",
                })

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
        # Pre-generate next round's news now, so an Early Word purchase during this
        # break reveals the SAME headlines that will actually run at start_round.
        next_round_num       = state["round"] + 1
        next_news_count       = 2 if next_round_num == 1 else 3
        state["pending_news"] = pick_news(state, next_news_count)
        await write_state(state)
    players = await all_players()
    board   = leaderboard(players, state)
    await manager.broadcast_all({
        "type":           "phase_change",
        "phase":          "break",
        "round":          state["round"],
        "board":          board,
        "break_end_time": state["break_end_time"],
        "break_duration": state["break_duration"],
    })
    await manager.broadcast_all({"type": "round_summary", "summary": round_summary})
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

        # ── Force-liquidate everything so net worth becomes pure cash and
        # this round's gains (including whatever's still on the board) can
        # actually be taxed cleanly. Order matters: insurance needs to see
        # what you still hold BEFORE that holding gets force-sold. ─────────
        for p in players:
            if not p["name"]:
                continue
            changed = False

            # 1) Resolve any still-open insurance policies (same rule as a
            # normal round end: pays out if still underwater and still held).
            ins = p.get("insurance") or {}
            if ins:
                for cid, pol in list(ins.items()):
                    held = p.get("holdings", {}).get(cid, 0)
                    c    = companies.get(cid)
                    covered_qty = min(pol["qty"], held)
                    if c and covered_qty > 0 and c["price"] < pol["avg_cost_locked"]:
                        loss_per_share = pol["avg_cost_locked"] - c["price"]
                        payout = round(loss_per_share * covered_qty * INSURANCE_COVERAGE_PCT)
                        if payout > 0:
                            p["cash"] += payout
                    del ins[cid]
                p["insurance"] = ins
                changed = True

            # 2) Sell every held stock at its current price
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

        # 3) FINAL tax pass — the only time income tax is ever charged.
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
    rank_of       = {r["name"]: r["rank"] for r in board}
    for p in players:
        if not p["name"]:
            continue
        t  = final_by_name.get(p["name"], {})
        pv = player_view(p, state)
        # Sent BEFORE game_ended so the client already has it when the results screen opens.
        await manager.send_player(p["code"], {"type": "final_summary", "summary": {
            "rank":                 rank_of.get(p["name"]),
            "players":              len(rank_of),
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
    await manager.broadcast_all({"type": "game_ended", "board": board})
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
        {"text": n["text"], "real": bool(n.get("real")), "affects": n.get("affects")}
        for n in state.get("news", []) if n.get("type_tag") == "unverified" and n.get("real") is not None
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
        is_verified = data.get("verified", True)
        is_real     = is_verified  # verified always moves; unverified may or may not
        strength    = safe_float(data.get("strength"), 0.10)
        affects     = data["affects"]
        direction   = data.get("direction", 1)
        text        = re.sub(r"[<>]", "", (data.get("text") or "").strip())
        if not text:
            # Host left the text field blank — auto-pick a matching preset headline.
            dir_key = "up" if direction > 0 else "down"
            text = pick_preset(state, affects, dir_key)
            if not text:
                cname = state["companies"].get(affects, {}).get("name", affects)
                text  = (f"Market update: {cname} sees notable "
                         f"{'gains' if direction > 0 else 'losses'} amid shifting investor sentiment.")
        n = {
            "id":        uuid.uuid4().hex[:8],
            "type_tag":  "verified" if is_verified else "unverified",
            "label":     "Market Event" if is_verified else "Unverified Rumour",
            "text":      text,
            "affects":   affects,
            "direction": direction,
            "strength":  strength,
            "real":      is_real,
            "reactions": {},
        }
        state["news"].append(n)
        c = state["companies"].get(affects)
        if c and state["phase"] == "trading":
            c["prev_price"] = c["price"]
            if is_verified:
                move = strength
            else:
                move = strength if random.random() < 0.4 else random.uniform(0.005, 0.02)
            floor         = PRICE_FLOORS.get(affects, 10)
            new_price     = max(floor, round(c["price"] * (1 + n["direction"] * move)))
            c["price"]        = new_price
            c["target_price"] = new_price  # move the "fair value" too, so the next 4s tick
                                            # samples around the news price instead of erasing it
        await write_state(state)
    await manager.broadcast_all({"type": "news", **n})
    players = await all_players()
    board   = leaderboard(players, state)
    await manager.broadcast_all({
        "type":   "prices_bulk",
        "prices": {k: v["price"] for k, v in state["companies"].items()},
        "board":  board,
    })
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


@app.post("/api/host/secret_intel")
async def secret_intel(data: dict, pw: str):
    """Send a private news tip to one player only."""
    if pw != HOST_PASSWORD:
        raise HTTPException(403, "Wrong password")
    code = data.get("code", "")
    text = re.sub(r"[<>]", "", (data.get("text") or "").strip())
    if not text:
        raise HTTPException(400, "Enter intel text.")
    n = {
        "type_tag": "unverified",
        "label":    "Secret Intel",
        "text":     text,
        "private":  True,
    }
    await manager.send_player(code, {"type": "news", **n})
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
@app.post("/api/chaos/regulatory_freeze")
async def chaos_regulatory_freeze(data: dict, pw: str):
    """Halt all trading in a sector for the rest of this round."""
    if pw != HOST_PASSWORD:
        raise HTTPException(403, "Wrong password")
    sector   = data["sector"]
    async with STATE_LOCK:
        state    = await read_state()
        affected = [cid for cid, c in state["companies"].items() if c.get("sector") == sector]
        if not affected:
            raise HTTPException(400, f"No companies in sector '{sector}'")
        state["regulatory_freeze"] = sector
        await write_state(state)
    msg = f"🚫 REGULATORY FREEZE — All trading in the {sector} sector is halted for this round!"
    await manager.broadcast_all({
        "type":           "chaos",
        "event":          "regulatory_freeze",
        "sector":         sector,
        "frozen_stocks":  affected,
        "msg":            msg,
    })
    players = await all_players()
    board   = leaderboard(players, state)
    await manager.broadcast_hosts({"type": "state_update", "state": state, "board": board})
    return {"ok": True, "sector": sector, "frozen_stocks": affected}


async def _apply_dividend(cid: str, per_share: int) -> int:
    """Pay a dividend per share to all holders of a company. Shared by the
    manual host endpoint and the automatic round-3/round-4 dividend events."""
    state = await read_state()
    if cid not in state["companies"]:
        return 0
    cname     = state["companies"][cid]["name"]
    players   = await all_players()
    total_out = 0
    for p in players:
        qty = p["holdings"].get(cid, 0)
        if qty > 0:
            div        = qty * per_share
            p["cash"] += div
            total_out += div
            await save_player(p)
            await manager.send_player(p["code"], {
                "type":   "player_update",
                "player": player_view(p, state),
                "msg":    f"💰 Dividend! {qty}× {cname} @ ₹{per_share}/share = +₹{div:,}",
            })
    players = await all_players()
    board   = leaderboard(players, state)
    await manager.broadcast_all({
        "type":  "chaos",
        "event": "dividend",
        "stock": cid,
        "msg":   f"💰 DIVIDEND DECLARED — {cname} pays ₹{per_share:,}/share! Total out: ₹{total_out:,}",
        "board": board,
    })
    await manager.broadcast_hosts({"type": "state_update", "state": state, "board": board})
    return total_out


async def _apply_dividends_batch(items: dict) -> None:
    """Pay several dividends at once ({stock_id: per_share}) and announce them as ONE
    event — used for the automatic Round 3/4 payouts so players get a single clear
    popup instead of 5-8 overlapping ones."""
    state   = await read_state()
    items   = {cid: ps for cid, ps in items.items() if cid in state["companies"]}
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
    players = await all_players()
    board   = leaderboard(players, state)
    per_line = ", ".join(f"{state['companies'][cid]['name'].split()[0]} ₹{ps:g}" for cid, ps in items.items())
    await manager.broadcast_all({
        "type": "chaos", "event": "dividend",
        "msg":  f"💰 DIVIDEND DAY — per share: {per_line}. Holders have been paid.",
        "board": board,
    })
    await manager.broadcast_hosts({"type": "state_update", "state": state, "board": board})


@app.post("/api/chaos/dividend")
async def chaos_dividend(data: dict, pw: str):
    if pw != HOST_PASSWORD:
        raise HTTPException(403, "Wrong password")
    cid       = data["stock"]
    per_share = int(data["per_share"])
    state     = await read_state()
    if cid not in state["companies"]:
        raise HTTPException(400, "Unknown stock")
    total_out = await _apply_dividend(cid, per_share)
    return {"ok": True, "total_paid": total_out}


async def _apply_acquisition_rumour(cid1: str, cid2: str):
    """Correlate two companies' price movements for the rest of this round —
    the 'two stocks move in tandem' acquisition-talk event. Shared by the
    manual host endpoint and the automatic Round 4 late-round trigger."""
    async with STATE_LOCK:
        state = await read_state()
        if cid1 not in state["companies"] or cid2 not in state["companies"]:
            return
        state["acquisition_pair"] = [cid1, cid2]
        n1  = state["companies"][cid1]["name"]
        n2  = state["companies"][cid2]["name"]
        msg = f"🤝 ACQUISITION RUMOUR — {n1} and {n2} reportedly in merger talks! Their prices will move in tandem. (Unverified)"
        news_item = {
            "id": uuid.uuid4().hex[:8], "type_tag": "unverified", "label": "Unverified Rumour",
            "affects": cid1, "direction": 1, "real": True, "text": msg, "reactions": {},
        }
        state["news"].append(news_item)
        await write_state(state)
    await manager.broadcast_all({"type": "chaos", "event": "acquisition_rumour", "msg": msg})
    await manager.broadcast_all({"type": "news", **news_item})
    players = await all_players()
    board   = leaderboard(players, state)
    await manager.broadcast_hosts({"type": "state_update", "state": state, "board": board})


@app.post("/api/chaos/acquisition_rumour")
async def chaos_acquisition(data: dict, pw: str):
    if pw != HOST_PASSWORD:
        raise HTTPException(403, "Wrong password")
    cid1 = data["stock1"]
    cid2 = data["stock2"]
    state = await read_state()
    if cid1 not in state["companies"] or cid2 not in state["companies"]:
        raise HTTPException(400, "Unknown stocks")
    await _apply_acquisition_rumour(cid1, cid2)
    return {"ok": True}


async def _delayed_round4_acquisition_rumour(delay_seconds: float, round_num: int, cid1: str, cid2: str):
    """Fires the Round 4 acquisition rumour once ~15 minutes remain in the
    round (i.e. ~5 minutes after Round 4 starts on a 20-min round). Bails out
    quietly if the round already ended or moved on by the time the delay elapses."""
    try:
        await asyncio.sleep(delay_seconds)
        state = await read_state()
        if state.get("phase") != "trading" or state.get("round") != round_num:
            return
        await _apply_acquisition_rumour(cid1, cid2)
    except Exception as e:
        print(f"[_delayed_round4_acquisition_rumour] failed: {e}")


@app.get("/api/chaos/merger_pairs")
async def list_merger_pairs(pw: str):
    """The fixed list of valid company-merger pairs, for the host UI's picker."""
    if pw != HOST_PASSWORD:
        raise HTTPException(403, "Wrong password")
    state     = await read_state()
    companies = state["companies"]
    out = []
    for key, mdef in MERGER_PAIRS.items():
        cid1, cid2 = key.split("|")
        if cid1 in companies and cid2 in companies:
            out.append({
                "cid1": cid1, "cid2": cid2,
                "name1": companies[cid1]["name"], "name2": companies[cid2]["name"],
                "result_name": mdef["name"],
            })
    return {"pairs": out}


@app.post("/api/chaos/company_merger")
async def chaos_company_merger(data: dict, pw: str):
    """Permanently combine two companies into a brand new one. Existing
    holdings, stop-losses, and insurance on either original stock get
    migrated (value-preserving) or refunded — nothing just vanishes."""
    if pw != HOST_PASSWORD:
        raise HTTPException(403, "Wrong password")
    cid1 = data.get("stock1")
    cid2 = data.get("stock2")
    if not cid1 or not cid2 or cid1 == cid2:
        raise HTTPException(400, "Pick two different companies.")
    mdef = MERGER_PAIRS.get(_mkey(cid1, cid2))
    if not mdef:
        raise HTTPException(400, "These two don't have a defined merger — pick a valid pair.")

    async with STATE_LOCK:
        state     = await read_state()
        companies = state["companies"]
        if cid1 not in companies or cid2 not in companies:
            raise HTTPException(400, "One of these companies isn't listed (already merged, or not IPO'd yet).")
        c1, c2 = companies[cid1], companies[cid2]
        price1, price2 = c1["price"], c2["price"]
        new_price = max(1, round((price1 + price2) / 2))
        new_cid   = f"merged_{cid1}_{cid2}"
        companies_before = {k: dict(v) for k, v in companies.items()}  # snapshot for ETF continuity

        del companies[cid1]
        del companies[cid2]
        companies[new_cid] = {
            "name": mdef["name"], "sector": mdef["sector"], "risk": mdef["risk"],
            "price": new_price, "prev_price": new_price, "target_price": new_price,
            "bio": mdef["bio"], "trait": mdef["trait"],
        }
        PRICE_FLOORS[new_cid] = round(new_price * 0.20)
        state.setdefault("price_history", {})[new_cid] = [new_price]
        state.get("price_freezes", {}).pop(cid1, None)
        state.get("price_freezes", {}).pop(cid2, None)

        # Rebalance any ETF that tracked either original sector (or now tracks
        # the merged one) so its price doesn't jump the instant this lands.
        sectors_touched = {c1.get("sector"), c2.get("sector"), mdef["sector"]}
        for etf_id, etf_cfg in SECTOR_ETFS.items():
            if etf_id not in companies or not (sectors_touched & set(etf_cfg["tracks_sectors"])):
                continue
            old_avg      = _etf_sector_avg(companies_before, etf_cfg["tracks_sectors"])
            new_avg      = _etf_sector_avg(companies, etf_cfg["tracks_sectors"])
            old_baseline = companies[etf_id].get("_baseline_avg") or 1.0
            if old_avg > 0:
                companies[etf_id]["_baseline_avg"] = old_baseline * (new_avg / old_avg)

        migration_notes = {}
        players = await all_players()
        for p in players:
            if not p["name"]:
                continue
            changed = False
            note_bits = []

            q1 = p.get("holdings", {}).get(cid1, 0)
            q2 = p.get("holdings", {}).get(cid2, 0)
            if q1 > 0 or q2 > 0:
                avg1, avg2   = p.get("avg_cost", {}).get(cid1, price1), p.get("avg_cost", {}).get(cid2, price2)
                total_value  = q1 * price1 + q2 * price2
                total_cost   = q1 * avg1 + q2 * avg2
                new_qty      = round(total_value / new_price) if new_price else 0
                p.setdefault("holdings", {})[cid1] = 0
                p["holdings"][cid2] = 0
                if new_qty > 0:
                    p["holdings"][new_cid] = new_qty
                    p.setdefault("avg_cost", {})[new_cid] = (total_cost / new_qty)
                    note_bits.append(f"{new_qty}× {mdef['name']} (from your {q1}+{q2} shares)")
                changed = True

            stops = p.get("stop_losses", {})
            if cid1 in stops or cid2 in stops:
                stops.pop(cid1, None); stops.pop(cid2, None)
                p["stop_losses"] = stops
                note_bits.append("stop-loss order(s) cancelled")
                changed = True

            ins, refund = p.get("insurance", {}), 0
            for cid in (cid1, cid2):
                if cid in ins:
                    refund += ins[cid].get("premium_paid", 0)
                    del ins[cid]
            if refund:
                p["cash"] += refund
                p["insurance"] = ins
                note_bits.append(f"₹{refund:,} insurance premium refunded")
                changed = True

            if changed:
                await save_player(p)
                migration_notes[p["code"]] = f"🏢 {c1['name']} + {c2['name']} → {mdef['name']}. " + "; ".join(note_bits) + "."

        msg = f"🏢 MERGER — {c1['name']} and {c2['name']} have combined into {mdef['name']}. New price: ₹{new_price:,}."
        await write_state(state)

    await manager.broadcast_all({
        "type":  "chaos", "event": "company_merger", "msg": msg,
        "old_ids": [cid1, cid2],
        "new_company": {
            "id": new_cid, "name": mdef["name"], "sector": mdef["sector"], "risk": mdef["risk"],
            "price": new_price, "bio": mdef["bio"], "trait": mdef["trait"],
        },
    })
    for code_, note in migration_notes.items():
        p_fresh = await get_player(code_)
        if p_fresh:
            await manager.send_player(code_, {"type": "player_update", "player": player_view(p_fresh, state), "msg": note})
    players_all = await all_players()
    board = leaderboard(players_all, state)
    await manager.broadcast_all({
        "type":   "prices_bulk",
        "prices": {k: v["price"] for k, v in state["companies"].items()},
        "board":  board,
    })
    await manager.broadcast_hosts({"type": "state_update", "state": state, "board": board})
    return {"ok": True, "new_company_id": new_cid, "new_company_name": mdef["name"]}
    return {"ok": True}


@app.post("/api/chaos/credit_crunch")
async def chaos_credit_crunch(pw: str):
    """Raise all bank rates by +5% for this round's interest calculation."""
    if pw != HOST_PASSWORD:
        raise HTTPException(403, "Wrong password")
    async with STATE_LOCK:
        state = await read_state()
        state["credit_crunch"] = True
        await write_state(state)
    def _range(bid):
        tiers = BANKS[bid]["rate_tiers"]
        return f"{round(tiers[0][1]*100+5)}–{round(tiers[-1][1]*100+5)}%"
    msg = (
        "💸 CREDIT CRUNCH — All bank interest rates +5% this round! "
        f"Bharat→{_range('bharat')}, VentureCapX→{_range('vcx')}, ShadowCredit→{_range('shadow')} "
        "(exact rate still depends on your balance tier). Heavy borrowers beware."
    )
    await manager.broadcast_all({"type": "chaos", "event": "credit_crunch", "msg": msg})
    players = await all_players()
    board   = leaderboard(players, state)
    await manager.broadcast_hosts({"type": "state_update", "state": state, "board": board})
    return {"ok": True}


async def _apply_ipo_drop(ipo_id: str) -> Optional[dict]:
    """List a New Listing (Vortex/Skyline) mid-game. Shared by the manual host
    endpoint and the automatic Round 2 / Round 3 new-listing events. Returns
    the company dict on success, None if already listed / unknown."""
    if ipo_id not in IPO_COMPANIES:
        return None
    async with STATE_LOCK:
        state = await read_state()
        if ipo_id in state.get("ipo_listed", []):
            return None
        ipo = IPO_COMPANIES[ipo_id]
        state["companies"][ipo_id]   = {**ipo, "prev_price": ipo["price"], "target_price": ipo["price"]}
        state["ipo_listed"]          = state.get("ipo_listed", []) + [ipo_id]
        PRICE_FLOORS[ipo_id]         = round(ipo["price"] * 0.20)  # set floor dynamically
        state.setdefault("price_history", {})[ipo_id] = [ipo["price"]]
        # If this new company falls in a sector an ETF tracks, rebalance that
        # ETF's baseline so its price doesn't jump the instant the IPO lists —
        # the ratio (and therefore the ETF's current price) stays continuous.
        for etf_id, etf_cfg in SECTOR_ETFS.items():
            if ipo.get("sector") in etf_cfg["tracks_sectors"] and etf_id in state["companies"]:
                old_avg = _etf_sector_avg(
                    {k: v for k, v in state["companies"].items() if k != ipo_id}, etf_cfg["tracks_sectors"]
                )
                new_avg = _etf_sector_avg(state["companies"], etf_cfg["tracks_sectors"])
                old_baseline = state["companies"][etf_id].get("_baseline_avg") or 1.0
                if old_avg > 0:
                    state["companies"][etf_id]["_baseline_avg"] = old_baseline * (new_avg / old_avg)
        await write_state(state)
    msg = f"🚀 NEW LISTING — {ipo['name']} lists on the exchange! {ipo['trait']} Listing price: ₹{ipo['price']:,}"
    await manager.broadcast_all({
        "type":    "chaos",
        "event":   "ipo_drop",
        "msg":     msg,
        "company": {"id": ipo_id, **ipo},
    })
    players = await all_players()
    board   = leaderboard(players, state)
    await manager.broadcast_hosts({"type": "state_update", "state": state, "board": board})
    return {"id": ipo_id, **ipo}


@app.post("/api/chaos/ipo_drop/{ipo_id}")
async def chaos_ipo_drop(ipo_id: str, pw: str):
    if pw != HOST_PASSWORD:
        raise HTTPException(403, "Wrong password")
    if ipo_id not in IPO_COMPANIES:
        raise HTTPException(400, f"Unknown listing: {ipo_id}")
    company = await _apply_ipo_drop(ipo_id)
    if company is None:
        raise HTTPException(400, f"{ipo_id} is already listed")
    return {"ok": True, "company": company}


@app.post("/api/chaos/portfolio_freeze")
async def chaos_portfolio_freeze(data: dict, pw: str):
    """Freeze a specific player's portfolio (they can't trade this round)."""
    if pw != HOST_PASSWORD:
        raise HTTPException(403, "Wrong password")
    code = data["code"]
    p    = await get_player(code)
    if not p:
        raise HTTPException(404, "Player not found")
    p["frozen"] = True
    await save_player(p)
    state = await read_state()
    await manager.send_player(code, {
        "type":   "player_update",
        "player": player_view(p, state),
        "msg":    "🔒 Your portfolio has been frozen by the host. No trading this round.",
    })
    await manager.broadcast_all({
        "type":  "chaos",
        "event": "portfolio_freeze",
        "msg":   f"🔒 {p['name']}'s portfolio has been frozen!",
    })
    return {"ok": True}



# ═══════════════════════════════════════════════════════════════
#  WEBSOCKET: PLAYER
# ═══════════════════════════════════════════════════════════════
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
        "board":         leaderboard(await all_players(), state),
        "banks":         BANKS,
        "joined":        already_joined,
        "reg_freeze":    state.get("regulatory_freeze"),
        "credit_crunch": state.get("credit_crunch", False),
        "price_history": state.get("price_history", {}),
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
                            "holdings": {}, "loans": {}, "frozen": False,
                            "avg_cost": {}, "bm_log": [],
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
                    await manager.broadcast_all({"type": "leaderboard", "board": board})
                    await manager.broadcast_hosts({"type": "player_online", "code": code, "name": name})

                # ── Buy ───────────────────────────────────────────────────
                elif action == "buy":
                    if state["phase"] != "trading":
                        await websocket.send_text(json.dumps({"type": "error", "msg": "Trading is closed."})); continue
                    if not player:
                        await websocket.send_text(json.dumps({"type": "error", "msg": "Join first."})); continue
                    if player["frozen"]:
                        await websocket.send_text(json.dumps({"type": "error", "msg": "Your portfolio is frozen this round."})); continue
                    stock = msg.get("stock")
                    qty   = safe_int(msg.get("qty"), 0)
                    if stock not in state["companies"] or qty < 1:
                        await websocket.send_text(json.dumps({"type": "error", "msg": "Invalid stock or quantity."})); continue
                    freeze = state.get("regulatory_freeze")
                    if freeze and state["companies"][stock].get("sector") == freeze:
                        await websocket.send_text(json.dumps({"type": "error", "msg": f"⛔ {state['companies'][stock]['sector']} sector is under Regulatory Freeze."})); continue
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
                    await manager.broadcast_all({"type": "leaderboard", "board": board})

                # ── Sell ──────────────────────────────────────────────────
                elif action == "sell":
                    if state["phase"] != "trading":
                        await websocket.send_text(json.dumps({"type": "error", "msg": "Trading is closed."})); continue
                    if not player:
                        await websocket.send_text(json.dumps({"type": "error", "msg": "Join first."})); continue
                    if player["frozen"]:
                        await websocket.send_text(json.dumps({"type": "error", "msg": "Your portfolio is frozen this round."})); continue
                    stock = msg.get("stock")
                    qty   = safe_int(msg.get("qty"), 0)
                    freeze = state.get("regulatory_freeze")
                    if freeze and state["companies"].get(stock, {}).get("sector") == freeze:
                        await websocket.send_text(json.dumps({"type": "error", "msg": "⛔ Regulatory Freeze — no trading in this sector."})); continue
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
                    await manager.broadcast_all({"type": "leaderboard", "board": board})

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

                # ── Insurance — insure one held position for the rest of this round ──
                elif action == "buy_insurance":
                    if state["phase"] != "trading":
                        await websocket.send_text(json.dumps({"type": "error", "msg": "Trading is closed."})); continue
                    if not player:
                        await websocket.send_text(json.dumps({"type": "error", "msg": "Join first."})); continue
                    stock = msg.get("stock")
                    if stock in (player.get("insurance") or {}):
                        await websocket.send_text(json.dumps({"type": "error", "msg": "You already have an active policy on that stock."})); continue
                    async with _player_locks[code]:
                        player = await get_player(code)
                        state  = await read_state()
                        owned  = player.get("holdings", {}).get(stock, 0)
                        if owned < 1:
                            await websocket.send_text(json.dumps({"type": "error", "msg": "You don't hold any shares of that stock."})); continue
                        avg_cost = player.get("avg_cost", {}).get(stock, state["companies"][stock]["price"])
                        premium  = round(owned * avg_cost * INSURANCE_PREMIUM_PCT)
                        if player["cash"] < premium:
                            await websocket.send_text(json.dumps({"type": "error", "msg": f"Need ₹{premium:,} for the premium — you have ₹{int(player['cash']):,}."})); continue
                        player["cash"] -= premium
                        ins = player.get("insurance", {})
                        ins[stock] = {"qty": owned, "avg_cost_locked": avg_cost, "premium_paid": premium, "round_taken": state["round"]}
                        player["insurance"] = ins
                        await save_player(player)
                    pv = player_view(player, state)
                    await websocket.send_text(json.dumps({
                        "type":   "trade_ok", "player": pv,
                        "msg":    f"🛡️ Insured {owned}× {state['companies'][stock]['name']} at ₹{avg_cost:,.0f} cost basis. Premium: ₹{premium:,}. Covers {int(INSURANCE_COVERAGE_PCT*100)}% of losses below that if you're still holding at round end.",
                    }))

                # ── React to a news item (Discord-style, toggle on/off) ──────
                elif action == "react_news":
                    if not player:
                        continue
                    news_id = msg.get("news_id")
                    emoji   = msg.get("emoji")
                    if not news_id or emoji not in NEWS_REACTION_EMOJIS:
                        continue
                    async with STATE_LOCK:
                        fresh_state = await read_state()
                        item = next((n for n in fresh_state.get("news", []) if n.get("id") == news_id), None)
                        if item is not None:
                            reactions = item.setdefault("reactions", {})
                            who = reactions.setdefault(emoji, [])
                            if player["name"] in who:
                                who.remove(player["name"])
                            else:
                                who.append(player["name"])
                            if not who:
                                reactions.pop(emoji, None)
                            await write_state(fresh_state)
                            counts = {e: len(v) for e, v in item.get("reactions", {}).items()}
                        else:
                            counts = None
                    if counts is not None:
                        await manager.broadcast_all({"type": "news_reaction", "news_id": news_id, "counts": counts})

                # ── Take loan ─────────────────────────────────────────────
                elif action == "take_loan":
                    if not player:
                        await websocket.send_text(json.dumps({"type": "error", "msg": "Join first."})); continue
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
                    rate     = bank_rate_for_balance(bank_id, new_bal) + (0.05 if state.get("credit_crunch") else 0)
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
                    async with _player_locks[code]:
                        player = await get_player(code)
                        player["cash"]        = BANKRUPTCY_RESTART
                        player["holdings"]    = {}
                        player["loans"]       = {}
                        player["avg_cost"]    = {}
                        player["stop_losses"] = {}
                        player["frozen"]      = True   # frozen for the rest of this round as a bankruptcy penalty
                        player["bankruptcy_count"] = player.get("bankruptcy_count", 0) + 1
                        await save_player(player)
                    pv = player_view(player, state)
                    await websocket.send_text(json.dumps({
                        "type":   "bankrupt",
                        "msg":    (f"💀 Bankruptcy declared. Wiped clean. Restarting with ₹{BANKRUPTCY_RESTART:,}. "
                                   "🔒 Trading is frozen for the rest of this round as a penalty — it unlocks "
                                   "automatically when the next round starts."),
                        "player": pv,
                    }))
                    players = await all_players()
                    board   = leaderboard(players, state)
                    await manager.broadcast_all({
                        "type":  "chaos",
                        "event": "bankrupt",
                        "msg":   f"💀 {player['name']} declared voluntary bankruptcy and restarted with ₹{BANKRUPTCY_RESTART:,}!",
                        "board": board,
                    })

                # ── Place prediction bet ──────────────────────────────────
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