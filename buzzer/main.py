"""
Market Mayhem — main.py
FastAPI + WebSockets + SQLite (aiosqlite)

Local:   uvicorn main:app --reload --port 8000
Railway: uvicorn main:app --host 0.0.0.0 --port $PORT

Routes:
  /          →  team.html   (player trading UI)
  /host      →  host.html   (password-protected host panel)
  /bm        →  bm.html     (black market)

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

from news_presets import NEWS_PRESETS

# ═══════════════════════════════════════════════════════════════
#  CONFIG
# ═══════════════════════════════════════════════════════════════
DB_PATH            = Path(os.getenv("DB_PATH", "game.db"))
HOST_PASSWORD      = os.getenv("HOST_PASSWORD", "Ich_liebe_Siya")
STARTING_CASH      = 0
ROUND_DURATION     = 1200        # 20 min — host can end early
BREAK_DURATION     = 600         # 10 min between rounds
BANKRUPTCY_RESTART = 25_000
SHORT_MARGIN_PCT   = 0.40   # cash held as collateral when opening a short = 40% of position value
INCOME_TAX_RATE    = 0.15   # on realized gains each round (only if positive)
WEALTH_TAX_RATE    = 0.03   # on the round-end leader's net worth
INSURANCE_PREMIUM_PCT  = 0.08   # cost to insure a position = 8% of its value at purchase
INSURANCE_COVERAGE_PCT = 0.60   # covers 60% of the loss below your locked cost, if you still hold it at round end
NEWS_REACTION_EMOJIS = {"🔥", "📈", "📉", "😱", "💀", "🤔"}
BANKRUPTCY_MIN_DEBT_GAP = 900_000   # debt must exceed net worth by ~9 lakh to qualify
MAX_ROUNDS         = 6

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
    "Technology":       ["skylink", "indranet", "bytecorp"],
    "FMCG":             ["freshco", "crownmart"],
    "Defence":          ["shieldgen", "armorinc"],
    "Renewable Energy": ["voltex"],
    "Pharma":           ["mediq"],
    "Logistics":        ["swifthaul"],
    "Manufacturing":    ["zora"],
    "Media / OTT":      ["streamvx"],
    "Fintech":          ["novapay"],
    "Agriculture":      ["greenleaf"],
}

# ═══════════════════════════════════════════════════════════════
#  VOLATILITY PROFILES  (min_drift, max_drift, down_bias)
#  down_bias > 0.5  →  stock drifts down more often (higher risk)
# ═══════════════════════════════════════════════════════════════
COMPANY_VOL = {
    "zora":      (0.004, 0.016, 0.48),   # Low risk, steady
    "streamvx":  (0.025, 0.075, 0.45),   # High vol, slight upward
    "freshco":   (0.003, 0.014, 0.49),   # Very stable
    "voltex":    (0.018, 0.055, 0.44),   # Growth, upward bias
    "mediq":     (0.018, 0.065, 0.46),   # Binary-event stock
    "skylink":   (0.030, 0.085, 0.44),   # High vol, narrative-driven
    "swifthaul": (0.010, 0.038, 0.46),   # Medium vol
    "crownmart": (0.022, 0.070, 0.45),   # Turnaround risk
    "shieldgen": (0.004, 0.018, 0.49),   # Very stable
    "indranet":  (0.008, 0.030, 0.47),   # Quiet compounder
    "novapay":   (0.038, 0.095, 0.43),   # High vol fintech
    "greenleaf": (0.015, 0.055, 0.46),   # Subsidy-dependent
    "armorinc":  (0.006, 0.025, 0.48),   # Stable defence
    "bytecorp":  (0.055, 0.140, 0.44),   # Pure speculative — extreme vol
    # ── Safe-route investments: tiny moves, biased toward steady positive drift ──
    "debtfund":     (0.001, 0.004, 0.35),  # Near-flat. This is the "parking cash" option.
    "balancedfund": (0.003, 0.012, 0.42),  # A little more motion, still calm.
    # ── Sector ETFs: volatility here is unused (price tracks the sector index instead) ──
    "techetf":     (0.0, 0.0, 0.5),
    "consumeretf": (0.0, 0.0, 0.5),
    "indusetf":    (0.0, 0.0, 0.5),
}

# Price floors per company (20% of IPO price — prevents absurd crashes)
PRICE_FLOORS = {
    "zora":      84,   "streamvx": 62,  "freshco": 37,  "voltex":   112,
    "mediq":     55,   "skylink":  178, "swifthaul": 68, "crownmart": 44,
    "shieldgen": 98,   "indranet": 86,  "novapay":  40,  "greenleaf": 30,
    "armorinc":  76,   "bytecorp": 130,
    "debtfund": 90, "balancedfund": 110,
    "techetf": 100, "consumeretf": 100, "indusetf": 100,
}

# ═══════════════════════════════════════════════════════════════
#  BASE COMPANIES  (always in game from Round 1)
# ═══════════════════════════════════════════════════════════════
BASE_COMPANIES = {
    "zora": {
        "name": "Zora Industries", "sector": "Manufacturing", "risk": "Low", "price": 420,
        "bio": (
            "Founded in 1972 by retired army engineer Vikram Zora, Zora Industries started as a small "
            "steel fabrication unit in Pune and grew into one of India's largest diversified manufacturers. "
            "Today it supplies everything from structural steel and industrial pipes to precision components "
            "for defence platforms and port infrastructure. The company has never missed a dividend in 30 "
            "consecutive years — a record that attracts pension funds and risk-averse institutions who treat "
            "Zora like a fixed deposit. Revenue is ₹22,400 crore. Margins are thin but rock-solid. The "
            "current order book stands at ₹38,000 crore. Boring? Absolutely. Safe? Almost certainly."
        ),
        "trait": "Old money. Steady as a rock.",
    },
    "streamvx": {
        "name": "StreamVerse", "sector": "Media / OTT", "risk": "High", "price": 310,
        "bio": (
            "StreamVerse launched in 2018 riding the Jio-fuelled data revolution and hasn't looked back. "
            "With 62 million subscribers and originals in 11 Indian languages, it's now the second-largest "
            "OTT platform in the country. The problem: it burns ₹3,200 crore a year on content. "
            "Every original that flops is a body blow; every hit buys them another 18 months of investor "
            "patience. The founder, a former Bollywood producer, is charismatic and reckless in equal "
            "measure. The stock trades on sentiment more than fundamentals. When a show goes viral, "
            "it soars. When subscriber numbers disappoint, it bleeds. High conviction, high volatility."
        ),
        "trait": "Binge-worthy. Wallet-draining.",
    },
    "freshco": {
        "name": "FreshCo", "sector": "FMCG", "risk": "Low", "price": 185,
        "bio": (
            "FreshCo has been in every Indian kitchen since 1965. From its flagship atta brand to "
            "shampoos, biscuits, and packaged snacks, the company is woven into the daily routine of "
            "400 million households. Its distribution network — 6 million kirana stores, 18 warehouses, "
            "and a direct-to-village supply chain across 600 districts — is its greatest moat. "
            "The balance sheet is clean, debt is negligible, and the dividend yield is 3.1%. "
            "FreshCo doesn't grow fast. But in rural India, consumption growth is structural, not "
            "cyclical. Analysts call it dull. Experienced investors call it their anchor."
        ),
        "trait": "Every Indian home has one.",
    },
    "voltex": {
        "name": "Voltex Energy", "sector": "Renewable Energy", "risk": "Medium-High", "price": 560,
        "bio": (
            "Voltex Energy is the government's favourite clean-energy bet. It operates 4.2 GW of solar "
            "capacity across Rajasthan, Gujarat, and Tamil Nadu, with two 600MW wind farms under "
            "construction in Andhra Pradesh. The company's growth is inseparable from government "
            "subsidy policy — when the policy is generous, Voltex flies; when bureaucratic winds shift, "
            "it stalls. Revenue is ₹9,800 crore but net profit is thin, with most earnings re-invested "
            "into new capacity. A recent debt refinancing brought rates down to 7.2%. Institutional "
            "investors are overweight, retail is excited, and every green-energy headline moves the stock."
        ),
        "trait": "Future is bright. Profits, not yet.",
    },
    "mediq": {
        "name": "MediQ", "sector": "Pharma", "risk": "Medium", "price": 275,
        "bio": (
            "MediQ is a mid-size pharma company with one exceptional card up its sleeve: Zytravax, "
            "a potential blockbuster oncology drug currently in Phase 3 trials. The rest of the "
            "portfolio — generic APIs and hospital supply contracts — is steady but unremarkable. "
            "If Zytravax clears DCGI approval, analysts estimate the stock 4–6x from current levels. "
            "If it fails or faces delays, expect a 35–40% single-day fall. Management is tight-lipped, "
            "trial data is closely guarded, and insiders are unusually active in the options market. "
            "Owning MediQ is not investing — it's placing a single, high-conviction bet on science."
        ),
        "trait": "One approval away from the moon.",
    },
    "skylink": {
        "name": "SkyLink Tech", "sector": "Technology", "risk": "High", "price": 890,
        "bio": (
            "SkyLink is India's most-discussed tech stock. Founded by IIT-Delhi dropout Aryan Mehta "
            "in 2014, the company makes cloud infrastructure software used by 2,400 enterprises across "
            "Southeast Asia. Revenue grew 44% last year to ₹14,200 crore. But the P/E ratio of 98x "
            "assumes nothing ever goes wrong. The stock is driven almost entirely by narrative — AI "
            "integrations, international expansion, founder charisma. When sentiment is good, it "
            "outperforms everything. When it cracks, it cracks hard. Institutional bulls and retail "
            "momentum traders share the same bed. It's worked so far."
        ),
        "trait": "Overhyped. Overpriced. Irresistible.",
    },
    "swifthaul": {
        "name": "SwiftHaul Logistics", "sector": "Logistics", "risk": "Medium", "price": 340,
        "bio": (
            "SwiftHaul was built on one bet: that India's e-commerce boom would create insatiable "
            "demand for last-mile delivery. It was right. The company now runs 18,000 vehicles across "
            "620 cities, delivers 2.4 million packages a day, and processes 840 million shipments "
            "annually. Three of the country's top five e-commerce players use SwiftHaul as their "
            "primary logistics partner. The business model is operationally complex — thin margins, "
            "fuel exposure, labour costs — but scale and exclusivity contracts provide stability. "
            "A cold-chain pharma logistics vertical is being quietly built. If it works, margins jump."
        ),
        "trait": "The backbone of online India.",
    },
    "crownmart": {
        "name": "CrownMart", "sector": "FMCG", "risk": "Medium", "price": 220,
        "bio": (
            "CrownMart is the turnaround story the market is watching. Once India's dominant "
            "brick-and-mortar retail chain with 2,800 stores, it was blindsided by quick commerce — "
            "Blinkit, Zepto, and Swiggy Instamart carved out its core grocery customer. "
            "The new CEO, Priya Nair, appointed 14 months ago, has a plan: shut 120 loss-making "
            "stores, expand private label to 40% of revenue, and turn profitable stores into "
            "'experience centres' that cannot be replicated online. Early results are mixed. "
            "The market is split: half believe this is a genuine reinvention; half think it's "
            "a slow decline dressed up in strategy."
        ),
        "trait": "Old retail trying to run new tricks.",
    },
    "shieldgen": {
        "name": "ShieldGen Defence", "sector": "Defence", "risk": "Low", "price": 490,
        "bio": (
            "ShieldGen has supplied the Indian armed forces for 38 years without interruption. "
            "Its product lines span armoured vehicle components, radar systems, infantry gear, "
            "and battlefield communications equipment. The company's revenue is almost entirely "
            "government-contracted with multi-year lock-ins. Border escalations are, bluntly, "
            "good news for the stock. Every defence budget hike adds to the order book. "
            "The promoter family holds 62% and hasn't sold a single share in a decade. "
            "ShieldGen doesn't surprise you — it just quietly compounds."
        ),
        "trait": "Fear is their product. Stability is their promise.",
    },
    "indranet": {
        "name": "IndraNet", "sector": "Technology", "risk": "Medium", "price": 430,
        "bio": (
            "IndraNet is what SkyLink pretends to be: actually profitable. Founded in 2009, "
            "the company sells B2B SaaS products to 14,000 enterprise clients — banks, insurance "
            "companies, PSUs, and mid-size manufacturers. Its core product is a workflow "
            "automation platform that's embedded so deeply into client operations that switching "
            "costs are enormous. Net revenue retention sits at 118%. The company is not exciting. "
            "Its founder refuses media interviews. There are no splashy product launches. "
            "But net margins are 24%, cash conversion is 94%, and the balance sheet has "
            "zero debt. In a sea of high-multiple tech hype, IndraNet is the quiet compounder."
        ),
        "trait": "Boring profits beat exciting losses.",
    },
}

# ═══════════════════════════════════════════════════════════════
#  IPO COMPANIES  (host drops these during the game)
# ═══════════════════════════════════════════════════════════════
IPO_COMPANIES = {
    "novapay": {
        "name": "NovaPay", "sector": "Fintech", "risk": "High", "price": 200,
        "bio": (
            "NovaPay was born inside a Bengaluru garage in 2019 and grew into a payments giant "
            "by making UPI transactions faster, cheaper, and more reliable than any competitor. "
            "It processes 800 million transactions per month across 340 million registered users. "
            "The B2B merchant side — payment gateway, POS terminals, BNPL rails — is where the "
            "real revenue sits. The problem: NovaPay has never posted a profit. It spends "
            "aggressively on user acquisition and international expansion. Now it's listing, "
            "and the market must decide: PhonePe successor, or overvalued promise?"
        ),
        "trait": "Could be the next PhonePe. Or the next cautionary tale.",
    },
    "greenleaf": {
        "name": "GreenLeaf Agri", "sector": "Agriculture", "risk": "Medium", "price": 150,
        "bio": (
            "GreenLeaf Agri is building the supply chain that India's farmers never had. "
            "The company connects 200,000 farmers directly to grocery chains, exporters, "
            "and food processors — cutting out four layers of middlemen and lifting farmer "
            "income by an average of 22%. Operations span 8 states, with cold storage "
            "facilities at 140 mandis. The model is subsidy-dependent: three government "
            "agritech schemes currently fund 31% of operating costs. If those schemes "
            "renew, GreenLeaf scales fast. If they're cut, margins collapse."
        ),
        "trait": "The field is fertile. So is the risk.",
    },
    "armorinc": {
        "name": "ArmorInc", "sector": "Defence", "risk": "Low", "price": 380,
        "bio": (
            "ArmorInc is the quiet younger sibling of ShieldGen — smaller, more specialised, "
            "and surprisingly profitable. Its product lines focus on personal protection: "
            "bulletproof vests, helmets, blast-resistant vehicle panels, and a growing "
            "surveillance equipment division used by state police forces and paramilitary "
            "units. Revenue is ₹3,200 crore with 19% net margins. The company recently won "
            "its first central paramilitary contract worth ₹840 crore. Under the radar — for now."
        ),
        "trait": "Not ShieldGen. But close enough.",
    },
    "bytecorp": {
        "name": "ByteCorp AI", "sector": "Technology", "risk": "Very High", "price": 650,
        "bio": (
            "ByteCorp AI has no revenue. It has no paying customers. It has two enterprise "
            "pilots, a demo that went viral, a founder who gave a TED talk, and a valuation "
            "that makes serious analysts laugh nervously. The company's foundation model — "
            "BharatGPT — is genuinely impressive: trained on 22 Indian languages with "
            "performance benchmarks that beat several international models on regional tasks. "
            "The thesis is that India's linguistic diversity creates a moat no foreign AI "
            "can easily replicate. Either this is the ground floor of something enormous, "
            "or it's nothing. No in-between."
        ),
        "trait": "The future. Or a ₹0 stock. No in-between.",
    },
}

# ═══════════════════════════════════════════════════════════════
#  SAFE-ROUTE INVESTMENTS — mutual funds (steady, low-volatility) and sector
#  ETFs (price tracks a basket of real companies instead of walking randomly).
#  Both are added into state["companies"] just like everything else, so all
#  existing trading/portfolio/chart infrastructure works on them for free.
# ═══════════════════════════════════════════════════════════════
FUNDS = {
    "debtfund": {
        "name": "Bharat Debt Fund", "sector": "Mutual Fund", "risk": "Very Low", "price": 100,
        "is_fund": True,
        "bio": (
            "A plain, boring debt fund holding government bonds and top-rated corporate paper. "
            "It will not make you rich. It will also not ruin you. Fund managers describe its "
            "strategy as 'try very hard to do nothing interesting.' The kind of thing your risk-averse "
            "uncle would actually approve of. If you just want somewhere to park cash between bets "
            "without watching it evaporate, this is it."
        ),
        "trait": "The parking lot for your cash.",
    },
    "balancedfund": {
        "name": "Balanced Growth Fund", "sector": "Mutual Fund", "risk": "Low", "price": 150,
        "is_fund": True,
        "bio": (
            "A diversified fund split across large, stable companies and a small slice of higher-growth "
            "names. Not thrilling, but it actually tries to grow instead of just sitting there. The pitch: "
            "steadier than picking individual stocks, with enough real growth that it isn't just a savings "
            "account with extra steps. The compromise option for people who want to feel like they're "
            "still playing the game without the stomach-drop swings."
        ),
        "trait": "Diversified. Deliberately unexciting.",
    },
}

SECTOR_ETFS = {
    "techetf": {
        "name": "Tech Sector ETF", "sector": "ETF", "risk": "Medium", "price": 500,
        "is_etf": True, "tracks_sectors": ["Technology"],
        "bio": (
            "Tracks a basket of every listed Technology-sector company on the exchange — currently "
            "SkyLink Tech, IndraNet, and ByteCorp AI once it lists. You don't pick a winner here, you buy "
            "the whole sector's momentum. Smooths out any single company's disaster, but also means you "
            "don't get the full upside if just one of them moons."
        ),
        "trait": "The whole sector, one ticker.",
    },
    "consumeretf": {
        "name": "Consumer Goods ETF", "sector": "ETF", "risk": "Low", "price": 300,
        "is_etf": True, "tracks_sectors": ["FMCG"],
        "bio": (
            "Tracks the FMCG basket — FreshCo and CrownMart. People buy groceries and snacks in good "
            "times and bad, which is exactly why this basket barely reacts to anything. A calmer way to "
            "get exposure to the consumer story without betting on one brand's ad campaign landing."
        ),
        "trait": "Groceries never go out of style.",
    },
    "indusetf": {
        "name": "Industrial & Infra ETF", "sector": "ETF", "risk": "Medium", "price": 400,
        "is_etf": True, "tracks_sectors": ["Manufacturing", "Renewable Energy", "Logistics"],
        "bio": (
            "Tracks the industrial backbone basket — Zora Industries, Voltex Energy, and SwiftHaul "
            "Logistics. Manufacturing, power, and freight rise and fall together more often than not, "
            "so this basket moves like a slow, heavy freight train: not fast, but with real momentum "
            "once it gets going."
        ),
        "trait": "Steel, power, and trucks — bundled.",
    },
}

# ═══════════════════════════════════════════════════════════════
#  NEWS POOL
# ═══════════════════════════════════════════════════════════════
NEWS_POOL = [
    # ── ZORA (8)
    {"type_tag":"verified",   "label":"Market Event",      "affects":"zora", "direction": 1, "strength":0.10, "real":True,
     "text":"Zora Industries secures ₹2,800 crore defence infrastructure contract from the Ministry of Defence — its third major government award this fiscal year."},
    {"type_tag":"verified",   "label":"Market Event",      "affects":"zora", "direction":-1, "strength":0.09, "real":True,
     "text":"BREAKING: National union declares a 3-day strike at manufacturing hubs across 5 states. Zora's flagship Pune plant has shut down."},
    {"type_tag":"verified",   "label":"Market Event",      "affects":"zora", "direction": 1, "strength":0.08, "real":True,
     "text":"Zora Industries marks 30 consecutive years of uninterrupted dividend payouts. LIC raises its stake by 4.2% in the latest quarter."},
    {"type_tag":"verified",   "label":"Market Event",      "affects":"zora", "direction": 1, "strength":0.11, "real":True,
     "text":"Zora wins ₹4,600 crore port infrastructure contract in Odisha. Management upgrades full-year revenue guidance by 14%."},
    {"type_tag":"verified",   "label":"Market Event",      "affects":"zora", "direction":-1, "strength":0.08, "real":True,
     "text":"Steel import duties slashed by 8%. Cheaper Chinese steel undercuts Zora's pricing in the domestic structural market."},
    {"type_tag":"unverified", "label":"Unverified Rumour", "affects":"zora", "direction":-1, "strength":0.11, "real":False,
     "text":"Rumour: A whistleblower claims Zora used substandard materials in a recent government project. The company calls the allegations completely fabricated."},
    {"type_tag":"unverified", "label":"Insider Hint",      "affects":"zora", "direction": 1, "strength":0.13, "real":True,
     "text":"Insider tip: Zora is in the final stage of negotiations for a ₹4,000 crore highway bridge contract. Award expected within days."},
    {"type_tag":"unverified", "label":"Unverified Rumour", "affects":"zora", "direction": 1, "strength":0.10, "real":False,
     "text":"Rumour: A large sovereign wealth fund is accumulating Zora shares quietly ahead of an expected Q4 earnings beat."},
    # ── STREAMVERSE (9)
    {"type_tag":"verified",   "label":"Market Event",      "affects":"streamvx", "direction":-1, "strength":0.12, "real":True,
     "text":"BREAKING: StreamVerse reports a 14% jump in subscriber churn after hiking monthly subscription prices by ₹100. Net adds turn negative for the first time."},
    {"type_tag":"verified",   "label":"Market Event",      "affects":"streamvx", "direction": 1, "strength":0.13, "real":True,
     "text":"StreamVerse's latest original crime drama crosses 200 million watch hours in its first week — the biggest debut in Indian OTT history."},
    {"type_tag":"verified",   "label":"Market Event",      "affects":"streamvx", "direction":-1, "strength":0.09, "real":True,
     "text":"Disney+ Hotstar announces an aggressive price cut and a major IPL streaming deal, directly targeting StreamVerse's urban subscriber base."},
    {"type_tag":"verified",   "label":"Market Event",      "affects":"streamvx", "direction": 1, "strength":0.10, "real":True,
     "text":"StreamVerse signs a 3-year exclusive deal with India's top film studio, locking out all competitors from its most bankable directors."},
    {"type_tag":"verified",   "label":"Market Event",      "affects":"streamvx", "direction":-1, "strength":0.11, "real":True,
     "text":"BREAKING: StreamVerse reports Q2 cash burn of ₹1,100 crore — 34% worse than analyst estimates. CFO steps down citing 'personal reasons'."},
    {"type_tag":"verified",   "label":"Market Event",      "affects":"streamvx", "direction": 1, "strength":0.09, "real":True,
     "text":"StreamVerse ad-supported tier crosses 18 million users in 6 months — monetisation path finally becoming credible to sceptical analysts."},
    {"type_tag":"unverified", "label":"Unverified Rumour", "affects":"streamvx", "direction":-1, "strength":0.10, "real":False,
     "text":"Rumour: A former StreamVerse VP claims the platform artificially inflates subscriber numbers to attract brand advertising. Management denies."},
    {"type_tag":"unverified", "label":"Insider Hint",      "affects":"streamvx", "direction": 1, "strength":0.14, "real":True,
     "text":"Insider tip: StreamVerse is close to signing an exclusive cricket streaming deal for 3 IPL seasons — a contract reportedly worth ₹4,200 crore."},
    {"type_tag":"unverified", "label":"Unverified Rumour", "affects":"streamvx", "direction": 1, "strength":0.12, "real":False,
     "text":"Rumour: A US streaming giant is in preliminary acquisition talks for StreamVerse at a 45% premium to current market price. Both sides unconfirmed."},
    # ── FRESHCO (8)
    {"type_tag":"verified",   "label":"Market Event",      "affects":"freshco", "direction": 1, "strength":0.08, "real":True,
     "text":"Rural FMCG consumption hits a 6-year high. FreshCo's 6 million kirana distribution network gives it unmatched last-mile reach in the surge."},
    {"type_tag":"verified",   "label":"Market Event",      "affects":"freshco", "direction":-1, "strength":0.10, "real":True,
     "text":"BREAKING: A cyclone warning is issued for the eastern coast. FreshCo's largest manufacturing cluster in Odisha has suspended operations."},
    {"type_tag":"verified",   "label":"Market Event",      "affects":"freshco", "direction": 1, "strength":0.09, "real":True,
     "text":"FreshCo's new premium biscuit line sells out in 48 hours across modern trade. Early data suggests 22% margin improvement over base SKUs."},
    {"type_tag":"verified",   "label":"Market Event",      "affects":"freshco", "direction":-1, "strength":0.08, "real":True,
     "text":"BREAKING: Palm oil prices surge 19% globally. FreshCo's input costs rise materially — margin guidance cut for the next two quarters."},
    {"type_tag":"verified",   "label":"Market Event",      "affects":"freshco", "direction": 1, "strength":0.09, "real":True,
     "text":"FreshCo announces entry into the premium skincare segment targeting urban millennials. Analysts project ₹1,200 crore in incremental revenue by Year 3."},
    {"type_tag":"unverified", "label":"Unverified Rumour", "affects":"freshco", "direction":-1, "strength":0.09, "real":False,
     "text":"Rumour: A viral social media post claims FreshCo's popular biscuit brand contains banned additives. Company calls it fabricated and is pursuing legal action."},
    {"type_tag":"unverified", "label":"Insider Hint",      "affects":"freshco", "direction": 1, "strength":0.11, "real":True,
     "text":"Insider tip: FreshCo's rural distribution numbers for this quarter are reportedly far ahead of estimates. Formal guidance upgrade expected next week."},
    {"type_tag":"unverified", "label":"Unverified Rumour", "affects":"freshco", "direction": 1, "strength":0.09, "real":False,
     "text":"Rumour: A global FMCG giant is reportedly in talks to acquire FreshCo's branded foods division at a significant premium. Unverified."},
    # ── VOLTEX (8)
    {"type_tag":"verified",   "label":"Market Event",      "affects":"voltex", "direction": 1, "strength":0.12, "real":True,
     "text":"BREAKING: Government announces ₹4,200 crore renewable energy subsidy expansion. Voltex Energy named explicitly in the policy document as a primary beneficiary."},
    {"type_tag":"verified",   "label":"Market Event",      "affects":"voltex", "direction":-1, "strength":0.11, "real":True,
     "text":"BREAKING: Two Voltex solar parks in Rajasthan fail safety inspections. Ministry of New Energy suspends project clearances pending a full review."},
    {"type_tag":"verified",   "label":"Market Event",      "affects":"voltex", "direction": 1, "strength":0.10, "real":True,
     "text":"Voltex Energy signs its largest contract yet — a 900MW solar park for a state electricity board. Analysts revise price target upward by 35%."},
    {"type_tag":"verified",   "label":"Market Event",      "affects":"voltex", "direction":-1, "strength":0.09, "real":True,
     "text":"Solar panel import tariffs hiked by 12%. Voltex's upcoming projects face a cost overrun of approximately ₹600 crore. Capex guidance raised."},
    {"type_tag":"verified",   "label":"Market Event",      "affects":"voltex", "direction": 1, "strength":0.09, "real":True,
     "text":"India achieves a new solar installation record. REC prices jump 14%, directly boosting Voltex's near-term revenue per MW."},
    {"type_tag":"unverified", "label":"Unverified Rumour", "affects":"voltex", "direction": 1, "strength":0.13, "real":False,
     "text":"Rumour: Voltex Energy allegedly in advanced merger talks with a UAE sovereign wealth fund. Could value the company at 3× current market cap. Unconfirmed."},
    {"type_tag":"unverified", "label":"Insider Hint",      "affects":"voltex", "direction": 1, "strength":0.12, "real":True,
     "text":"Insider tip: Government officials have reportedly signed off internally on Voltex's subsidy renewal — announcement expected before close of quarter."},
    {"type_tag":"unverified", "label":"Unverified Rumour", "affects":"voltex", "direction":-1, "strength":0.10, "real":False,
     "text":"Rumour: Voltex's Rajasthan solar project is reportedly 4 months behind schedule due to grid connection delays. Penalty clauses may apply."},
    # ── MEDIQ (8)
    {"type_tag":"verified",   "label":"Market Event",      "affects":"mediq", "direction": 1, "strength":0.14, "real":True,
     "text":"MediQ's Phase 3 drug trial results submitted to DCGI. Internal sources describe the efficacy data as 'exceptionally strong'. Approval timeline: 30 days."},
    {"type_tag":"verified",   "label":"Market Event",      "affects":"mediq", "direction":-1, "strength":0.15, "real":True,
     "text":"BREAKING: DCGI rejects MediQ's blockbuster drug application citing insufficient long-term safety data. Additional trials required — timeline pushed back 18 months."},
    {"type_tag":"verified",   "label":"Market Event",      "affects":"mediq", "direction": 1, "strength":0.10, "real":True,
     "text":"MediQ quietly files 4 new patents for next-generation oncology drugs. Pipeline depth far exceeds what the market has priced in."},
    {"type_tag":"verified",   "label":"Market Event",      "affects":"mediq", "direction":-1, "strength":0.10, "real":True,
     "text":"US FDA issues import alerts on MediQ's Hyderabad API manufacturing plant. Export revenues at risk until remediation is certified."},
    {"type_tag":"verified",   "label":"Market Event",      "affects":"mediq", "direction": 1, "strength":0.09, "real":True,
     "text":"WHO qualifies MediQ as a preferred supplier for generic oncology APIs in 40 developing nations. Long-term export revenue locked in."},
    {"type_tag":"unverified", "label":"Unverified Rumour", "affects":"mediq", "direction": 1, "strength":0.14, "real":False,
     "text":"Rumour: A global pharma giant is reportedly in acquisition talks for MediQ at a 60% premium to current price. Neither company has confirmed."},
    {"type_tag":"unverified", "label":"Insider Hint",      "affects":"mediq", "direction": 1, "strength":0.14, "real":True,
     "text":"Insider tip: MediQ's Zytravax trial data is reportedly clean and strong. DCGI submission is imminent. Management unusually confident internally."},
    {"type_tag":"unverified", "label":"Unverified Rumour", "affects":"mediq", "direction":-1, "strength":0.12, "real":False,
     "text":"Rumour: An adverse event in MediQ's Phase 3 trial is being reviewed internally. Nothing has been filed yet but whispers are spreading."},
    # ── SKYLINK (8)
    {"type_tag":"verified",   "label":"Market Event",      "affects":"skylink", "direction": 1, "strength":0.11, "real":True,
     "text":"SkyLink Tech posts 34% YoY revenue growth in Q2, beating analyst consensus by ₹420 crore. Founder announces entry into Southeast Asian markets."},
    {"type_tag":"verified",   "label":"Market Event",      "affects":"skylink", "direction":-1, "strength":0.13, "real":True,
     "text":"BREAKING: A massive data breach at SkyLink exposes 11 million user records. Government issues show-cause notice. Fines expected to exceed ₹800 crore."},
    {"type_tag":"verified",   "label":"Market Event",      "affects":"skylink", "direction":-1, "strength":0.10, "real":True,
     "text":"SkyLink loses two large enterprise contracts to IndraNet in a competitive rebid. Churn at the top of the client book raises retention concerns."},
    {"type_tag":"verified",   "label":"Market Event",      "affects":"skylink", "direction": 1, "strength":0.12, "real":True,
     "text":"SkyLink announces an AI product partnership with a top US tech firm — a deal that could fundamentally revalue the company's TAM story."},
    {"type_tag":"verified",   "label":"Market Event",      "affects":"skylink", "direction":-1, "strength":0.09, "real":True,
     "text":"BREAKING: SkyLink founder sells ₹800 crore of personal stock. Insider selling at this scale typically signals concern about near-term outlook."},
    {"type_tag":"unverified", "label":"Unverified Rumour", "affects":"skylink", "direction":-1, "strength":0.11, "real":False,
     "text":"Rumour: Three senior SkyLink engineers have resigned en masse over a dispute with the founder. Anonymous posts describe 'toxic leadership'. Unverified."},
    {"type_tag":"unverified", "label":"Insider Hint",      "affects":"skylink", "direction": 1, "strength":0.13, "real":True,
     "text":"Insider tip: SkyLink's Q3 deal pipeline is reportedly the strongest in company history. An earnings surprise is quietly expected internally."},
    {"type_tag":"unverified", "label":"Unverified Rumour", "affects":"skylink", "direction": 1, "strength":0.12, "real":False,
     "text":"Rumour: A global tech giant has submitted a non-binding indicative offer for SkyLink at 2.2× current price. Completely unverified."},
    # ── SWIFTHAUL (8)
    {"type_tag":"verified",   "label":"Market Event",      "affects":"swifthaul", "direction": 1, "strength":0.10, "real":True,
     "text":"SwiftHaul reports a 28% surge in same-day delivery volume as festive season kicks off. Signs exclusive 3-year contract with India's largest e-commerce platform."},
    {"type_tag":"verified",   "label":"Market Event",      "affects":"swifthaul", "direction":-1, "strength":0.10, "real":True,
     "text":"BREAKING: Fuel prices rise 12% following a global crude oil surge. SwiftHaul's fleet of 18,000 vehicles faces immediate margin compression."},
    {"type_tag":"verified",   "label":"Market Event",      "affects":"swifthaul", "direction": 1, "strength":0.09, "real":True,
     "text":"SwiftHaul's cold-chain pharma division signs its first hospital chain client. High-margin recurring revenue materialises ahead of analyst forecasts."},
    {"type_tag":"verified",   "label":"Market Event",      "affects":"swifthaul", "direction":-1, "strength":0.09, "real":True,
     "text":"A competing logistics firm poaches SwiftHaul's head of enterprise sales along with the team managing three key accounts. Client at-risk notices issued."},
    {"type_tag":"verified",   "label":"Market Event",      "affects":"swifthaul", "direction": 1, "strength":0.08, "real":True,
     "text":"GST Council simplifies e-way bill compliance. SwiftHaul estimates ₹120 crore in annual cost savings from reduced administrative overhead."},
    {"type_tag":"unverified", "label":"Unverified Rumour", "affects":"swifthaul", "direction":-1, "strength":0.10, "real":False,
     "text":"Rumour: SwiftHaul allegedly under-reporting delivery failure rates to maintain contract metrics. An internal audit is said to be underway."},
    {"type_tag":"unverified", "label":"Insider Hint",      "affects":"swifthaul", "direction": 1, "strength":0.11, "real":True,
     "text":"Insider tip: SwiftHaul's cold-chain pharma division has onboarded 3 hospital chains. Revenue starts next quarter — not in consensus estimates."},
    {"type_tag":"unverified", "label":"Unverified Rumour", "affects":"swifthaul", "direction":-1, "strength":0.09, "real":False,
     "text":"Rumour: SwiftHaul's primary e-commerce partner is running a quiet RFQ process with rival logistics firms. Contract renewal may not be automatic."},
    # ── CROWNMART (8)
    {"type_tag":"verified",   "label":"Market Event",      "affects":"crownmart", "direction": 1, "strength":0.11, "real":True,
     "text":"CrownMart's new CEO unveils a restructuring plan: closing 120 loss-making stores and doubling down on high-margin private label products. Analysts react positively."},
    {"type_tag":"verified",   "label":"Market Event",      "affects":"crownmart", "direction":-1, "strength":0.11, "real":True,
     "text":"BREAKING: Blinkit announces 10-minute grocery delivery expansion to 50 new cities — directly attacking CrownMart's core customer base in Tier-2 markets."},
    {"type_tag":"verified",   "label":"Market Event",      "affects":"crownmart", "direction":-1, "strength":0.10, "real":True,
     "text":"CrownMart's Q3 same-store sales data shows a 9% decline. Results below guidance for the second consecutive quarter. Analysts cut targets."},
    {"type_tag":"verified",   "label":"Market Event",      "affects":"crownmart", "direction": 1, "strength":0.10, "real":True,
     "text":"CrownMart's private label division posts 34% revenue growth. Margins on own-brand products are 18 percentage points above branded equivalents."},
    {"type_tag":"verified",   "label":"Market Event",      "affects":"crownmart", "direction":-1, "strength":0.09, "real":True,
     "text":"CrownMart announces 40 additional store closures beyond the previously disclosed 120, citing structurally unviable lease terms."},
    {"type_tag":"unverified", "label":"Unverified Rumour", "affects":"crownmart", "direction": 1, "strength":0.12, "real":False,
     "text":"Rumour: A major private equity firm is building a stake in CrownMart ahead of an alleged management buyout. Unusual after-hours trading activity spotted."},
    {"type_tag":"unverified", "label":"Insider Hint",      "affects":"crownmart", "direction":-1, "strength":0.11, "real":True,
     "text":"Insider tip: CrownMart's Q3 same-store sales data, not yet public, shows a 9% decline. Insiders are quietly reducing positions ahead of results."},
    {"type_tag":"unverified", "label":"Unverified Rumour", "affects":"crownmart", "direction": 1, "strength":0.10, "real":False,
     "text":"Rumour: CrownMart is in preliminary talks with a GCC-based sovereign retailer about a strategic investment and regional expansion partnership."},
    # ── SHIELDGEN (8)
    {"type_tag":"verified",   "label":"Market Event",      "affects":"shieldgen", "direction": 1, "strength":0.12, "real":True,
     "text":"BREAKING: Escalating border tensions prompt the government to fast-track ₹18,000 crore in emergency defence procurement. ShieldGen is primary supplier for 3 of 5 categories."},
    {"type_tag":"verified",   "label":"Market Event",      "affects":"shieldgen", "direction": 1, "strength":0.10, "real":True,
     "text":"ShieldGen receives export clearance to supply radar systems to two allied nations — India's defence export push directly boosts order visibility."},
    {"type_tag":"verified",   "label":"Market Event",      "affects":"shieldgen", "direction":-1, "strength":0.09, "real":True,
     "text":"A parliamentary committee review flags ShieldGen's pricing on a recent armoured vehicle contract. Overpricing investigation formally initiated."},
    {"type_tag":"verified",   "label":"Market Event",      "affects":"shieldgen", "direction": 1, "strength":0.11, "real":True,
     "text":"Defence budget hiked 18% in supplementary demands. ShieldGen's order book grows by ₹6,800 crore in a single day of inbound procurement notices."},
    {"type_tag":"verified",   "label":"Market Event",      "affects":"shieldgen", "direction": 1, "strength":0.09, "real":True,
     "text":"'Make in India' defence mandate raises domestic content requirement to 70%. ShieldGen, as a fully domestic manufacturer, gains a structural competitive advantage."},
    {"type_tag":"unverified", "label":"Unverified Rumour", "affects":"shieldgen", "direction":-1, "strength":0.10, "real":False,
     "text":"Rumour: A parliamentary committee is allegedly reviewing ShieldGen's pricing on a recent armoured vehicle contract. Government has not confirmed any probe."},
    {"type_tag":"unverified", "label":"Insider Hint",      "affects":"shieldgen", "direction": 1, "strength":0.12, "real":True,
     "text":"Insider tip: ShieldGen has secured a 7-year maintenance contract for a classified drone programme worth ₹6,000 crore. Announcement expected post budget session."},
    {"type_tag":"unverified", "label":"Unverified Rumour", "affects":"shieldgen", "direction": 1, "strength":0.11, "real":False,
     "text":"Rumour: A further ₹12,000 crore supplementary defence allocation is being discussed in Cabinet. ShieldGen would be the single largest beneficiary."},
    # ── INDRANET (7)
    {"type_tag":"verified",   "label":"Market Event",      "affects":"indranet", "direction": 1, "strength":0.10, "real":True,
     "text":"IndraNet closes 3 large enterprise renewals at 20% higher ARR. Net revenue retention at 118% for the fourth consecutive quarter."},
    {"type_tag":"verified",   "label":"Market Event",      "affects":"indranet", "direction":-1, "strength":0.09, "real":True,
     "text":"SkyLink launches a competing workflow automation product at 30% lower pricing, directly targeting IndraNet's mid-market client base."},
    {"type_tag":"verified",   "label":"Market Event",      "affects":"indranet", "direction": 1, "strength":0.09, "real":True,
     "text":"IndraNet wins a ₹480 crore 5-year contract with a major public sector bank — its largest PSU deal ever. Management raises full-year guidance."},
    {"type_tag":"verified",   "label":"Market Event",      "affects":"indranet", "direction": 1, "strength":0.08, "real":True,
     "text":"Gartner names IndraNet a Leader in its Asia-Pacific Workflow Automation Magic Quadrant for the third consecutive year. International inbounds accelerate."},
    {"type_tag":"unverified", "label":"Unverified Rumour", "affects":"indranet", "direction":-1, "strength":0.10, "real":False,
     "text":"Rumour: A key IndraNet engineering team is reportedly being poached by SkyLink en masse, including the architect of the core automation engine."},
    {"type_tag":"unverified", "label":"Insider Hint",      "affects":"indranet", "direction": 1, "strength":0.11, "real":True,
     "text":"Insider tip: IndraNet just closed 3 large enterprise renewals at 20% higher ARR. Not announced yet — formal guidance upgrade expected next quarter."},
    {"type_tag":"unverified", "label":"Unverified Rumour", "affects":"indranet", "direction": 1, "strength":0.10, "real":False,
     "text":"Rumour: A global enterprise software firm is running diligence on IndraNet as an acquisition target. Premium to current price estimated at 40%."},
    # ── NOVAPAY (IPO, 7)
    {"type_tag":"verified",   "label":"Market Event",      "affects":"novapay", "direction":-1, "strength":0.13, "real":True,
     "text":"BREAKING: RBI sends NovaPay a show-cause notice over KYC compliance gaps in its BNPL product. ₹200 crore fine and product pause possible."},
    {"type_tag":"verified",   "label":"Market Event",      "affects":"novapay", "direction": 1, "strength":0.12, "real":True,
     "text":"NovaPay's monthly transaction volume crosses ₹1 lakh crore for the first time. Market share vs PhonePe narrows to 4 percentage points."},
    {"type_tag":"verified",   "label":"Market Event",      "affects":"novapay", "direction":-1, "strength":0.11, "real":True,
     "text":"BREAKING: UPI interchange fee framework revised downward by RBI. NovaPay's core revenue per transaction drops 18%. Profitability timeline extends."},
    {"type_tag":"verified",   "label":"Market Event",      "affects":"novapay", "direction": 1, "strength":0.10, "real":True,
     "text":"NovaPay BNPL product reaches 8 million users in 5 months — fastest adoption for any credit product in Indian fintech history."},
    {"type_tag":"unverified", "label":"Unverified Rumour", "affects":"novapay", "direction": 1, "strength":0.14, "real":False,
     "text":"Rumour: A Singapore sovereign fund is eyeing a 20% strategic stake in NovaPay at a valuation of 2× current market price. Completely unconfirmed."},
    {"type_tag":"unverified", "label":"Insider Hint",      "affects":"novapay", "direction":-1, "strength":0.12, "real":True,
     "text":"Insider tip: NovaPay's internal audit has flagged irregularities in transaction fee reporting that may require a revenue restatement."},
    {"type_tag":"unverified", "label":"Unverified Rumour", "affects":"novapay", "direction": 1, "strength":0.11, "real":False,
     "text":"Rumour: NovaPay has quietly applied for a small finance bank licence — if granted, this transforms it from a fintech into a fully regulated bank."},
    # ── GREENLEAF (IPO, 7)
    {"type_tag":"verified",   "label":"Market Event",      "affects":"greenleaf", "direction": 1, "strength":0.11, "real":True,
     "text":"GreenLeaf Agri onboards 200,000 new farmers this season. The government farm-to-fork subsidy scheme has been renewed for 3 more years."},
    {"type_tag":"verified",   "label":"Market Event",      "affects":"greenleaf", "direction":-1, "strength":0.12, "real":True,
     "text":"BREAKING: Drought conditions declared across 3 of GreenLeaf's key operating states. Crop yield outlook revised down 28%. Revenue guidance cut."},
    {"type_tag":"verified",   "label":"Market Event",      "affects":"greenleaf", "direction": 1, "strength":0.10, "real":True,
     "text":"GreenLeaf signs supply agreements with 6 major retail chains, securing offtake for 40% of its produce network for the next 2 years."},
    {"type_tag":"verified",   "label":"Market Event",      "affects":"greenleaf", "direction":-1, "strength":0.10, "real":True,
     "text":"A government review of agritech subsidies proposes 30% cuts in allocation. GreenLeaf, which relies on these for 31% of operating costs, faces margin risk."},
    {"type_tag":"unverified", "label":"Insider Hint",      "affects":"greenleaf", "direction": 1, "strength":0.11, "real":True,
     "text":"Insider tip: GreenLeaf's Gulf export deal is reportedly finalised at ₹2,000 crore annually. Transformative if confirmed — not in any public guidance."},
    {"type_tag":"unverified", "label":"Unverified Rumour", "affects":"greenleaf", "direction":-1, "strength":0.09, "real":False,
     "text":"Rumour: A government audit has flagged GreenLeaf's subsidy claims as potentially inflated. A formal investigation may be underway."},
    {"type_tag":"verified",   "label":"Market Event",      "affects":"greenleaf", "direction": 1, "strength":0.09, "real":True,
     "text":"GreenLeaf expands cold storage to 40 new mandis. Post-harvest losses drop 18% — a key metric that directly affects subsidy renewal prospects."},
    # ── ARMORINC (IPO, 7)
    {"type_tag":"verified",   "label":"Market Event",      "affects":"armorinc", "direction": 1, "strength":0.10, "real":True,
     "text":"ArmorInc wins its first central paramilitary contract — 50,000 bulletproof vests for CRPF at ₹840 crore. Recurring annual procurement expected."},
    {"type_tag":"verified",   "label":"Market Event",      "affects":"armorinc", "direction": 1, "strength":0.09, "real":True,
     "text":"ArmorInc's surveillance division signs a ₹420 crore contract with 3 state police forces. High-margin, recurring service revenue begins."},
    {"type_tag":"verified",   "label":"Market Event",      "affects":"armorinc", "direction":-1, "strength":0.09, "real":True,
     "text":"A foreign OEM wins an import tender for personal protective equipment that ArmorInc had expected to secure. 12% revenue shortfall anticipated."},
    {"type_tag":"verified",   "label":"Market Event",      "affects":"armorinc", "direction": 1, "strength":0.10, "real":True,
     "text":"Escalating internal security concerns prompt ₹3,200 crore state government equipment procurement. ArmorInc wins the largest single order in its history."},
    {"type_tag":"unverified", "label":"Insider Hint",      "affects":"armorinc", "direction": 1, "strength":0.12, "real":True,
     "text":"Insider tip: ArmorInc is in advanced acquisition talks for a Pune-based surveillance tech startup. A deal could double its addressable market overnight."},
    {"type_tag":"unverified", "label":"Unverified Rumour", "affects":"armorinc", "direction": 1, "strength":0.10, "real":False,
     "text":"Rumour: ShieldGen is in preliminary talks to acquire ArmorInc at a 35% premium as part of a domestic defence consolidation play."},
    {"type_tag":"verified",   "label":"Market Event",      "affects":"armorinc", "direction": 1, "strength":0.08, "real":True,
     "text":"ArmorInc receives defence export licence. First shipment of ₹120 crore of personal protection equipment to an African nation dispatched."},
    # ── BYTECORP (IPO, 8)
    {"type_tag":"verified",   "label":"Market Event",      "affects":"bytecorp", "direction": 1, "strength":0.15, "real":True,
     "text":"ByteCorp AI's BharatGPT demo goes viral after a prominent US tech analyst calls it 'the most impressive multilingual AI model built outside the US'. Retail frenzy begins."},
    {"type_tag":"verified",   "label":"Market Event",      "affects":"bytecorp", "direction":-1, "strength":0.14, "real":True,
     "text":"BREAKING: ByteCorp's AI enterprise pilot with a major private bank collapses after accuracy failures in Hindi and Tamil. The hype cycle takes a hard hit."},
    {"type_tag":"verified",   "label":"Market Event",      "affects":"bytecorp", "direction": 1, "strength":0.13, "real":True,
     "text":"ByteCorp signs its first revenue-generating enterprise contract — a 2-year deal with a government ministry for AI-powered document processing at ₹180 crore."},
    {"type_tag":"verified",   "label":"Market Event",      "affects":"bytecorp", "direction":-1, "strength":0.13, "real":True,
     "text":"OpenAI launches an Indian-language optimised model that benchmarks above BharatGPT on 7 of 11 regional language tests. ByteCorp's core moat narrative cracks."},
    {"type_tag":"verified",   "label":"Market Event",      "affects":"bytecorp", "direction": 1, "strength":0.12, "real":True,
     "text":"ByteCorp partners with India's largest telecom to embed BharatGPT across 480 million mobile users. Distribution reach far exceeds any competitor."},
    {"type_tag":"verified",   "label":"Market Event",      "affects":"bytecorp", "direction":-1, "strength":0.11, "real":True,
     "text":"ByteCorp reports net cash burn of ₹420 crore for the quarter with no clear timeline to profitability. Institutional investors begin trimming positions."},
    {"type_tag":"unverified", "label":"Unverified Rumour", "affects":"bytecorp", "direction": 1, "strength":0.15, "real":False,
     "text":"Rumour: Microsoft is in serious talks to invest ₹2,000 crore in ByteCorp AI. The CEO responded 'no comment'. Market has fully priced in the best case."},
    {"type_tag":"unverified", "label":"Insider Hint",      "affects":"bytecorp", "direction": 1, "strength":0.14, "real":True,
     "text":"Insider tip: ByteCorp is weeks away from announcing a government AI contract worth ₹800 crore — the company's first large public-sector revenue deal."},
    # ── SECTOR-WIDE (20)
    {"type_tag":"verified", "label":"Market Event", "affects":"sector:Technology",       "direction": 1, "strength":0.08, "real":True,
     "text":"SECTOR: Government launches a ₹10,000 crore Digital India 3.0 push. Cloud, SaaS, and AI companies are the primary intended beneficiaries."},
    {"type_tag":"verified", "label":"Market Event", "affects":"sector:Technology",       "direction":-1, "strength":0.08, "real":True,
     "text":"SECTOR: A sweeping data localisation bill clears Rajya Sabha. Compliance costs for tech companies estimated at ₹4,000–8,000 crore industry-wide."},
    {"type_tag":"verified", "label":"Market Event", "affects":"sector:Technology",       "direction": 1, "strength":0.07, "real":True,
     "text":"SECTOR: India climbs to #3 globally in tech startup funding. Analyst upgrades across the sector as global capital inflows accelerate."},
    {"type_tag":"verified", "label":"Market Event", "affects":"sector:Technology",       "direction":-1, "strength":0.07, "real":True,
     "text":"SECTOR: Global tech selloff after US Fed signals higher-for-longer rates. Indian tech stocks, with high P/E multiples, bear the sharpest correction."},
    {"type_tag":"verified", "label":"Market Event", "affects":"sector:FMCG",             "direction": 1, "strength":0.07, "real":True,
     "text":"SECTOR: Rural consumption surges 11% YoY as crop prices rise and rural wages hit a 5-year high. FMCG companies are broadly re-rated upward."},
    {"type_tag":"verified", "label":"Market Event", "affects":"sector:FMCG",             "direction":-1, "strength":0.07, "real":True,
     "text":"SECTOR: Palm oil and edible oil prices spike 22% globally. Input cost pressure hits all FMCG manufacturers simultaneously."},
    {"type_tag":"verified", "label":"Market Event", "affects":"sector:Defence",          "direction": 1, "strength":0.09, "real":True,
     "text":"SECTOR: Defence budget hiked 18% in supplementary demands. Domestic manufacturers across the sector receive order upgrades."},
    {"type_tag":"verified", "label":"Market Event", "affects":"sector:Defence",          "direction": 1, "strength":0.08, "real":True,
     "text":"SECTOR: 'Make in India' defence mandate requires 70% domestic content. Foreign OEMs must partner with Indian firms — domestic players gain structural edge."},
    {"type_tag":"verified", "label":"Market Event", "affects":"sector:Pharma",           "direction":-1, "strength":0.07, "real":True,
     "text":"SECTOR: US FDA issues import alerts on 4 Indian pharmaceutical plants. Export revenue for multiple companies at immediate risk."},
    {"type_tag":"verified", "label":"Market Event", "affects":"sector:Pharma",           "direction": 1, "strength":0.07, "real":True,
     "text":"SECTOR: WHO qualifies 3 more Indian generic manufacturers for global supply. Export opportunity worth ₹12,000 crore opens up across the sector."},
    {"type_tag":"verified", "label":"Market Event", "affects":"sector:Logistics",        "direction":-1, "strength":0.07, "real":True,
     "text":"SECTOR: New national highway toll policy hikes rates by 15%. All logistics and trucking companies face immediate cost increases."},
    {"type_tag":"verified", "label":"Market Event", "affects":"sector:Logistics",        "direction": 1, "strength":0.07, "real":True,
     "text":"SECTOR: GST Council announces simplified e-way bill process, reducing logistics compliance costs. Entire sector benefits from the efficiency gain."},
    {"type_tag":"verified", "label":"Market Event", "affects":"sector:Renewable Energy", "direction": 1, "strength":0.08, "real":True,
     "text":"SECTOR: India achieves a new solar installation record. Government doubles renewable energy subsidies for the next 3 fiscal years."},
    {"type_tag":"verified", "label":"Market Event", "affects":"sector:Renewable Energy", "direction":-1, "strength":0.07, "real":True,
     "text":"SECTOR: Solar panel import tariffs hiked 12%. Domestic project costs rise for all renewable energy companies."},
    {"type_tag":"verified", "label":"Market Event", "affects":"sector:Fintech",          "direction": 1, "strength":0.08, "real":True,
     "text":"SECTOR: UPI transaction volume crosses 20 billion monthly. RBI announces new incentive framework for digital payment platforms."},
    {"type_tag":"verified", "label":"Market Event", "affects":"sector:Fintech",          "direction":-1, "strength":0.08, "real":True,
     "text":"SECTOR: RBI tightens digital lending norms. Fintech companies face new capital adequacy requirements that squeeze short-term profitability."},
    {"type_tag":"verified", "label":"Market Event", "affects":"sector:Agriculture",      "direction": 1, "strength":0.07, "real":True,
     "text":"SECTOR: Government announces largest-ever agritech investment package at ₹8,500 crore. Agritech startups and listed companies both benefit."},
    {"type_tag":"verified", "label":"Market Event", "affects":"sector:Agriculture",      "direction":-1, "strength":0.07, "real":True,
     "text":"SECTOR: A poor monsoon forecast triggers broad-based selling in agri-dependent businesses. Crop yield estimates revised down 15%."},
    {"type_tag":"verified", "label":"Market Event", "affects":"sector:Media / OTT",      "direction": 1, "strength":0.07, "real":True,
     "text":"SECTOR: Internet penetration reaches 900 million users in India. OTT platforms are the biggest beneficiaries of the next digital adoption wave."},
    {"type_tag":"verified", "label":"Market Event", "affects":"sector:Manufacturing",    "direction": 1, "strength":0.07, "real":True,
     "text":"SECTOR: PLI (Production Linked Incentive) scheme extended for 3 years. Manufacturing companies across steel, defence, and infrastructure to benefit."},
]

# ═══════════════════════════════════════════════════════════════
#  BLACK MARKET ITEMS
# ═══════════════════════════════════════════════════════════════
BM_ITEMS = {
    "insider_hint": {
        "id": "insider_hint", "name": "Insider Hint", "icon": "🔍", "cost": 15_000,
        "desc": "A private, unverified tip on one stock — only you see it. Could be gold. Could be noise.",
    },
    "spread_rumour": {
        "id": "spread_rumour", "name": "Spread Rumour", "icon": "📢", "cost": 10_000,
        "desc": "Plant an anonymous Unverified headline. You pick the stock and write the text. Random price effect. Untraceable.",
    },
    "leak_card": {
        "id": "leak_card", "name": "Leak Card", "icon": "🃏", "cost": 25_000,
        "desc": "One-time use per game. Broadcast a strong Unverified headline that always moves price. More powerful than a rumour.",
    },
    "price_freeze": {
        "id": "price_freeze", "name": "Price Freeze Hack", "icon": "🧊", "cost": 18_000,
        "desc": "Freeze one stock's price feed for 60 real seconds — nobody (including you) can move it or get a fresh quote on it.",
    },
    "rate_freeze": {
        "id": "rate_freeze", "name": "Rate Freeze Coupon", "icon": "🔒", "cost": 20_000,
        "desc": "Locks in your current interest rate with one bank for its next round-end charge, even if your balance climbs into a higher tier.",
    },
    "portfolio_peek": {
        "id": "portfolio_peek", "name": "Portfolio Peek", "icon": "🕵️", "cost": 18_000,
        "desc": "Instantly reveals a rival's cash, total loans, and full holdings list. Just this once, just to you.",
    },
    "early_word": {
        "id": "early_word", "name": "Early Word", "icon": "🔮", "cost": 22_000,
        "desc": "Break-only. See next round's opening headlines before anyone else — the real ones, not a preview.",
    },
}

INSIDER_HINTS = [
    ("zora",       1,  0.12, "A bulk order for Zora's industrial components just landed from a defence subcontractor. Unconfirmed but credible."),
    ("zora",      -1,  0.10, "Zora's largest plant reportedly running at 60% capacity due to a parts shortage. Not public yet."),
    ("streamvx",   1,  0.13, "Word is StreamVerse's next original just wrapped production and early test screenings are exceptional."),
    ("streamvx",  -1,  0.11, "StreamVerse's latest subscriber data allegedly shows churn accelerating. Results due soon."),
    ("freshco",    1,  0.10, "FreshCo's rural distribution numbers for this quarter are reportedly far ahead of estimates."),
    ("freshco",   -1,  0.09, "A FreshCo manufacturing unit in Odisha is dealing with a quiet quality control issue. Not disclosed publicly."),
    ("voltex",     1,  0.12, "Government officials have reportedly signed off internally on Voltex's subsidy renewal — announcement imminent."),
    ("voltex",    -1,  0.11, "Voltex's Rajasthan solar project reportedly 4 months behind schedule due to grid connection delays."),
    ("mediq",      1,  0.14, "MediQ's Zytravax trial data is reportedly clean and strong. Submission to DCGI is imminent."),
    ("mediq",     -1,  0.13, "Rumoured adverse event in MediQ's Phase 3 trial being quietly reviewed internally. Nothing filed yet."),
    ("skylink",    1,  0.13, "SkyLink's Q3 deal pipeline is reportedly the strongest in company history. Earnings surprise likely."),
    ("skylink",   -1,  0.12, "SkyLink is quietly losing two enterprise clients to IndraNet. No public statement expected."),
    ("swifthaul",  1,  0.11, "SwiftHaul's cold-chain pharma division just onboarded its first 3 hospital chains. Revenue starts next quarter."),
    ("swifthaul", -1,  0.10, "SwiftHaul's primary e-commerce partner is reportedly in talks with a rival logistics firm."),
    ("crownmart",  1,  0.11, "CrownMart's Q3 private-label sales are reportedly tracking 30% ahead of target."),
    ("crownmart", -1,  0.10, "CrownMart is about to announce 40 more store closures beyond the previously disclosed 120."),
    ("shieldgen",  1,  0.12, "ShieldGen's classified drone maintenance contract has reportedly been signed and sealed."),
    ("indranet",   1,  0.11, "IndraNet just closed 3 large enterprise renewals at 20% higher ARR. Not announced yet."),
    ("indranet",  -1,  0.09, "A key IndraNet engineering team is reportedly being poached by SkyLink en masse."),
    ("novapay",    1,  0.13, "NovaPay's RBI KYC issue has reportedly been resolved behind closed doors. Formal clearance expected soon."),
    ("bytecorp",   1,  0.14, "ByteCorp's government contract — the big one — is in final legal sign-off. Announcement within days."),
    ("bytecorp",  -1,  0.13, "ByteCorp's lead model engineer has quietly resigned. Harder to replace than the market realises."),
    ("greenleaf",  1,  0.11, "GreenLeaf's Gulf export deal is reportedly finalised. ₹2,000 crore annually — transformative if confirmed."),
    ("armorinc",   1,  0.11, "ArmorInc's surveillance tech acquisition is almost done. Completion expected before next round."),
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
                code     TEXT PRIMARY KEY,
                name     TEXT,
                cash     REAL    DEFAULT 0,
                holdings TEXT    DEFAULT '{}',
                loans    TEXT    DEFAULT '{}',
                frozen   INTEGER DEFAULT 0,
                avg_cost TEXT    DEFAULT '{}',
                bets     TEXT    DEFAULT '{}',
                bm_log   TEXT    DEFAULT '[]'
            )
        """)
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
        "merge_bids":         {},
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
    return {
        "code":     row["code"],
        "name":     row["name"],
        "cash":     row["cash"],
        "holdings": json.loads(row["holdings"]),
        "loans":    json.loads(row["loans"]),
        "frozen":   bool(row["frozen"]),
        "avg_cost": json.loads(row["avg_cost"]),
        "bets":     json.loads(row["bets"]),
        "bm_log":   json.loads(row["bm_log"]),
    }


async def save_player(p: dict):
    async with aiosqlite.connect(DB_PATH, timeout=5.0) as db:
        await db.execute(
            """INSERT OR REPLACE INTO players
               (code,name,cash,holdings,loans,frozen,avg_cost,bets,bm_log)
               VALUES (?,?,?,?,?,?,?,?,?)""",
            (
                p["code"], p.get("name"), p["cash"],
                json.dumps(p["holdings"]),
                json.dumps(p.get("loans", {})),
                int(p.get("frozen", False)),
                json.dumps(p.get("avg_cost", {})),
                json.dumps(p.get("bets", {})),
                json.dumps(p.get("bm_log", [])),
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
    # Short positions: you already banked the sale proceeds in cash when you
    # opened these, so what's left is a LIABILITY — the cost to buy the shares
    # back at today's price. That liability comes straight off net worth.
    shorts = {}
    short_liability = 0
    for cid, sp in (p.get("shorts") or {}).items():
        if sp.get("qty", 0) > 0 and cid in companies:
            price   = companies[cid]["price"]
            qty     = sp["qty"]
            entry   = sp["entry_price"]
            cost_to_cover = qty * price
            short_liability += cost_to_cover
            shorts[cid] = {
                "qty": qty, "entry_price": round(entry), "price": price,
                "cost_to_cover": round(cost_to_cover),
                "pnl": round((entry - price) * qty),  # positive = price fell, you're winning
            }
    port_value  = sum(h["value"] for h in portfolio.values())
    total_loans = player_loans_total(p)
    net_worth   = p["cash"] + port_value - total_loans - short_liability
    return {
        "cash":         round(p["cash"]),
        "loans":        p.get("loans", {}),
        "total_loan":   round(total_loans),
        "frozen":       p["frozen"],
        "net_worth":    round(net_worth),
        "portfolio":    portfolio,
        "bets":         p.get("bets", {}),
        "shorts":       shorts,
        "short_liability": round(short_liability),
        "stop_losses":  p.get("stop_losses", {}),
        "insurance":    p.get("insurance", {}),
    }


def leaderboard(players: list, state: dict) -> list:
    rows = []
    for p in players:
        if not p["name"] or p.get("merged_into"):
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

async def price_target_loop():
    """Every 20s: recompute each stock's underlying target price, AND drop a
    matching news headline for whichever stock moved the most that cycle —
    so the price change and the news that "caused" it land together and
    people can actually connect the two, instead of news being on its own
    disconnected timer."""
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
                moves = {}  # cid -> (direction, magnitude) for this cycle's movers
                for cid, c in companies.items():
                    if c.get("is_etf") or c.get("is_fund"):
                        continue  # ETFs/funds derive their price or drift quietly — no news hooks them
                    if freeze and c.get("sector") == freeze:
                        continue
                    if frozen_bm.get(cid, 0) > now:
                        continue
                    lo, hi, bias = COMPANY_VOL.get(cid, (0.005, 0.03, 0.46))
                    mag   = random.uniform(lo * 0.5, hi * 0.65)
                    direc = 1 if random.random() > bias else -1
                    floor = PRICE_FLOORS.get(cid, 10)
                    base  = c.get("target_price", c["price"])
                    c["target_price"] = max(floor, round(base * (1 + direc * mag)))
                    moves[cid] = (direc, mag)

                # One headline per cycle, for the single biggest mover — this
                # is what actually ties a visible price move to a reason.
                if moves:
                    top_cid       = max(moves, key=lambda k: moves[k][1])
                    direc, mag    = moves[top_cid]
                    dir_key       = "up" if direc > 0 else "down"
                    options       = NEWS_PRESETS.get(top_cid, {}).get(dir_key, [])
                    used          = set(state.get("news_used", []))
                    fresh_options = [o for o in options if o not in used] or options
                    if fresh_options:
                        text = random.choice(fresh_options)
                        state.setdefault("news_used", []).append(text)
                        headline_n = {
                            "id":        uuid.uuid4().hex[:8],
                            "type_tag":  "verified",
                            "label":     "Market Event",
                            "text":      text,
                            "affects":   top_cid,
                            "direction": direc,
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
                    jitter = random.uniform(-lo * 0.9, lo * 0.9) or random.uniform(-0.01, 0.01)
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
def pick_news(state: dict, count: int = 3) -> list:
    listed = set(state.get("ipo_listed", []))
    used   = set(state.get("news_used", []))
    pool   = []
    for n in NEWS_POOL:
        if n["text"] in used:
            continue
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
    return chosen


async def ambient_news_loop():
    """DEPRECATED — folded into price_target_loop, which now generates a
    matching headline for the biggest mover every 20s cycle instead of this
    running on its own disconnected ~2min timer with its own separate price
    impact. Kept as a no-op stub in case anything still references it."""
    return


# ═══════════════════════════════════════════════════════════════
#  PREDICTION MARKET
# ═══════════════════════════════════════════════════════════════
def compute_sentiment(players: list, companies: dict) -> dict:
    tally = {cid: {"up": 0, "down": 0} for cid in companies}
    for p in players:
        for cid, bet in (p.get("bets") or {}).items():
            if cid not in tally:
                tally[cid] = {"up": 0, "down": 0}
            key = "up" if bet.get("direction") == "up" else "down"
            tally[cid][key] += bet.get("amount", 0)
    result = {}
    for cid, t in tally.items():
        total = t["up"] + t["down"]
        if total > 0:
            result[cid] = {
                "up_pct":     round(t["up"] / total * 100),
                "down_pct":   round(t["down"] / total * 100),
                "total_bets": total,
            }
    return result


async def resolve_predictions(state: dict, players: list) -> None:
    """
    Evaluate bets at round end.
    Payout tiers:
      - Correct direction AND target hit  → 3× stake
      - Correct direction only            → 1.5× stake
      - Wrong direction                   → stake lost (already deducted)
    """
    companies = state["companies"]
    for p in players:
        if not p.get("bets"):
            continue
        changed = False
        for cid, bet in list(p["bets"].items()):
            if cid not in companies:
                continue
            curr  = companies[cid]["price"]
            prev  = companies[cid].get("prev_price", curr)
            direc = bet.get("direction")
            tgt   = bet.get("target", 0)
            amt   = bet.get("amount", 0)
            correct_dir = (
                (direc == "up"   and curr > prev) or
                (direc == "down" and curr < prev)
            )
            target_hit = (
                (direc == "up"   and curr >= tgt) or
                (direc == "down" and curr <= tgt)
            )
            cname = companies[cid]["name"]
            if correct_dir and target_hit:
                payout = amt * 3
                p["cash"] += payout
                await manager.send_player(p["code"], {
                    "type": "info",
                    "msg":  f"🎯 Prediction HIT! {cname} — direction + target correct. 3× payout: +₹{payout:,}",
                })
            elif correct_dir:
                payout = int(amt * 1.5)
                p["cash"] += payout
                await manager.send_player(p["code"], {
                    "type": "info",
                    "msg":  f"✅ Prediction PARTIAL — direction correct, target not reached. 1.5× payout: +₹{payout:,}",
                })
            else:
                await manager.send_player(p["code"], {
                    "type": "info",
                    "msg":  f"❌ Prediction WRONG on {cname}. Bet of ₹{amt:,} lost.",
                })
            changed = True
        if changed:
            p["bets"] = {}
            await save_player(p)


# ═══════════════════════════════════════════════════════════════
#  CONNECTION MANAGER
# ═══════════════════════════════════════════════════════════════
class ConnectionManager:
    def __init__(self):
        self.players: Dict[str, WebSocket] = {}
        self.hosts:   list = []

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


# ═══════════════════════════════════════════════════════════════
#  LIFESPAN
# ═══════════════════════════════════════════════════════════════
@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
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


@app.get("/bm", response_class=HTMLResponse)
async def serve_bm():
    p = BASE_DIR / "bm.html"
    return HTMLResponse(p.read_text(encoding="utf-8") if p.exists() else "<h1>bm.html not found</h1>")


@app.get("/board", response_class=HTMLResponse)
async def serve_board():
    p = BASE_DIR / "board.html"
    return HTMLResponse(p.read_text(encoding="utf-8") if p.exists() else "<h1>board.html not found</h1>")


# ═══════════════════════════════════════════════════════════════
#  REST: CODE MANAGEMENT
# ═══════════════════════════════════════════════════════════════
@app.post("/api/codes/generate")
async def generate_codes(count: int = 10):
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


@app.get("/api/codes")
async def list_codes():
    codes   = await all_codes()
    players = await all_players()
    used    = {p["code"] for p in players if p["name"]}
    return {"codes": sorted(codes), "used": sorted(used)}


@app.delete("/api/codes/{code}")
async def delete_code(code: str):
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
async def api_state():
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
async def api_players():
    state        = await read_state()
    players      = await all_players()
    board        = leaderboard(players, state)
    name_to_code = {p["name"]: p["code"] for p in players if p["name"]}
    return {"players": name_to_code, "board": board}


@app.get("/api/players/detail")
async def api_players_detail():
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


@app.get("/api/predictions/overview")
async def api_predictions_overview():
    state     = await read_state()
    players   = await all_players()
    sentiment = compute_sentiment(players, state["companies"])
    all_bets  = []
    for p in players:
        for cid, bet in (p.get("bets") or {}).items():
            all_bets.append({
                "player":     p["name"],
                "stock":      cid,
                "stock_name": state["companies"].get(cid, {}).get("name", cid),
                "direction":  bet.get("direction"),
                "target":     bet.get("target"),
                "amount":     bet.get("amount"),
            })
    return {"sentiment": sentiment, "bets": all_bets}


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
        state["round"] += 1
        state["phase"]          = "trading"
        state["round_end_time"] = time.time() + ROUND_DURATION
        state["break_end_time"] = None
        # Reset per-round chaos effects
        state["regulatory_freeze"] = None
        state["acquisition_pair"]  = None
        state["credit_crunch"]     = False
        # Clean up expired merge bids from previous rounds
        state["merge_bids"] = {}
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
        # Round 3 -> 4 break is extended to 20 min — reserved for a bigger event/twist later on.
        this_break_duration     = 1200 if state["round"] == 3 else BREAK_DURATION
        state["break_end_time"] = time.time() + this_break_duration
        state["break_duration"] = this_break_duration
        state["regulatory_freeze"] = None
        state["acquisition_pair"]  = None
        state["merge_bids"]        = {}
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

        # ── Taxes: income tax on this round's realized gains (everyone with a
        # profit), wealth tax on whoever's currently in 1st place. Automatic,
        # every round — no host button needed. ──────────────────────────────
        board_pre_tax = leaderboard(players, state)
        leader_names  = {board_pre_tax[0]["name"]} if board_pre_tax else set()
        tax_summary   = []
        for p in players:
            if not p["name"]:
                continue
            income_tax = 0
            realized   = p.get("realized_pnl_round", 0)
            if realized > 0:
                income_tax = round(realized * INCOME_TAX_RATE)
            wealth_tax = 0
            if p["name"] in leader_names:
                wealth_tax = round(player_view(p, state)["net_worth"] * WEALTH_TAX_RATE)
            if income_tax or wealth_tax:
                p["cash"] -= (income_tax + wealth_tax)
                await save_player(p)
                tax_summary.append({"name": p["name"], "income_tax": income_tax, "wealth_tax": wealth_tax})
                parts = []
                if income_tax: parts.append(f"Income tax ₹{income_tax:,} (on ₹{round(realized):,} realized gains)")
                if wealth_tax: parts.append(f"Wealth tax ₹{wealth_tax:,} (you're #1)")
                await manager.send_player(p["code"], {
                    "type": "player_update", "player": player_view(p, state),
                    "msg":  "🧾 " + " + ".join(parts),
                })

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

        # ── Round summary: biggest winner/loser, most active trader ─────────
        summary_rows = []
        for p in players:
            if not p["name"]:
                continue
            start_nw = p.get("net_worth_at_round_start", 0)
            end_nw   = player_view(p, state)["net_worth"]
            summary_rows.append({"name": p["name"], "delta": round(end_nw - start_nw),
                                  "trades": p.get("trades_this_round", 0)})
        round_summary = {
            "round":       state["round"],
            "winner":      max(summary_rows, key=lambda r: r["delta"],  default=None),
            "loser":       min(summary_rows, key=lambda r: r["delta"],  default=None),
            "most_active": max(summary_rows, key=lambda r: r["trades"], default=None),
            "taxes":       tax_summary,
        }
        state["last_round_summary"] = round_summary
        state.setdefault("round_summaries", []).append(round_summary)
        # Pre-generate next round's news now, so an Early Word purchase during this
        # break reveals the SAME headlines that will actually run at start_round.
        next_round_num       = state["round"] + 1
        next_news_count       = 2 if next_round_num == 1 else 3
        state["pending_news"] = pick_news(state, next_news_count)
        # Resolve prediction bets
        players = await all_players()
        await resolve_predictions(state, players)
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
        state          = await read_state()
        state["phase"] = "ended"
        await write_state(state)
    players = await all_players()
    board   = leaderboard(players, state)
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
    total_income_tax = sum(t["income_tax"] for s in summaries for t in s.get("taxes", []))
    total_wealth_tax  = sum(t["wealth_tax"] for s in summaries for t in s.get("taxes", []))

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
            options = NEWS_PRESETS.get(affects, {}).get(dir_key, [])
            if options:
                text = random.choice(options)
            else:
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


@app.post("/api/chaos/dividend")
async def chaos_dividend(data: dict, pw: str):
    """Pay a dividend per share to all holders of a company."""
    if pw != HOST_PASSWORD:
        raise HTTPException(403, "Wrong password")
    state     = await read_state()
    cid       = data["stock"]
    per_share = int(data["per_share"])
    if cid not in state["companies"]:
        raise HTTPException(400, "Unknown stock")
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
    return {"ok": True, "total_paid": total_out}


@app.post("/api/chaos/acquisition_rumour")
async def chaos_acquisition(data: dict, pw: str):
    """Correlate two companies' price movements for this round."""
    if pw != HOST_PASSWORD:
        raise HTTPException(403, "Wrong password")
    cid1  = data["stock1"]
    cid2  = data["stock2"]
    async with STATE_LOCK:
        state = await read_state()
        if cid1 not in state["companies"] or cid2 not in state["companies"]:
            raise HTTPException(400, "Unknown stocks")
        state["acquisition_pair"] = [cid1, cid2]
        await write_state(state)
    n1  = state["companies"][cid1]["name"]
    n2  = state["companies"][cid2]["name"]
    msg = f"🤝 ACQUISITION RUMOUR — {n1} and {n2} reportedly in merger talks! Their prices will move in tandem. (Unverified)"
    news_item = {
        "id": uuid.uuid4().hex[:8], "type_tag": "unverified", "label": "Unverified Rumour",
        "affects": cid1, "direction": 1, "real": False, "text": msg, "reactions": {},
    }
    async with STATE_LOCK:
        state = await read_state()
        state["news"].append(news_item)
        await write_state(state)
    await manager.broadcast_all({"type": "chaos", "event": "acquisition_rumour", "msg": msg})
    await manager.broadcast_all({"type": "news", **news_item})
    players = await all_players()
    board   = leaderboard(players, state)
    await manager.broadcast_hosts({"type": "state_update", "state": state, "board": board})
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


@app.post("/api/chaos/ipo_drop/{ipo_id}")
async def chaos_ipo_drop(ipo_id: str, pw: str):
    """List an IPO company mid-game."""
    if pw != HOST_PASSWORD:
        raise HTTPException(403, "Wrong password")
    if ipo_id not in IPO_COMPANIES:
        raise HTTPException(400, f"Unknown IPO: {ipo_id}")
    async with STATE_LOCK:
        state = await read_state()
        if ipo_id in state.get("ipo_listed", []):
            raise HTTPException(400, f"{ipo_id} is already listed")
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
    msg = f"🚀 IPO DROP — {ipo['name']} lists on the exchange! {ipo['trait']} IPO price: ₹{ipo['price']:,}"
    await manager.broadcast_all({
        "type":    "chaos",
        "event":   "ipo_drop",
        "msg":     msg,
        "company": {"id": ipo_id, **ipo},
    })
    players = await all_players()
    board   = leaderboard(players, state)
    await manager.broadcast_hosts({"type": "state_update", "state": state, "board": board})
    return {"ok": True, "company": {"id": ipo_id, **ipo}}


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
#  REST: BLACK MARKET
# ═══════════════════════════════════════════════════════════════
@app.get("/api/bm/items")
async def bm_items(code: str):
    p = await get_player(code.upper())
    if not p:
        raise HTTPException(404, "Player not found")
    used_leak = any(e["item"] == "leak_card" for e in p.get("bm_log", []))
    items = [
        {**item, "locked": item["id"] == "leak_card" and used_leak}
        for item in BM_ITEMS.values()
    ]
    return {"items": items, "cash": p["cash"], "name": p["name"]}


@app.post("/api/bm/buy")
async def bm_buy(data: dict):
    """
    Purchase a black market item.
    Body: { code, item_id, stock?, direction?, text? }
    """
    code    = (data.get("code") or "").upper()
    item_id = data.get("item_id")

    async with _player_locks[code]:
        p = await get_player(code)
        if not p or not p["name"]:
            raise HTTPException(400, "Invalid player")
        if item_id not in BM_ITEMS:
            raise HTTPException(400, "Unknown item")
        item  = BM_ITEMS[item_id]
        cost  = item["cost"]
        state = await read_state()
        if p["cash"] < cost:
            raise HTTPException(400, f"Not enough cash. Need ₹{cost:,}, have ₹{int(p['cash']):,}.")
        if item_id == "leak_card":
            if any(e["item"] == "leak_card" for e in p.get("bm_log", [])):
                raise HTTPException(400, "You've already used your Leak Card this game.")

        p["cash"] -= cost
        log_entry: dict = {"item": item_id, "cost": cost, "ts": time.time(), "player": p["name"]}

        # ── Insider Hint ─────────────────────────────────────────────
        if item_id == "insider_hint":
            pool = [h for h in INSIDER_HINTS if h[0] in state["companies"]]
            if not pool:
                raise HTTPException(500, "No hints available right now.")
            cid, direction, strength, text = random.choice(pool)
            log_entry.update({"stock": cid, "direction": direction, "text": text})
            await manager.send_player(code, {
                "type":     "news",
                "label":    "🔍 Insider Hint",
                "text":     text,
                "private":  True,
                "type_tag": "unverified",
            })

        # ── Spread Rumour ────────────────────────────────────────────
        elif item_id in ("spread_rumour", "leak_card"):
            stock     = data.get("stock")
            direction = safe_int(data.get("direction"), 1)
            text      = re.sub(r"[<>]", "", (data.get("text") or "").strip())[:200]
            if not stock or stock not in state["companies"]:
                raise HTTPException(400, "Pick a valid stock.")
            if not text:
                raise HTTPException(400, "Rumour text is required.")
            log_entry.update({"stock": stock, "direction": direction, "text": text})
            is_leak  = item_id == "leak_card"
            strength = random.uniform(0.10, 0.18) if is_leak else random.uniform(0.06, 0.12)
            is_real  = True if is_leak else (random.random() < 0.5)
            n = {
                "id":        uuid.uuid4().hex[:8],
                "type_tag":  "unverified",
                "label":     "Unverified Rumour",
                "affects":   stock,
                "direction": direction,
                "strength":  strength,
                "real":      is_real,
                "text":      text,
                "reactions": {},
            }
            async with STATE_LOCK:
                fresh_state = await read_state()
                fresh_state["news"].append(n)
                c = fresh_state["companies"].get(stock)
                if c and is_real and fresh_state["phase"] == "trading":
                    c["prev_price"] = c["price"]
                    floor           = PRICE_FLOORS.get(stock, 10)
                    c["price"]        = max(floor, round(c["price"] * (1 + direction * strength)))
                    c["target_price"] = c["price"]
                await write_state(fresh_state)
                state = fresh_state
            await manager.broadcast_all({"type": "news", **n})
            players_all = await all_players()
            board_now   = leaderboard(players_all, state)
            await manager.broadcast_all({
                "type":   "prices_bulk",
                "prices": {k: v["price"] for k, v in state["companies"].items()},
                "board":  board_now,
            })
            icon = "🃏" if is_leak else "📢"
            await manager.send_player(code, {
                "type": "info",
                "msg":  f"{icon} {'Leak Card deployed' if is_leak else 'Rumour spread'} on {state['companies'][stock]['name']}. Anonymous.",
            })
            await manager.broadcast_hosts({"type": "state_update", "state": state, "board": board_now})

        # ── Price Freeze Hack ────────────────────────────────────────
        elif item_id == "price_freeze":
            stock = data.get("stock")
            if not stock or stock not in state["companies"]:
                raise HTTPException(400, "Pick a valid stock.")
            until = time.time() + 60
            log_entry.update({"stock": stock})
            async with STATE_LOCK:
                fresh_state = await read_state()
                fresh_state.setdefault("price_freezes", {})[stock] = until
                await write_state(fresh_state)
                state = fresh_state
            cname = state["companies"][stock]["name"]
            # Market-wide but anonymous — everyone feels it, nobody knows who did it.
            await manager.broadcast_all({
                "type": "chaos", "event": "price_freeze",
                "msg":  f"🧊 PRICE FREEZE — {cname}'s price feed is locked for 60 seconds. Unusual activity detected.",
                "stock": stock, "until": until,
            })
            await manager.send_player(code, {"type": "info", "msg": f"🧊 {cname} frozen for 60s. Anonymous."})
            players_all = await all_players()
            board_now   = leaderboard(players_all, state)
            await manager.broadcast_hosts({"type": "state_update", "state": state, "board": board_now})

        # ── Rate Freeze Coupon ───────────────────────────────────────
        elif item_id == "rate_freeze":
            bank_id = data.get("bank_id")
            if bank_id not in BANKS:
                raise HTTPException(400, "Pick a valid bank.")
            balance = (p.get("loans") or {}).get(bank_id, 0)
            if balance <= 0:
                raise HTTPException(400, f"You don't have an outstanding loan with {BANKS[bank_id]['name']}.")
            locked_rate = bank_rate_for_balance(bank_id, balance)
            p["rate_locks"] = {**(p.get("rate_locks") or {}), bank_id: locked_rate}
            log_entry.update({"bank_id": bank_id, "locked_rate": locked_rate})
            await manager.send_player(code, {
                "type": "info",
                "msg":  f"🔒 {BANKS[bank_id]['name']} rate locked at {locked_rate*100:.0f}% for its next round-end charge.",
            })

        # ── Portfolio Peek ────────────────────────────────────────────
        elif item_id == "portfolio_peek":
            target_name = (data.get("target_name") or "").strip()
            if not target_name:
                raise HTTPException(400, "Pick a rival to peek at.")
            all_p  = await all_players()
            target = next((tp for tp in all_p if tp.get("name") == target_name and tp["code"] != code), None)
            if not target:
                raise HTTPException(400, "Couldn't find that player.")
            tv = player_view(target, state)
            holdings_txt = ", ".join(
                f"{h['qty']}× {state['companies'].get(cid,{}).get('name',cid)}"
                for cid, h in tv.get("portfolio", {}).items() if h.get("qty")
            ) or "no holdings"
            log_entry.update({"target": target_name})
            await manager.send_player(code, {
                "type": "info",
                "msg":  (f"🕵️ {target_name} — Cash: ₹{int(tv['cash']):,} · "
                         f"Loans: ₹{int(tv['total_loan']):,} · Holdings: {holdings_txt}"),
            })

        # ── Early Word ────────────────────────────────────────────────
        elif item_id == "early_word":
            if state["phase"] != "break":
                raise HTTPException(400, "Early Word only works during a break, ahead of the next round.")
            upcoming = state.get("pending_news", [])
            if not upcoming:
                raise HTTPException(400, "Nothing queued up yet — try again in a moment.")
            headlines = "  |  ".join(n["text"] for n in upcoming)
            await manager.send_player(code, {
                "type": "info",
                "msg":  f"🔮 Next round's headlines: {headlines}",
            })

        p["bm_log"] = p.get("bm_log", []) + [log_entry]
        await save_player(p)
        await manager.broadcast_hosts({"type": "bm_log_update", "entry": log_entry})
        return {"ok": True, "cash": p["cash"], "item": item_id}


@app.get("/api/bm/log")
async def bm_log(pw: str):
    if pw != HOST_PASSWORD:
        raise HTTPException(403, "Wrong password")
    players = await all_players()
    log = []
    for p in players:
        for entry in (p.get("bm_log") or []):
            log.append({**entry, "player": p["name"], "code": p["code"]})
    log.sort(key=lambda x: x.get("ts", 0), reverse=True)
    return {"log": log}


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
        "market":        state["companies"],
        "board":         leaderboard(await all_players(), state),
        "banks":         BANKS,
        "joined":        already_joined,
        "reg_freeze":    state.get("regulatory_freeze"),
        "credit_crunch": state.get("credit_crunch", False),
        "price_history": state.get("price_history", {}),
        "news":          state.get("news", []),
        "merged_into":   player.get("merged_into") if player else None,
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

                if player and player.get("merged_into") and action not in ("react_news", "team_merge_respond"):
                    survivor = await get_player(player["merged_into"])
                    await websocket.send_text(json.dumps({
                        "type": "error",
                        "msg":  f"Your account merged into {survivor['name'] if survivor else 'your teammate'}'s team — trade from their device instead.",
                    }))
                    continue

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
                            "avg_cost": {}, "bets": {}, "bm_log": [],
                        }
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
                        price  = state["companies"][stock]["price"]
                        cost   = price * qty
                        if player["cash"] < cost:
                            await websocket.send_text(json.dumps({"type": "error", "msg": f"Need ₹{cost:,}. You have ₹{int(player['cash']):,}."})); continue
                        old_qty = player["holdings"].get(stock, 0)
                        old_avg = player["avg_cost"].get(stock, price)
                        player["avg_cost"][stock] = ((old_avg * old_qty + price * qty) / (old_qty + qty)) if old_qty else price
                        player["holdings"][stock]  = old_qty + qty
                        player["cash"]            -= cost
                        player["trades_this_round"] = player.get("trades_this_round", 0) + 1
                        await save_player(player)
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
                        price = state["companies"][stock]["price"]
                        avg_cost = player.get("avg_cost", {}).get(stock, price)
                        realized = (price - avg_cost) * qty
                        player["cash"]             += price * qty
                        player["holdings"][stock]   = owned - qty
                        player["trades_this_round"]  = player.get("trades_this_round", 0) + 1
                        player["realized_pnl_round"] = player.get("realized_pnl_round", 0) + realized
                        await save_player(player)
                    pv = player_view(player, state)
                    await websocket.send_text(json.dumps({
                        "type":   "trade_ok",
                        "msg":    f"Sold {qty}× {state['companies'][stock]['name']} @ ₹{price:,}",
                        "player": pv,
                    }))
                    board = leaderboard(await all_players(), state)
                    await manager.broadcast_all({"type": "leaderboard", "board": board})

                # ── Short Sell ────────────────────────────────────────────
                elif action == "short_sell":
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
                    if state["companies"][stock].get("is_fund") or state["companies"][stock].get("is_etf"):
                        await websocket.send_text(json.dumps({"type": "error", "msg": "Funds and ETFs can't be shorted."})); continue
                    freeze = state.get("regulatory_freeze")
                    if freeze and state["companies"][stock].get("sector") == freeze:
                        await websocket.send_text(json.dumps({"type": "error", "msg": "⛔ Regulatory Freeze — no trading in this sector."})); continue
                    async with _player_locks[code]:
                        player   = await get_player(code)
                        state    = await read_state()
                        price    = state["companies"][stock]["price"]
                        proceeds = price * qty
                        margin   = round(proceeds * SHORT_MARGIN_PCT)
                        if player["cash"] < margin:
                            await websocket.send_text(json.dumps({"type": "error", "msg": f"Need ₹{margin:,} margin ({int(SHORT_MARGIN_PCT*100)}% of position) to open this short. You have ₹{int(player['cash']):,}."})); continue
                        shorts   = player.get("shorts", {})
                        existing = shorts.get(stock)
                        if existing:
                            new_qty   = existing["qty"] + qty
                            new_entry = (existing["entry_price"] * existing["qty"] + price * qty) / new_qty
                            shorts[stock] = {"qty": new_qty, "entry_price": new_entry}
                        else:
                            shorts[stock] = {"qty": qty, "entry_price": price}
                        player["shorts"]             = shorts
                        player["cash"]              += proceeds
                        player["trades_this_round"]  = player.get("trades_this_round", 0) + 1
                        await save_player(player)
                    pv = player_view(player, state)
                    await websocket.send_text(json.dumps({
                        "type":   "trade_ok",
                        "msg":    f"🔻 Shorted {qty}× {state['companies'][stock]['name']} @ ₹{price:,}. Proceeds banked — you owe the shares back.",
                        "player": pv,
                    }))
                    board = leaderboard(await all_players(), state)
                    await manager.broadcast_all({"type": "leaderboard", "board": board})

                # ── Cover Short ───────────────────────────────────────────
                elif action == "cover_short":
                    if state["phase"] != "trading":
                        await websocket.send_text(json.dumps({"type": "error", "msg": "Trading is closed."})); continue
                    if not player:
                        await websocket.send_text(json.dumps({"type": "error", "msg": "Join first."})); continue
                    stock = msg.get("stock")
                    async with _player_locks[code]:
                        player = await get_player(code)
                        state  = await read_state()
                        shorts = player.get("shorts", {})
                        pos    = shorts.get(stock)
                        if not pos or pos.get("qty", 0) < 1:
                            await websocket.send_text(json.dumps({"type": "error", "msg": "No open short on that stock."})); continue
                        price         = state["companies"][stock]["price"]
                        qty           = pos["qty"]
                        cost_to_cover = price * qty
                        if player["cash"] < cost_to_cover:
                            await websocket.send_text(json.dumps({"type": "error", "msg": f"Need ₹{int(cost_to_cover):,} to cover — you have ₹{int(player['cash']):,}. Sell something first."})); continue
                        realized = (pos["entry_price"] - price) * qty
                        player["cash"]               -= cost_to_cover
                        player["realized_pnl_round"]  = player.get("realized_pnl_round", 0) + realized
                        del shorts[stock]
                        player["shorts"]              = shorts
                        player["trades_this_round"]   = player.get("trades_this_round", 0) + 1
                        await save_player(player)
                    pv   = player_view(player, state)
                    sign = "+" if realized >= 0 else ""
                    await websocket.send_text(json.dumps({
                        "type":   "trade_ok",
                        "msg":    f"Covered {qty}× {state['companies'][stock]['name']} @ ₹{price:,}. P&L: {sign}₹{int(realized):,}",
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
                        player["bets"]        = {}   # bets cleared; stakes already deducted — treat as lost
                        player["avg_cost"]    = {}
                        player["shorts"]      = {}   # open shorts wiped too — you no longer owe those shares
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
                elif action == "place_bet":
                    if state["phase"] != "trading":
                        await websocket.send_text(json.dumps({"type": "error", "msg": "Bets can only be placed during trading rounds."})); continue
                    if not player:
                        await websocket.send_text(json.dumps({"type": "error", "msg": "Join first."})); continue
                    stock     = msg.get("stock")
                    direction = msg.get("direction")
                    target    = safe_float(msg.get("target"), 0)
                    amount    = safe_int(msg.get("amount"), 0)
                    if stock not in state["companies"]:
                        await websocket.send_text(json.dumps({"type": "error", "msg": "Invalid stock."})); continue
                    if direction not in ("up", "down"):
                        await websocket.send_text(json.dumps({"type": "error", "msg": "Direction must be 'up' or 'down'."})); continue
                    curr_price = state["companies"][stock]["price"]
                    if direction == "up"   and target <= curr_price:
                        await websocket.send_text(json.dumps({"type": "error", "msg": f"Target must be above current price ₹{curr_price:,}."})); continue
                    if direction == "down" and target >= curr_price:
                        await websocket.send_text(json.dumps({"type": "error", "msg": f"Target must be below current price ₹{curr_price:,}."})); continue
                    if amount < 1000:
                        await websocket.send_text(json.dumps({"type": "error", "msg": "Minimum bet is ₹1,000."})); continue
                    async with _player_locks[code]:
                        player = await get_player(code)
                        if amount > player["cash"]:
                            await websocket.send_text(json.dumps({"type": "error", "msg": f"Max bet ₹{int(player['cash']):,}."})); continue
                        if stock in (player.get("bets") or {}):
                            await websocket.send_text(json.dumps({"type": "error", "msg": "Already have an open bet on this stock."})); continue
                        player["cash"] -= amount
                        player.setdefault("bets", {})[stock] = {
                            "direction": direction,
                            "target":    target,
                            "amount":    amount,
                            "locked_at": curr_price,
                        }
                        await save_player(player)
                    pv = player_view(player, state)
                    cname = state["companies"][stock]["name"]
                    sentiment = compute_sentiment(await all_players(), state["companies"])
                    await manager.broadcast_all({"type": "sentiment_update", "sentiment": sentiment})
                    await websocket.send_text(json.dumps({
                        "type":   "trade_ok",
                        "msg":    f"Bet ₹{amount:,} on {cname} going {direction.upper()} to ₹{int(target):,}.",
                        "player": pv,
                    }))

                # ── Merger: initiate ──────────────────────────────────────
                elif action == "merge_initiate":
                    if state["phase"] != "trading" or not player:
                        await websocket.send_text(json.dumps({"type": "error", "msg": "Can only merge during trading."})); continue
                    partner_code = (msg.get("partner_code") or "").upper()
                    stock        = msg.get("stock")
                    qty          = safe_int(msg.get("qty"), 0)
                    if stock not in state["companies"] or qty < 1:
                        await websocket.send_text(json.dumps({"type": "error", "msg": "Invalid merger request."})); continue
                    if partner_code == code:
                        await websocket.send_text(json.dumps({"type": "error", "msg": "Can't merge with yourself."})); continue
                    partner = await get_player(partner_code)
                    if not partner or not partner["name"]:
                        await websocket.send_text(json.dumps({"type": "error", "msg": "Partner not found."})); continue
                    price  = state["companies"][stock]["price"]
                    each   = round(price * qty / 2)   # each pays half
                    # Validate both sides can afford it
                    if player["cash"] < each:
                        await websocket.send_text(json.dumps({"type": "error", "msg": f"You need ₹{each:,} for this merger."})); continue
                    bid_id = uuid.uuid4().hex[:8]
                    async with STATE_LOCK:
                        # Re-read right before mutating — `state` above may be a
                        # few awaits stale by now, and this write touches shared
                        # game state that the price loops also write every 4-20s.
                        fresh_state = await read_state()
                        fresh_state["merge_bids"][bid_id] = {
                            "from_code":    code,
                            "from_name":    player["name"],
                            "partner_code": partner_code,
                            "stock":        stock,
                            "qty":          qty,
                            "each":         each,
                            "ts":           time.time(),
                        }
                        await write_state(fresh_state)
                    await manager.send_player(partner_code, {
                        "type":    "merge_request",
                        "bid_id":  bid_id,
                        "from":    player["name"],
                        "stock":   stock,
                        "stock_name": state["companies"][stock]["name"],
                        "qty":     qty,
                        "each":    each,
                    })
                    await websocket.send_text(json.dumps({"type": "info", "msg": f"Merger request sent to {partner['name']}."}))

                # ── Merger: respond ───────────────────────────────────────
                elif action == "merge_respond":
                    bid_id = msg.get("bid_id")
                    accept = msg.get("accept", False)
                    state  = await read_state()
                    bid    = state.get("merge_bids", {}).get(bid_id)
                    if not bid:
                        await websocket.send_text(json.dumps({"type": "error", "msg": "Merger bid expired or not found."})); continue
                    if not accept:
                        async with STATE_LOCK:
                            fresh_state = await read_state()
                            fresh_state.get("merge_bids", {}).pop(bid_id, None)
                            await write_state(fresh_state)
                        await manager.send_player(bid["from_code"], {
                            "type": "info",
                            "msg":  f"{player['name']} declined the merger.",
                        })
                        await websocket.send_text(json.dumps({"type": "info", "msg": "Merger declined."}))
                        continue
                    # Accept: both pay `each`, both receive qty//2 shares
                    # (initiator gets ceil, responder gets floor on odd quantities)
                    p_init = await get_player(bid["from_code"])
                    p_resp = await get_player(bid["partner_code"])
                    stock  = bid["stock"]
                    qty    = bid["qty"]
                    each   = bid["each"]
                    price  = state["companies"][stock]["price"]
                    qty_init = (qty + 1) // 2   # ceiling
                    qty_resp = qty // 2         # floor

                    if p_init is None or p_resp is None:
                        await websocket.send_text(json.dumps({"type": "error", "msg": "A player in the merger has left."})); continue
                    if p_init["cash"] < each:
                        await websocket.send_text(json.dumps({"type": "error", "msg": f"{p_init['name']} can no longer afford the merger."})); continue
                    if p_resp["cash"] < each:
                        await websocket.send_text(json.dumps({"type": "error", "msg": "You can no longer afford the merger."})); continue

                    async with _player_locks[bid["from_code"]], _player_locks[bid["partner_code"]]:
                        p_init = await get_player(bid["from_code"])
                        p_resp = await get_player(bid["partner_code"])
                        # Deduct cost from both
                        p_init["cash"] -= each
                        p_resp["cash"] -= each
                        # Distribute shares
                        for p_side, q in [(p_init, qty_init), (p_resp, qty_resp)]:
                            old_q   = p_side["holdings"].get(stock, 0)
                            old_avg = p_side["avg_cost"].get(stock, price)
                            p_side["avg_cost"][stock] = ((old_avg * old_q + price * q) / (old_q + q)) if old_q else price
                            p_side["holdings"][stock]  = old_q + q
                        await save_player(p_init)
                        await save_player(p_resp)

                    async with STATE_LOCK:
                        fresh_state = await read_state()
                        fresh_state.get("merge_bids", {}).pop(bid_id, None)
                        await write_state(fresh_state)
                        state = fresh_state
                    cname = state["companies"][stock]["name"]
                    await manager.send_player(bid["from_code"], {
                        "type":   "player_update",
                        "player": player_view(p_init, state),
                    })
                    await manager.send_player(bid["partner_code"], {
                        "type":   "player_update",
                        "player": player_view(p_resp, state),
                    })
                    await manager.send_player(bid["from_code"], {
                        "type": "info",
                        "msg":  f"Merger complete! You received {qty_init}× {cname}.",
                    })
                    await websocket.send_text(json.dumps({
                        "type": "info",
                        "msg":  f"Merger complete! You received {qty_resp}× {cname}.",
                    }))

                # ── Full Team Merger — permanently combine two accounts ──────
                elif action == "team_merge_propose":
                    if not player:
                        await websocket.send_text(json.dumps({"type": "error", "msg": "Join first."})); continue
                    partner_code = (msg.get("partner_code") or "").strip().upper()
                    if not partner_code or partner_code == code:
                        await websocket.send_text(json.dumps({"type": "error", "msg": "Enter a different player's code."})); continue
                    partner = await get_player(partner_code)
                    if not partner or not partner["name"]:
                        await websocket.send_text(json.dumps({"type": "error", "msg": "No player found with that code."})); continue
                    if partner.get("merged_into") or player.get("merged_into"):
                        await websocket.send_text(json.dumps({"type": "error", "msg": "One of you is already part of a merged team."})); continue
                    req_id = uuid.uuid4().hex[:8]
                    async with STATE_LOCK:
                        fresh_state = await read_state()
                        fresh_state.setdefault("team_merge_requests", {})[req_id] = {
                            "from_code": code, "from_name": player["name"],
                            "partner_code": partner_code, "ts": time.time(),
                        }
                        await write_state(fresh_state)
                    await manager.send_player(partner_code, {
                        "type": "team_merge_request", "req_id": req_id,
                        "from_name": player["name"], "from_code": code,
                    })
                    await websocket.send_text(json.dumps({"type": "info", "msg": f"Team merge proposal sent to {partner_code}."}))

                elif action == "team_merge_respond":
                    req_id = msg.get("req_id")
                    accept = bool(msg.get("accept"))
                    async with STATE_LOCK:
                        fresh_state = await read_state()
                        req = fresh_state.get("team_merge_requests", {}).pop(req_id, None)
                        await write_state(fresh_state)
                        state = fresh_state
                    if not req or req["partner_code"] != code:
                        await websocket.send_text(json.dumps({"type": "error", "msg": "That proposal isn't valid anymore."})); continue
                    if not accept:
                        await manager.send_player(req["from_code"], {"type": "info", "msg": f"{req['from_name']}, your team merge proposal was declined."})
                        await websocket.send_text(json.dumps({"type": "info", "msg": "Merge declined."}))
                        continue
                    async with _player_locks[req["from_code"]], _player_locks[code]:
                        survivor = await get_player(req["from_code"])
                        partner  = await get_player(code)
                        if not survivor or not partner or survivor.get("merged_into") or partner.get("merged_into"):
                            await websocket.send_text(json.dumps({"type": "error", "msg": "Merge couldn't complete — one of you already merged elsewhere."})); continue
                        survivor["cash"] += partner["cash"]
                        for cid, qty in partner.get("holdings", {}).items():
                            if qty <= 0: continue
                            old_qty = survivor["holdings"].get(cid, 0)
                            old_avg = survivor.get("avg_cost", {}).get(cid, 0)
                            p_avg   = partner.get("avg_cost", {}).get(cid, 0)
                            new_qty = old_qty + qty
                            new_avg = ((old_avg * old_qty) + (p_avg * qty)) / new_qty if new_qty else 0
                            survivor["holdings"][cid] = new_qty
                            survivor.setdefault("avg_cost", {})[cid] = new_avg
                        for bank_id, bal in partner.get("loans", {}).items():
                            if bal <= 0: continue
                            survivor["loans"][bank_id] = survivor.get("loans", {}).get(bank_id, 0) + bal
                        for cid, sp in partner.get("shorts", {}).items():
                            if sp.get("qty", 0) <= 0: continue
                            old = survivor.get("shorts", {}).get(cid)
                            if old:
                                new_qty   = old["qty"] + sp["qty"]
                                new_entry = ((old["entry_price"] * old["qty"]) + (sp["entry_price"] * sp["qty"])) / new_qty
                                survivor["shorts"][cid] = {"qty": new_qty, "entry_price": new_entry}
                            else:
                                survivor.setdefault("shorts", {})[cid] = sp
                        # Predictions don't merge cleanly — cancel and refund the stake into the team pot
                        for cid, bet in partner.get("bets", {}).items():
                            survivor["cash"] += bet.get("amount", 0)
                        survivor_old_name = survivor["name"]
                        survivor["name"]             = f"{survivor_old_name} & {partner['name']}"
                        survivor["merged_partners"]  = survivor.get("merged_partners", []) + [partner["name"]]
                        await save_player(survivor)
                        partner["cash"]        = 0
                        partner["holdings"]    = {}
                        partner["loans"]       = {}
                        partner["shorts"]      = {}
                        partner["bets"]        = {}
                        partner["stop_losses"] = {}
                        partner["insurance"]   = {}
                        partner["merged_into"] = req["from_code"]
                        await save_player(partner)
                    await manager.send_player(req["from_code"], {
                        "type":   "player_update", "player": player_view(survivor, state),
                        "msg":    f"🤝 {partner['name']} merged into your team! Combined resources are now yours.",
                    })
                    await websocket.send_text(json.dumps({
                        "type": "team_merge_done",
                        "msg":  f"Your account merged into {survivor_old_name}'s team. Trading now happens from their device for the rest of the game.",
                    }))
                    players_all = await all_players()
                    board_now   = leaderboard(players_all, state)
                    await manager.broadcast_all({"type": "leaderboard", "board": board_now})
                    await manager.broadcast_hosts({"type": "state_update", "state": state, "board": board_now})
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
    await manager.connect_host(websocket)
    try:
        state   = await read_state()
        players = await all_players()
        board   = leaderboard(players, state)
        await websocket.send_text(json.dumps({
            "type":         "state_update",
            "state":        state,
            "board":        board,
            "player_count": len([p for p in players if p["name"]]),
            "sentiment":    compute_sentiment(players, state["companies"]),
        }))
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
                    "sentiment":    compute_sentiment(players, state["companies"]),
                }))
    except WebSocketDisconnect:
        pass
    finally:
        manager.disconnect_host(websocket)