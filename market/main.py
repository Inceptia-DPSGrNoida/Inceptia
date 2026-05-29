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

# ═══════════════════════════════════════════════════════════════
#  CONFIG
# ═══════════════════════════════════════════════════════════════
DB_PATH            = Path(os.getenv("DB_PATH", "game.db"))
HOST_PASSWORD      = os.getenv("HOST_PASSWORD", "InceptiaHost2025")
STARTING_CASH      = 50_000
ROUND_DURATION     = 1200        # 20 min — host can end early
BREAK_DURATION     = 300         # 5 min between rounds
BANKRUPTCY_RESTART = 25_000
DRIFT_INTERVAL     = 90          # seconds between passive micro-drifts (reduced magnitude)
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
        "rate":    0.05,    # 5% per round, compounds on balance
        "desc":    "Safe, government-backed. Low rate, low limit. The sensible choice.",
    },
    "vcx": {
        "name":    "VentureCapX",
        "limit":   1_50_000,
        "options": [50_000, 75_000, 1_00_000, 1_50_000],
        "rate":    0.09,    # 9% per round
        "desc":    "Aggressive growth lender. Higher limit, higher cost. For calculated risks.",
    },
    "shadow": {
        "name":    "ShadowCredit",
        "limit":   3_00_000,
        "options": [1_00_000, 1_50_000, 2_00_000, 3_00_000],
        "rate":    0.16,    # 16% per round — compounding is brutal over 4 rounds
        "desc":    "No questions asked. Maximum leverage. Minimum mercy. 4-round compound: ~2.7×.",
    },
}

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
}

# Price floors per company (20% of IPO price — prevents absurd crashes)
PRICE_FLOORS = {
    "zora":      84,   "streamvx": 62,  "freshco": 37,  "voltex":   112,
    "mediq":     55,   "skylink":  178, "swifthaul": 68, "crownmart": 44,
    "shieldgen": 98,   "indranet": 86,  "novapay":  40,  "greenleaf": 30,
    "armorinc":  76,   "bytecorp": 130,
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
#  NEWS POOL
# ═══════════════════════════════════════════════════════════════
NEWS_POOL = [
    # ── ZORA (8)
    {"type":"verified",   "label":"Market Event",      "affects":"zora", "direction": 1, "strength":0.10, "real":True,
     "text":"Zora Industries secures ₹2,800 crore defence infrastructure contract from the Ministry of Defence — its third major government award this fiscal year."},
    {"type":"verified",   "label":"Market Event",      "affects":"zora", "direction":-1, "strength":0.09, "real":True,
     "text":"BREAKING: National union declares a 3-day strike at manufacturing hubs across 5 states. Zora's flagship Pune plant has shut down."},
    {"type":"verified",   "label":"Market Event",      "affects":"zora", "direction": 1, "strength":0.08, "real":True,
     "text":"Zora Industries marks 30 consecutive years of uninterrupted dividend payouts. LIC raises its stake by 4.2% in the latest quarter."},
    {"type":"verified",   "label":"Market Event",      "affects":"zora", "direction": 1, "strength":0.11, "real":True,
     "text":"Zora wins ₹4,600 crore port infrastructure contract in Odisha. Management upgrades full-year revenue guidance by 14%."},
    {"type":"verified",   "label":"Market Event",      "affects":"zora", "direction":-1, "strength":0.08, "real":True,
     "text":"Steel import duties slashed by 8%. Cheaper Chinese steel undercuts Zora's pricing in the domestic structural market."},
    {"type":"unverified", "label":"Unverified Rumour", "affects":"zora", "direction":-1, "strength":0.11, "real":False,
     "text":"Rumour: A whistleblower claims Zora used substandard materials in a recent government project. The company calls the allegations completely fabricated."},
    {"type":"unverified", "label":"Insider Hint",      "affects":"zora", "direction": 1, "strength":0.13, "real":True,
     "text":"Insider tip: Zora is in the final stage of negotiations for a ₹4,000 crore highway bridge contract. Award expected within days."},
    {"type":"unverified", "label":"Unverified Rumour", "affects":"zora", "direction": 1, "strength":0.10, "real":False,
     "text":"Rumour: A large sovereign wealth fund is accumulating Zora shares quietly ahead of an expected Q4 earnings beat."},
    # ── STREAMVERSE (9)
    {"type":"verified",   "label":"Market Event",      "affects":"streamvx", "direction":-1, "strength":0.12, "real":True,
     "text":"BREAKING: StreamVerse reports a 14% jump in subscriber churn after hiking monthly subscription prices by ₹100. Net adds turn negative for the first time."},
    {"type":"verified",   "label":"Market Event",      "affects":"streamvx", "direction": 1, "strength":0.13, "real":True,
     "text":"StreamVerse's latest original crime drama crosses 200 million watch hours in its first week — the biggest debut in Indian OTT history."},
    {"type":"verified",   "label":"Market Event",      "affects":"streamvx", "direction":-1, "strength":0.09, "real":True,
     "text":"Disney+ Hotstar announces an aggressive price cut and a major IPL streaming deal, directly targeting StreamVerse's urban subscriber base."},
    {"type":"verified",   "label":"Market Event",      "affects":"streamvx", "direction": 1, "strength":0.10, "real":True,
     "text":"StreamVerse signs a 3-year exclusive deal with India's top film studio, locking out all competitors from its most bankable directors."},
    {"type":"verified",   "label":"Market Event",      "affects":"streamvx", "direction":-1, "strength":0.11, "real":True,
     "text":"BREAKING: StreamVerse reports Q2 cash burn of ₹1,100 crore — 34% worse than analyst estimates. CFO steps down citing 'personal reasons'."},
    {"type":"verified",   "label":"Market Event",      "affects":"streamvx", "direction": 1, "strength":0.09, "real":True,
     "text":"StreamVerse ad-supported tier crosses 18 million users in 6 months — monetisation path finally becoming credible to sceptical analysts."},
    {"type":"unverified", "label":"Unverified Rumour", "affects":"streamvx", "direction":-1, "strength":0.10, "real":False,
     "text":"Rumour: A former StreamVerse VP claims the platform artificially inflates subscriber numbers to attract brand advertising. Management denies."},
    {"type":"unverified", "label":"Insider Hint",      "affects":"streamvx", "direction": 1, "strength":0.14, "real":True,
     "text":"Insider tip: StreamVerse is close to signing an exclusive cricket streaming deal for 3 IPL seasons — a contract reportedly worth ₹4,200 crore."},
    {"type":"unverified", "label":"Unverified Rumour", "affects":"streamvx", "direction": 1, "strength":0.12, "real":False,
     "text":"Rumour: A US streaming giant is in preliminary acquisition talks for StreamVerse at a 45% premium to current market price. Both sides unconfirmed."},
    # ── FRESHCO (8)
    {"type":"verified",   "label":"Market Event",      "affects":"freshco", "direction": 1, "strength":0.08, "real":True,
     "text":"Rural FMCG consumption hits a 6-year high. FreshCo's 6 million kirana distribution network gives it unmatched last-mile reach in the surge."},
    {"type":"verified",   "label":"Market Event",      "affects":"freshco", "direction":-1, "strength":0.10, "real":True,
     "text":"BREAKING: A cyclone warning is issued for the eastern coast. FreshCo's largest manufacturing cluster in Odisha has suspended operations."},
    {"type":"verified",   "label":"Market Event",      "affects":"freshco", "direction": 1, "strength":0.09, "real":True,
     "text":"FreshCo's new premium biscuit line sells out in 48 hours across modern trade. Early data suggests 22% margin improvement over base SKUs."},
    {"type":"verified",   "label":"Market Event",      "affects":"freshco", "direction":-1, "strength":0.08, "real":True,
     "text":"BREAKING: Palm oil prices surge 19% globally. FreshCo's input costs rise materially — margin guidance cut for the next two quarters."},
    {"type":"verified",   "label":"Market Event",      "affects":"freshco", "direction": 1, "strength":0.09, "real":True,
     "text":"FreshCo announces entry into the premium skincare segment targeting urban millennials. Analysts project ₹1,200 crore in incremental revenue by Year 3."},
    {"type":"unverified", "label":"Unverified Rumour", "affects":"freshco", "direction":-1, "strength":0.09, "real":False,
     "text":"Rumour: A viral social media post claims FreshCo's popular biscuit brand contains banned additives. Company calls it fabricated and is pursuing legal action."},
    {"type":"unverified", "label":"Insider Hint",      "affects":"freshco", "direction": 1, "strength":0.11, "real":True,
     "text":"Insider tip: FreshCo's rural distribution numbers for this quarter are reportedly far ahead of estimates. Formal guidance upgrade expected next week."},
    {"type":"unverified", "label":"Unverified Rumour", "affects":"freshco", "direction": 1, "strength":0.09, "real":False,
     "text":"Rumour: A global FMCG giant is reportedly in talks to acquire FreshCo's branded foods division at a significant premium. Unverified."},
    # ── VOLTEX (8)
    {"type":"verified",   "label":"Market Event",      "affects":"voltex", "direction": 1, "strength":0.12, "real":True,
     "text":"BREAKING: Government announces ₹4,200 crore renewable energy subsidy expansion. Voltex Energy named explicitly in the policy document as a primary beneficiary."},
    {"type":"verified",   "label":"Market Event",      "affects":"voltex", "direction":-1, "strength":0.11, "real":True,
     "text":"BREAKING: Two Voltex solar parks in Rajasthan fail safety inspections. Ministry of New Energy suspends project clearances pending a full review."},
    {"type":"verified",   "label":"Market Event",      "affects":"voltex", "direction": 1, "strength":0.10, "real":True,
     "text":"Voltex Energy signs its largest contract yet — a 900MW solar park for a state electricity board. Analysts revise price target upward by 35%."},
    {"type":"verified",   "label":"Market Event",      "affects":"voltex", "direction":-1, "strength":0.09, "real":True,
     "text":"Solar panel import tariffs hiked by 12%. Voltex's upcoming projects face a cost overrun of approximately ₹600 crore. Capex guidance raised."},
    {"type":"verified",   "label":"Market Event",      "affects":"voltex", "direction": 1, "strength":0.09, "real":True,
     "text":"India achieves a new solar installation record. REC prices jump 14%, directly boosting Voltex's near-term revenue per MW."},
    {"type":"unverified", "label":"Unverified Rumour", "affects":"voltex", "direction": 1, "strength":0.13, "real":False,
     "text":"Rumour: Voltex Energy allegedly in advanced merger talks with a UAE sovereign wealth fund. Could value the company at 3× current market cap. Unconfirmed."},
    {"type":"unverified", "label":"Insider Hint",      "affects":"voltex", "direction": 1, "strength":0.12, "real":True,
     "text":"Insider tip: Government officials have reportedly signed off internally on Voltex's subsidy renewal — announcement expected before close of quarter."},
    {"type":"unverified", "label":"Unverified Rumour", "affects":"voltex", "direction":-1, "strength":0.10, "real":False,
     "text":"Rumour: Voltex's Rajasthan solar project is reportedly 4 months behind schedule due to grid connection delays. Penalty clauses may apply."},
    # ── MEDIQ (8)
    {"type":"verified",   "label":"Market Event",      "affects":"mediq", "direction": 1, "strength":0.14, "real":True,
     "text":"MediQ's Phase 3 drug trial results submitted to DCGI. Internal sources describe the efficacy data as 'exceptionally strong'. Approval timeline: 30 days."},
    {"type":"verified",   "label":"Market Event",      "affects":"mediq", "direction":-1, "strength":0.15, "real":True,
     "text":"BREAKING: DCGI rejects MediQ's blockbuster drug application citing insufficient long-term safety data. Additional trials required — timeline pushed back 18 months."},
    {"type":"verified",   "label":"Market Event",      "affects":"mediq", "direction": 1, "strength":0.10, "real":True,
     "text":"MediQ quietly files 4 new patents for next-generation oncology drugs. Pipeline depth far exceeds what the market has priced in."},
    {"type":"verified",   "label":"Market Event",      "affects":"mediq", "direction":-1, "strength":0.10, "real":True,
     "text":"US FDA issues import alerts on MediQ's Hyderabad API manufacturing plant. Export revenues at risk until remediation is certified."},
    {"type":"verified",   "label":"Market Event",      "affects":"mediq", "direction": 1, "strength":0.09, "real":True,
     "text":"WHO qualifies MediQ as a preferred supplier for generic oncology APIs in 40 developing nations. Long-term export revenue locked in."},
    {"type":"unverified", "label":"Unverified Rumour", "affects":"mediq", "direction": 1, "strength":0.14, "real":False,
     "text":"Rumour: A global pharma giant is reportedly in acquisition talks for MediQ at a 60% premium to current price. Neither company has confirmed."},
    {"type":"unverified", "label":"Insider Hint",      "affects":"mediq", "direction": 1, "strength":0.14, "real":True,
     "text":"Insider tip: MediQ's Zytravax trial data is reportedly clean and strong. DCGI submission is imminent. Management unusually confident internally."},
    {"type":"unverified", "label":"Unverified Rumour", "affects":"mediq", "direction":-1, "strength":0.12, "real":False,
     "text":"Rumour: An adverse event in MediQ's Phase 3 trial is being reviewed internally. Nothing has been filed yet but whispers are spreading."},
    # ── SKYLINK (8)
    {"type":"verified",   "label":"Market Event",      "affects":"skylink", "direction": 1, "strength":0.11, "real":True,
     "text":"SkyLink Tech posts 34% YoY revenue growth in Q2, beating analyst consensus by ₹420 crore. Founder announces entry into Southeast Asian markets."},
    {"type":"verified",   "label":"Market Event",      "affects":"skylink", "direction":-1, "strength":0.13, "real":True,
     "text":"BREAKING: A massive data breach at SkyLink exposes 11 million user records. Government issues show-cause notice. Fines expected to exceed ₹800 crore."},
    {"type":"verified",   "label":"Market Event",      "affects":"skylink", "direction":-1, "strength":0.10, "real":True,
     "text":"SkyLink loses two large enterprise contracts to IndraNet in a competitive rebid. Churn at the top of the client book raises retention concerns."},
    {"type":"verified",   "label":"Market Event",      "affects":"skylink", "direction": 1, "strength":0.12, "real":True,
     "text":"SkyLink announces an AI product partnership with a top US tech firm — a deal that could fundamentally revalue the company's TAM story."},
    {"type":"verified",   "label":"Market Event",      "affects":"skylink", "direction":-1, "strength":0.09, "real":True,
     "text":"BREAKING: SkyLink founder sells ₹800 crore of personal stock. Insider selling at this scale typically signals concern about near-term outlook."},
    {"type":"unverified", "label":"Unverified Rumour", "affects":"skylink", "direction":-1, "strength":0.11, "real":False,
     "text":"Rumour: Three senior SkyLink engineers have resigned en masse over a dispute with the founder. Anonymous posts describe 'toxic leadership'. Unverified."},
    {"type":"unverified", "label":"Insider Hint",      "affects":"skylink", "direction": 1, "strength":0.13, "real":True,
     "text":"Insider tip: SkyLink's Q3 deal pipeline is reportedly the strongest in company history. An earnings surprise is quietly expected internally."},
    {"type":"unverified", "label":"Unverified Rumour", "affects":"skylink", "direction": 1, "strength":0.12, "real":False,
     "text":"Rumour: A global tech giant has submitted a non-binding indicative offer for SkyLink at 2.2× current price. Completely unverified."},
    # ── SWIFTHAUL (8)
    {"type":"verified",   "label":"Market Event",      "affects":"swifthaul", "direction": 1, "strength":0.10, "real":True,
     "text":"SwiftHaul reports a 28% surge in same-day delivery volume as festive season kicks off. Signs exclusive 3-year contract with India's largest e-commerce platform."},
    {"type":"verified",   "label":"Market Event",      "affects":"swifthaul", "direction":-1, "strength":0.10, "real":True,
     "text":"BREAKING: Fuel prices rise 12% following a global crude oil surge. SwiftHaul's fleet of 18,000 vehicles faces immediate margin compression."},
    {"type":"verified",   "label":"Market Event",      "affects":"swifthaul", "direction": 1, "strength":0.09, "real":True,
     "text":"SwiftHaul's cold-chain pharma division signs its first hospital chain client. High-margin recurring revenue materialises ahead of analyst forecasts."},
    {"type":"verified",   "label":"Market Event",      "affects":"swifthaul", "direction":-1, "strength":0.09, "real":True,
     "text":"A competing logistics firm poaches SwiftHaul's head of enterprise sales along with the team managing three key accounts. Client at-risk notices issued."},
    {"type":"verified",   "label":"Market Event",      "affects":"swifthaul", "direction": 1, "strength":0.08, "real":True,
     "text":"GST Council simplifies e-way bill compliance. SwiftHaul estimates ₹120 crore in annual cost savings from reduced administrative overhead."},
    {"type":"unverified", "label":"Unverified Rumour", "affects":"swifthaul", "direction":-1, "strength":0.10, "real":False,
     "text":"Rumour: SwiftHaul allegedly under-reporting delivery failure rates to maintain contract metrics. An internal audit is said to be underway."},
    {"type":"unverified", "label":"Insider Hint",      "affects":"swifthaul", "direction": 1, "strength":0.11, "real":True,
     "text":"Insider tip: SwiftHaul's cold-chain pharma division has onboarded 3 hospital chains. Revenue starts next quarter — not in consensus estimates."},
    {"type":"unverified", "label":"Unverified Rumour", "affects":"swifthaul", "direction":-1, "strength":0.09, "real":False,
     "text":"Rumour: SwiftHaul's primary e-commerce partner is running a quiet RFQ process with rival logistics firms. Contract renewal may not be automatic."},
    # ── CROWNMART (8)
    {"type":"verified",   "label":"Market Event",      "affects":"crownmart", "direction": 1, "strength":0.11, "real":True,
     "text":"CrownMart's new CEO unveils a restructuring plan: closing 120 loss-making stores and doubling down on high-margin private label products. Analysts react positively."},
    {"type":"verified",   "label":"Market Event",      "affects":"crownmart", "direction":-1, "strength":0.11, "real":True,
     "text":"BREAKING: Blinkit announces 10-minute grocery delivery expansion to 50 new cities — directly attacking CrownMart's core customer base in Tier-2 markets."},
    {"type":"verified",   "label":"Market Event",      "affects":"crownmart", "direction":-1, "strength":0.10, "real":True,
     "text":"CrownMart's Q3 same-store sales data shows a 9% decline. Results below guidance for the second consecutive quarter. Analysts cut targets."},
    {"type":"verified",   "label":"Market Event",      "affects":"crownmart", "direction": 1, "strength":0.10, "real":True,
     "text":"CrownMart's private label division posts 34% revenue growth. Margins on own-brand products are 18 percentage points above branded equivalents."},
    {"type":"verified",   "label":"Market Event",      "affects":"crownmart", "direction":-1, "strength":0.09, "real":True,
     "text":"CrownMart announces 40 additional store closures beyond the previously disclosed 120, citing structurally unviable lease terms."},
    {"type":"unverified", "label":"Unverified Rumour", "affects":"crownmart", "direction": 1, "strength":0.12, "real":False,
     "text":"Rumour: A major private equity firm is building a stake in CrownMart ahead of an alleged management buyout. Unusual after-hours trading activity spotted."},
    {"type":"unverified", "label":"Insider Hint",      "affects":"crownmart", "direction":-1, "strength":0.11, "real":True,
     "text":"Insider tip: CrownMart's Q3 same-store sales data, not yet public, shows a 9% decline. Insiders are quietly reducing positions ahead of results."},
    {"type":"unverified", "label":"Unverified Rumour", "affects":"crownmart", "direction": 1, "strength":0.10, "real":False,
     "text":"Rumour: CrownMart is in preliminary talks with a GCC-based sovereign retailer about a strategic investment and regional expansion partnership."},
    # ── SHIELDGEN (8)
    {"type":"verified",   "label":"Market Event",      "affects":"shieldgen", "direction": 1, "strength":0.12, "real":True,
     "text":"BREAKING: Escalating border tensions prompt the government to fast-track ₹18,000 crore in emergency defence procurement. ShieldGen is primary supplier for 3 of 5 categories."},
    {"type":"verified",   "label":"Market Event",      "affects":"shieldgen", "direction": 1, "strength":0.10, "real":True,
     "text":"ShieldGen receives export clearance to supply radar systems to two allied nations — India's defence export push directly boosts order visibility."},
    {"type":"verified",   "label":"Market Event",      "affects":"shieldgen", "direction":-1, "strength":0.09, "real":True,
     "text":"A parliamentary committee review flags ShieldGen's pricing on a recent armoured vehicle contract. Overpricing investigation formally initiated."},
    {"type":"verified",   "label":"Market Event",      "affects":"shieldgen", "direction": 1, "strength":0.11, "real":True,
     "text":"Defence budget hiked 18% in supplementary demands. ShieldGen's order book grows by ₹6,800 crore in a single day of inbound procurement notices."},
    {"type":"verified",   "label":"Market Event",      "affects":"shieldgen", "direction": 1, "strength":0.09, "real":True,
     "text":"'Make in India' defence mandate raises domestic content requirement to 70%. ShieldGen, as a fully domestic manufacturer, gains a structural competitive advantage."},
    {"type":"unverified", "label":"Unverified Rumour", "affects":"shieldgen", "direction":-1, "strength":0.10, "real":False,
     "text":"Rumour: A parliamentary committee is allegedly reviewing ShieldGen's pricing on a recent armoured vehicle contract. Government has not confirmed any probe."},
    {"type":"unverified", "label":"Insider Hint",      "affects":"shieldgen", "direction": 1, "strength":0.12, "real":True,
     "text":"Insider tip: ShieldGen has secured a 7-year maintenance contract for a classified drone programme worth ₹6,000 crore. Announcement expected post budget session."},
    {"type":"unverified", "label":"Unverified Rumour", "affects":"shieldgen", "direction": 1, "strength":0.11, "real":False,
     "text":"Rumour: A further ₹12,000 crore supplementary defence allocation is being discussed in Cabinet. ShieldGen would be the single largest beneficiary."},
    # ── INDRANET (7)
    {"type":"verified",   "label":"Market Event",      "affects":"indranet", "direction": 1, "strength":0.10, "real":True,
     "text":"IndraNet closes 3 large enterprise renewals at 20% higher ARR. Net revenue retention at 118% for the fourth consecutive quarter."},
    {"type":"verified",   "label":"Market Event",      "affects":"indranet", "direction":-1, "strength":0.09, "real":True,
     "text":"SkyLink launches a competing workflow automation product at 30% lower pricing, directly targeting IndraNet's mid-market client base."},
    {"type":"verified",   "label":"Market Event",      "affects":"indranet", "direction": 1, "strength":0.09, "real":True,
     "text":"IndraNet wins a ₹480 crore 5-year contract with a major public sector bank — its largest PSU deal ever. Management raises full-year guidance."},
    {"type":"verified",   "label":"Market Event",      "affects":"indranet", "direction": 1, "strength":0.08, "real":True,
     "text":"Gartner names IndraNet a Leader in its Asia-Pacific Workflow Automation Magic Quadrant for the third consecutive year. International inbounds accelerate."},
    {"type":"unverified", "label":"Unverified Rumour", "affects":"indranet", "direction":-1, "strength":0.10, "real":False,
     "text":"Rumour: A key IndraNet engineering team is reportedly being poached by SkyLink en masse, including the architect of the core automation engine."},
    {"type":"unverified", "label":"Insider Hint",      "affects":"indranet", "direction": 1, "strength":0.11, "real":True,
     "text":"Insider tip: IndraNet just closed 3 large enterprise renewals at 20% higher ARR. Not announced yet — formal guidance upgrade expected next quarter."},
    {"type":"unverified", "label":"Unverified Rumour", "affects":"indranet", "direction": 1, "strength":0.10, "real":False,
     "text":"Rumour: A global enterprise software firm is running diligence on IndraNet as an acquisition target. Premium to current price estimated at 40%."},
    # ── NOVAPAY (IPO, 7)
    {"type":"verified",   "label":"Market Event",      "affects":"novapay", "direction":-1, "strength":0.13, "real":True,
     "text":"BREAKING: RBI sends NovaPay a show-cause notice over KYC compliance gaps in its BNPL product. ₹200 crore fine and product pause possible."},
    {"type":"verified",   "label":"Market Event",      "affects":"novapay", "direction": 1, "strength":0.12, "real":True,
     "text":"NovaPay's monthly transaction volume crosses ₹1 lakh crore for the first time. Market share vs PhonePe narrows to 4 percentage points."},
    {"type":"verified",   "label":"Market Event",      "affects":"novapay", "direction":-1, "strength":0.11, "real":True,
     "text":"BREAKING: UPI interchange fee framework revised downward by RBI. NovaPay's core revenue per transaction drops 18%. Profitability timeline extends."},
    {"type":"verified",   "label":"Market Event",      "affects":"novapay", "direction": 1, "strength":0.10, "real":True,
     "text":"NovaPay BNPL product reaches 8 million users in 5 months — fastest adoption for any credit product in Indian fintech history."},
    {"type":"unverified", "label":"Unverified Rumour", "affects":"novapay", "direction": 1, "strength":0.14, "real":False,
     "text":"Rumour: A Singapore sovereign fund is eyeing a 20% strategic stake in NovaPay at a valuation of 2× current market price. Completely unconfirmed."},
    {"type":"unverified", "label":"Insider Hint",      "affects":"novapay", "direction":-1, "strength":0.12, "real":True,
     "text":"Insider tip: NovaPay's internal audit has flagged irregularities in transaction fee reporting that may require a revenue restatement."},
    {"type":"unverified", "label":"Unverified Rumour", "affects":"novapay", "direction": 1, "strength":0.11, "real":False,
     "text":"Rumour: NovaPay has quietly applied for a small finance bank licence — if granted, this transforms it from a fintech into a fully regulated bank."},
    # ── GREENLEAF (IPO, 7)
    {"type":"verified",   "label":"Market Event",      "affects":"greenleaf", "direction": 1, "strength":0.11, "real":True,
     "text":"GreenLeaf Agri onboards 200,000 new farmers this season. The government farm-to-fork subsidy scheme has been renewed for 3 more years."},
    {"type":"verified",   "label":"Market Event",      "affects":"greenleaf", "direction":-1, "strength":0.12, "real":True,
     "text":"BREAKING: Drought conditions declared across 3 of GreenLeaf's key operating states. Crop yield outlook revised down 28%. Revenue guidance cut."},
    {"type":"verified",   "label":"Market Event",      "affects":"greenleaf", "direction": 1, "strength":0.10, "real":True,
     "text":"GreenLeaf signs supply agreements with 6 major retail chains, securing offtake for 40% of its produce network for the next 2 years."},
    {"type":"verified",   "label":"Market Event",      "affects":"greenleaf", "direction":-1, "strength":0.10, "real":True,
     "text":"A government review of agritech subsidies proposes 30% cuts in allocation. GreenLeaf, which relies on these for 31% of operating costs, faces margin risk."},
    {"type":"unverified", "label":"Insider Hint",      "affects":"greenleaf", "direction": 1, "strength":0.11, "real":True,
     "text":"Insider tip: GreenLeaf's Gulf export deal is reportedly finalised at ₹2,000 crore annually. Transformative if confirmed — not in any public guidance."},
    {"type":"unverified", "label":"Unverified Rumour", "affects":"greenleaf", "direction":-1, "strength":0.09, "real":False,
     "text":"Rumour: A government audit has flagged GreenLeaf's subsidy claims as potentially inflated. A formal investigation may be underway."},
    {"type":"verified",   "label":"Market Event",      "affects":"greenleaf", "direction": 1, "strength":0.09, "real":True,
     "text":"GreenLeaf expands cold storage to 40 new mandis. Post-harvest losses drop 18% — a key metric that directly affects subsidy renewal prospects."},
    # ── ARMORINC (IPO, 7)
    {"type":"verified",   "label":"Market Event",      "affects":"armorinc", "direction": 1, "strength":0.10, "real":True,
     "text":"ArmorInc wins its first central paramilitary contract — 50,000 bulletproof vests for CRPF at ₹840 crore. Recurring annual procurement expected."},
    {"type":"verified",   "label":"Market Event",      "affects":"armorinc", "direction": 1, "strength":0.09, "real":True,
     "text":"ArmorInc's surveillance division signs a ₹420 crore contract with 3 state police forces. High-margin, recurring service revenue begins."},
    {"type":"verified",   "label":"Market Event",      "affects":"armorinc", "direction":-1, "strength":0.09, "real":True,
     "text":"A foreign OEM wins an import tender for personal protective equipment that ArmorInc had expected to secure. 12% revenue shortfall anticipated."},
    {"type":"verified",   "label":"Market Event",      "affects":"armorinc", "direction": 1, "strength":0.10, "real":True,
     "text":"Escalating internal security concerns prompt ₹3,200 crore state government equipment procurement. ArmorInc wins the largest single order in its history."},
    {"type":"unverified", "label":"Insider Hint",      "affects":"armorinc", "direction": 1, "strength":0.12, "real":True,
     "text":"Insider tip: ArmorInc is in advanced acquisition talks for a Pune-based surveillance tech startup. A deal could double its addressable market overnight."},
    {"type":"unverified", "label":"Unverified Rumour", "affects":"armorinc", "direction": 1, "strength":0.10, "real":False,
     "text":"Rumour: ShieldGen is in preliminary talks to acquire ArmorInc at a 35% premium as part of a domestic defence consolidation play."},
    {"type":"verified",   "label":"Market Event",      "affects":"armorinc", "direction": 1, "strength":0.08, "real":True,
     "text":"ArmorInc receives defence export licence. First shipment of ₹120 crore of personal protection equipment to an African nation dispatched."},
    # ── BYTECORP (IPO, 8)
    {"type":"verified",   "label":"Market Event",      "affects":"bytecorp", "direction": 1, "strength":0.15, "real":True,
     "text":"ByteCorp AI's BharatGPT demo goes viral after a prominent US tech analyst calls it 'the most impressive multilingual AI model built outside the US'. Retail frenzy begins."},
    {"type":"verified",   "label":"Market Event",      "affects":"bytecorp", "direction":-1, "strength":0.14, "real":True,
     "text":"BREAKING: ByteCorp's AI enterprise pilot with a major private bank collapses after accuracy failures in Hindi and Tamil. The hype cycle takes a hard hit."},
    {"type":"verified",   "label":"Market Event",      "affects":"bytecorp", "direction": 1, "strength":0.13, "real":True,
     "text":"ByteCorp signs its first revenue-generating enterprise contract — a 2-year deal with a government ministry for AI-powered document processing at ₹180 crore."},
    {"type":"verified",   "label":"Market Event",      "affects":"bytecorp", "direction":-1, "strength":0.13, "real":True,
     "text":"OpenAI launches an Indian-language optimised model that benchmarks above BharatGPT on 7 of 11 regional language tests. ByteCorp's core moat narrative cracks."},
    {"type":"verified",   "label":"Market Event",      "affects":"bytecorp", "direction": 1, "strength":0.12, "real":True,
     "text":"ByteCorp partners with India's largest telecom to embed BharatGPT across 480 million mobile users. Distribution reach far exceeds any competitor."},
    {"type":"verified",   "label":"Market Event",      "affects":"bytecorp", "direction":-1, "strength":0.11, "real":True,
     "text":"ByteCorp reports net cash burn of ₹420 crore for the quarter with no clear timeline to profitability. Institutional investors begin trimming positions."},
    {"type":"unverified", "label":"Unverified Rumour", "affects":"bytecorp", "direction": 1, "strength":0.15, "real":False,
     "text":"Rumour: Microsoft is in serious talks to invest ₹2,000 crore in ByteCorp AI. The CEO responded 'no comment'. Market has fully priced in the best case."},
    {"type":"unverified", "label":"Insider Hint",      "affects":"bytecorp", "direction": 1, "strength":0.14, "real":True,
     "text":"Insider tip: ByteCorp is weeks away from announcing a government AI contract worth ₹800 crore — the company's first large public-sector revenue deal."},
    # ── SECTOR-WIDE (20)
    {"type":"verified", "label":"Market Event", "affects":"sector:Technology",       "direction": 1, "strength":0.08, "real":True,
     "text":"SECTOR: Government launches a ₹10,000 crore Digital India 3.0 push. Cloud, SaaS, and AI companies are the primary intended beneficiaries."},
    {"type":"verified", "label":"Market Event", "affects":"sector:Technology",       "direction":-1, "strength":0.08, "real":True,
     "text":"SECTOR: A sweeping data localisation bill clears Rajya Sabha. Compliance costs for tech companies estimated at ₹4,000–8,000 crore industry-wide."},
    {"type":"verified", "label":"Market Event", "affects":"sector:Technology",       "direction": 1, "strength":0.07, "real":True,
     "text":"SECTOR: India climbs to #3 globally in tech startup funding. Analyst upgrades across the sector as global capital inflows accelerate."},
    {"type":"verified", "label":"Market Event", "affects":"sector:Technology",       "direction":-1, "strength":0.07, "real":True,
     "text":"SECTOR: Global tech selloff after US Fed signals higher-for-longer rates. Indian tech stocks, with high P/E multiples, bear the sharpest correction."},
    {"type":"verified", "label":"Market Event", "affects":"sector:FMCG",             "direction": 1, "strength":0.07, "real":True,
     "text":"SECTOR: Rural consumption surges 11% YoY as crop prices rise and rural wages hit a 5-year high. FMCG companies are broadly re-rated upward."},
    {"type":"verified", "label":"Market Event", "affects":"sector:FMCG",             "direction":-1, "strength":0.07, "real":True,
     "text":"SECTOR: Palm oil and edible oil prices spike 22% globally. Input cost pressure hits all FMCG manufacturers simultaneously."},
    {"type":"verified", "label":"Market Event", "affects":"sector:Defence",          "direction": 1, "strength":0.09, "real":True,
     "text":"SECTOR: Defence budget hiked 18% in supplementary demands. Domestic manufacturers across the sector receive order upgrades."},
    {"type":"verified", "label":"Market Event", "affects":"sector:Defence",          "direction": 1, "strength":0.08, "real":True,
     "text":"SECTOR: 'Make in India' defence mandate requires 70% domestic content. Foreign OEMs must partner with Indian firms — domestic players gain structural edge."},
    {"type":"verified", "label":"Market Event", "affects":"sector:Pharma",           "direction":-1, "strength":0.07, "real":True,
     "text":"SECTOR: US FDA issues import alerts on 4 Indian pharmaceutical plants. Export revenue for multiple companies at immediate risk."},
    {"type":"verified", "label":"Market Event", "affects":"sector:Pharma",           "direction": 1, "strength":0.07, "real":True,
     "text":"SECTOR: WHO qualifies 3 more Indian generic manufacturers for global supply. Export opportunity worth ₹12,000 crore opens up across the sector."},
    {"type":"verified", "label":"Market Event", "affects":"sector:Logistics",        "direction":-1, "strength":0.07, "real":True,
     "text":"SECTOR: New national highway toll policy hikes rates by 15%. All logistics and trucking companies face immediate cost increases."},
    {"type":"verified", "label":"Market Event", "affects":"sector:Logistics",        "direction": 1, "strength":0.07, "real":True,
     "text":"SECTOR: GST Council announces simplified e-way bill process, reducing logistics compliance costs. Entire sector benefits from the efficiency gain."},
    {"type":"verified", "label":"Market Event", "affects":"sector:Renewable Energy", "direction": 1, "strength":0.08, "real":True,
     "text":"SECTOR: India achieves a new solar installation record. Government doubles renewable energy subsidies for the next 3 fiscal years."},
    {"type":"verified", "label":"Market Event", "affects":"sector:Renewable Energy", "direction":-1, "strength":0.07, "real":True,
     "text":"SECTOR: Solar panel import tariffs hiked 12%. Domestic project costs rise for all renewable energy companies."},
    {"type":"verified", "label":"Market Event", "affects":"sector:Fintech",          "direction": 1, "strength":0.08, "real":True,
     "text":"SECTOR: UPI transaction volume crosses 20 billion monthly. RBI announces new incentive framework for digital payment platforms."},
    {"type":"verified", "label":"Market Event", "affects":"sector:Fintech",          "direction":-1, "strength":0.08, "real":True,
     "text":"SECTOR: RBI tightens digital lending norms. Fintech companies face new capital adequacy requirements that squeeze short-term profitability."},
    {"type":"verified", "label":"Market Event", "affects":"sector:Agriculture",      "direction": 1, "strength":0.07, "real":True,
     "text":"SECTOR: Government announces largest-ever agritech investment package at ₹8,500 crore. Agritech startups and listed companies both benefit."},
    {"type":"verified", "label":"Market Event", "affects":"sector:Agriculture",      "direction":-1, "strength":0.07, "real":True,
     "text":"SECTOR: A poor monsoon forecast triggers broad-based selling in agri-dependent businesses. Crop yield estimates revised down 15%."},
    {"type":"verified", "label":"Market Event", "affects":"sector:Media / OTT",      "direction": 1, "strength":0.07, "real":True,
     "text":"SECTOR: Internet penetration reaches 900 million users in India. OTT platforms are the biggest beneficiaries of the next digital adoption wave."},
    {"type":"verified", "label":"Market Event", "affects":"sector:Manufacturing",    "direction": 1, "strength":0.07, "real":True,
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
    async with aiosqlite.connect(DB_PATH) as db:
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
                cash     REAL    DEFAULT 50000,
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
        "phase":              "lobby",
        "round":              0,
        "round_end_time":     None,
        "break_end_time":     None,
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
    async with aiosqlite.connect(DB_PATH) as db:
        rows = await (await db.execute("SELECT code FROM codes")).fetchall()
    return {r[0] for r in rows}


async def all_players():
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        rows = await (await db.execute("SELECT * FROM players")).fetchall()
    return [_row_to_player(r) for r in rows]


async def get_player(code: str) -> Optional[dict]:
    async with aiosqlite.connect(DB_PATH) as db:
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
    async with aiosqlite.connect(DB_PATH) as db:
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
    port_value  = sum(h["value"] for h in portfolio.values())
    total_loans = player_loans_total(p)
    net_worth   = p["cash"] + port_value - total_loans
    return {
        "cash":       round(p["cash"]),
        "loans":      p.get("loans", {}),
        "total_loan": round(total_loans),
        "frozen":     p["frozen"],
        "net_worth":  round(net_worth),
        "portfolio":  portfolio,
        "bets":       p.get("bets", {}),
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
        c["price"] = max(floor, round(c["price"] * (1 + change)))
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


# ═══════════════════════════════════════════════════════════════
#  PASSIVE DRIFT LOOP
# ═══════════════════════════════════════════════════════════════
async def price_drift_loop():
    await asyncio.sleep(30)
    while True:
        await asyncio.sleep(DRIFT_INTERVAL)
        state = await read_state()
        if state.get("phase") != "trading":
            continue
        freeze    = state.get("regulatory_freeze")
        companies = state["companies"]
        for cid, c in companies.items():
            if freeze and c.get("sector") == freeze:
                continue
            lo, hi, bias = COMPANY_VOL.get(cid, (0.005, 0.03, 0.46))
            # Drift is a fraction of normal volatility — micro-movements
            mag   = random.uniform(0.001, min(0.020, hi * 0.30))
            direc = 1 if random.random() > bias else -1
            floor = PRICE_FLOORS.get(cid, 10)
            c["price"] = max(floor, round(c["price"] * (1 + direc * mag)))
        await write_state(state)
        players = await all_players()
        board   = leaderboard(players, state)
        await manager.broadcast_all({
            "type":   "prices_bulk",
            "prices": {k: v["price"] for k, v in companies.items()},
            "board":  board,
        })


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
    chosen = random.sample(pool, min(count, len(pool)))
    state["news_used"] = list(used) + [n["text"] for n in chosen]
    return chosen


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
    asyncio.create_task(price_drift_loop())
    yield


app = FastAPI(lifespan=lifespan)
BASE_DIR = Path(__file__).parent


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


# ═══════════════════════════════════════════════════════════════
#  REST: CODE MANAGEMENT
# ═══════════════════════════════════════════════════════════════
@app.post("/api/codes/generate")
async def generate_codes(count: int = 10):
    # Generate slightly more than needed to account for rare collisions
    candidates = [uuid.uuid4().hex[:6].upper() for _ in range(max(count, 20))]
    async with aiosqlite.connect(DB_PATH) as db:
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
    async with aiosqlite.connect(DB_PATH) as db:
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
    async with aiosqlite.connect(DB_PATH) as db:
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
    async with aiosqlite.connect(DB_PATH) as db:
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
    # Unfreeze all players
    players = await all_players()
    for p in players:
        if p["frozen"]:
            p["frozen"] = False
            await save_player(p)
    # Pick and apply news
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
    state = await read_state()
    if state["phase"] != "trading":
        raise HTTPException(400, "Not in trading phase")
    state["phase"]          = "break"
    state["round_end_time"] = None
    state["break_end_time"] = time.time() + BREAK_DURATION
    state["regulatory_freeze"] = None
    state["acquisition_pair"]  = None
    state["merge_bids"]        = {}
    # Apply per-bank compounding interest
    players = await all_players()
    for p in players:
        loans   = p.get("loans", {})
        changed = False
        for bank_id, bal in list(loans.items()):
            if bal > 0 and bank_id in BANKS:
                rate = BANKS[bank_id]["rate"]
                if state.get("credit_crunch"):
                    rate += 0.05
                loans[bank_id] = round(bal * (1 + rate))
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
    # Resolve prediction bets
    players = await all_players()
    await resolve_predictions(state, players)
    await write_state(state)
    players = await all_players()
    board   = leaderboard(players, state)
    await manager.broadcast_all({
        "type":  "phase_change",
        "phase": "break",
        "round": state["round"],
        "board": board,
    })
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
    state       = await read_state()
    is_verified = data.get("verified", True)
    is_real     = is_verified  # verified always moves; unverified may or may not
    strength    = float(data.get("strength", 0.10))
    n = {
        "type":      "verified" if is_verified else "unverified",
        "label":     "Market Event" if is_verified else "Unverified Rumour",
        "text":      data["text"],
        "affects":   data["affects"],
        "direction": data.get("direction", 1),
        "strength":  strength,
        "real":      is_real,
    }
    state["news"].append(n)
    c = state["companies"].get(data["affects"])
    if c and state["phase"] == "trading":
        c["prev_price"] = c["price"]
        if is_verified:
            move = strength
        else:
            move = strength if random.random() < 0.4 else random.uniform(0.005, 0.02)
        floor         = PRICE_FLOORS.get(data["affects"], 10)
        c["price"]    = max(floor, round(c["price"] * (1 + n["direction"] * move)))
    await write_state(state)
    await manager.broadcast_all({"type": "news", **n})
    players = await all_players()
    board   = leaderboard(players, state)
    await manager.broadcast_all({
        "type":   "prices_bulk",
        "prices": {k: v["price"] for k, v in state["companies"].items()},
        "board":  board,
    })
    return {"ok": True}


@app.post("/api/host/manual_price")
async def manual_price(data: dict, pw: str):
    if pw != HOST_PASSWORD:
        raise HTTPException(403, "Wrong password")
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
    code = data["code"]
    n = {
        "type":    "unverified",
        "label":   "Secret Intel",
        "text":    data["text"],
        "private": True,
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
    state = await read_state()
    cid1  = data["stock1"]
    cid2  = data["stock2"]
    if cid1 not in state["companies"] or cid2 not in state["companies"]:
        raise HTTPException(400, "Unknown stocks")
    state["acquisition_pair"] = [cid1, cid2]
    await write_state(state)
    n1  = state["companies"][cid1]["name"]
    n2  = state["companies"][cid2]["name"]
    msg = f"🤝 ACQUISITION RUMOUR — {n1} and {n2} reportedly in merger talks! Their prices will move in tandem. (Unverified)"
    await manager.broadcast_all({"type": "chaos", "event": "acquisition_rumour", "msg": msg})
    await manager.broadcast_all({
        "type": "news", "label": "Unverified Rumour", "type_tag": "unverified",
        "affects": cid1, "direction": 1, "real": False,
        "text": msg,
    })
    return {"ok": True}


@app.post("/api/chaos/credit_crunch")
async def chaos_credit_crunch(pw: str):
    """Raise all bank rates by +5% for this round's interest calculation."""
    if pw != HOST_PASSWORD:
        raise HTTPException(403, "Wrong password")
    state = await read_state()
    state["credit_crunch"] = True
    await write_state(state)
    msg = (
        "💸 CREDIT CRUNCH — All bank interest rates +5% this round! "
        "Bharat→10%, VentureCapX→14%, ShadowCredit→21%. Heavy borrowers beware."
    )
    await manager.broadcast_all({"type": "chaos", "event": "credit_crunch", "msg": msg})
    return {"ok": True}


@app.post("/api/chaos/ipo_drop/{ipo_id}")
async def chaos_ipo_drop(ipo_id: str, pw: str):
    """List an IPO company mid-game."""
    if pw != HOST_PASSWORD:
        raise HTTPException(403, "Wrong password")
    if ipo_id not in IPO_COMPANIES:
        raise HTTPException(400, f"Unknown IPO: {ipo_id}")
    state = await read_state()
    if ipo_id in state.get("ipo_listed", []):
        raise HTTPException(400, f"{ipo_id} is already listed")
    ipo = IPO_COMPANIES[ipo_id]
    state["companies"][ipo_id]   = {**ipo, "prev_price": ipo["price"]}
    state["ipo_listed"]          = state.get("ipo_listed", []) + [ipo_id]
    PRICE_FLOORS[ipo_id]         = round(ipo["price"] * 0.20)  # set floor dynamically
    state.setdefault("price_history", {})[ipo_id] = [ipo["price"]]
    await write_state(state)
    msg = f"🚀 IPO DROP — {ipo['name']} lists on the exchange! {ipo['trait']} IPO price: ₹{ipo['price']:,}"
    await manager.broadcast_all({
        "type":    "chaos",
        "event":   "ipo_drop",
        "msg":     msg,
        "company": {"id": ipo_id, **ipo},
    })
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
    code    = data.get("code", "").upper()
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
            direction = int(data.get("direction", 1))
            text      = data.get("text", "").strip()[:200]
            if not stock or stock not in state["companies"]:
                raise HTTPException(400, "Pick a valid stock.")
            if not text:
                raise HTTPException(400, "Rumour text is required.")
            log_entry.update({"stock": stock, "direction": direction, "text": text})
            is_leak  = item_id == "leak_card"
            strength = random.uniform(0.10, 0.18) if is_leak else random.uniform(0.06, 0.12)
            is_real  = True if is_leak else (random.random() < 0.5)
            n = {
                "type":      "unverified",
                "label":     "Unverified Rumour",
                "affects":   stock,
                "direction": direction,
                "strength":  strength,
                "real":      is_real,
                "text":      text,
            }
            state["news"].append(n)
            c = state["companies"].get(stock)
            if c and is_real and state["phase"] == "trading":
                c["prev_price"] = c["price"]
                floor           = PRICE_FLOORS.get(stock, 10)
                c["price"]      = max(floor, round(c["price"] * (1 + direction * strength)))
            await write_state(state)
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
        "market":        state["companies"],
        "board":         leaderboard(await all_players(), state),
        "banks":         BANKS,
        "joined":        already_joined,
        "reg_freeze":    state.get("regulatory_freeze"),
        "credit_crunch": state.get("credit_crunch", False),
        "price_history": state.get("price_history", {}),
        "news":          state.get("news", []),
        **({"name": player["name"], "player": player_view(player, state)} if already_joined else {}),
    }))

    try:
        async for raw in websocket.iter_text():
            msg    = json.loads(raw)
            action = msg.get("action")
            # Always re-read state and player for freshness
            state  = await read_state()
            player = await get_player(code)

            # ── Set name ──────────────────────────────────────────────
            if action == "set_name":
                name = msg.get("name", "").strip()[:30]
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
                    "type":   "joined",
                    "name":   name,
                    "player": pv,
                    "banks":  BANKS,
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
                qty   = int(msg.get("qty", 0))
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
                qty   = int(msg.get("qty", 0))
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
                    player["cash"]             += price * qty
                    player["holdings"][stock]   = owned - qty
                    await save_player(player)
                pv = player_view(player, state)
                await websocket.send_text(json.dumps({
                    "type":   "trade_ok",
                    "msg":    f"Sold {qty}× {state['companies'][stock]['name']} @ ₹{price:,}",
                    "player": pv,
                }))
                board = leaderboard(await all_players(), state)
                await manager.broadcast_all({"type": "leaderboard", "board": board})

            # ── Take loan ─────────────────────────────────────────────
            elif action == "take_loan":
                if not player:
                    await websocket.send_text(json.dumps({"type": "error", "msg": "Join first."})); continue
                bank_id = msg.get("bank_id")
                amount  = int(msg.get("amount", 0))
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
                pv   = player_view(player, state)
                rate = bank["rate"] + (0.05 if state.get("credit_crunch") else 0)
                await websocket.send_text(json.dumps({
                    "type":   "trade_ok",
                    "msg":    f"₹{amount:,} from {bank['name']}. Balance: ₹{int(player['loans'][bank_id]):,}. Rate: {rate*100:.0f}%/round.",
                    "player": pv,
                }))

            # ── Repay loan ────────────────────────────────────────────
            elif action == "repay_loan":
                if not player:
                    await websocket.send_text(json.dumps({"type": "error", "msg": "Join first."})); continue
                if state["phase"] != "break":
                    await websocket.send_text(json.dumps({"type": "error", "msg": "Loans can only be repaid during the break."})); continue
                bank_id   = msg.get("bank_id")
                repay_amt = int(msg.get("amount", 0))
                if bank_id not in BANKS:
                    await websocket.send_text(json.dumps({"type": "error", "msg": "Invalid bank."})); continue
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
                async with _player_locks[code]:
                    player = await get_player(code)
                    player["cash"]     = BANKRUPTCY_RESTART
                    player["holdings"] = {}
                    player["loans"]    = {}
                    player["bets"]     = {}   # bets cleared; stakes already deducted — treat as lost
                    player["avg_cost"] = {}
                    player["frozen"]   = False
                    await save_player(player)
                pv = player_view(player, state)
                await websocket.send_text(json.dumps({
                    "type":   "bankrupt",
                    "msg":    f"💀 Bankruptcy declared. Wiped clean. Restarting with ₹{BANKRUPTCY_RESTART:,}.",
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
                target    = float(msg.get("target", 0))
                amount    = int(msg.get("amount", 0))
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
                partner_code = msg.get("partner_code", "").upper()
                stock        = msg.get("stock")
                qty          = int(msg.get("qty", 0))
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
                state["merge_bids"][bid_id] = {
                    "from_code":    code,
                    "from_name":    player["name"],
                    "partner_code": partner_code,
                    "stock":        stock,
                    "qty":          qty,
                    "each":         each,
                    "ts":           time.time(),
                }
                await write_state(state)
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
                    del state["merge_bids"][bid_id]
                    await write_state(state)
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

                del state["merge_bids"][bid_id]
                await write_state(state)
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

    except WebSocketDisconnect:
        pass
    finally:
        manager.disconnect_player(code)
        # Notify host that this player went offline
        await manager.broadcast_hosts({"type": "player_offline", "code": code})


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
            msg = json.loads(raw)
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