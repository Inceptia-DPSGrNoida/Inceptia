"""
Market Mayhem — main.py  (Stage 2)
FastAPI + WebSockets + SQLite
Run: uvicorn main:app --reload --port 8000
Team view:  http://localhost:8000
Host panel: http://localhost:8000/host
Black mkt:  http://localhost:8000/bm  (skeleton, items in Stage 3)
"""

import asyncio, json, os, random, time, uuid
from pathlib import Path
from contextlib import asynccontextmanager
from typing import Dict, Optional

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException
from fastapi.responses import HTMLResponse
import aiosqlite

# ── Config ─────────────────────────────────────────────────────────────────────
DB_PATH            = Path(os.getenv("DB_PATH", "game.db"))
HOST_PASSWORD      = os.getenv("HOST_PASSWORD", "InceptiaHost2025")
STARTING_CASH      = 50_000
ROUND_DURATION     = 1200      # seconds (20 min) — host can end early
BANKRUPTCY_RESTART = 25_000
DRIFT_INTERVAL     = 120       # seconds between passive price drifts

# ── 3-Bank config ──────────────────────────────────────────────────────────────
BANKS = {
    "bharat": {
        "name":    "Bharat Bank",
        "limit":   90_000,
        "options": [20_000, 40_000, 60_000, 90_000],
        "rate":    0.05,   # 5% per round
    },
    "vcx": {
        "name":    "VentureCapX",
        "limit":   1_50_000,
        "options": [50_000, 75_000, 1_00_000, 1_50_000],
        "rate":    0.09,
    },
    "shadow": {
        "name":    "ShadowCredit",
        "limit":   3_00_000,
        "options": [1_00_000, 1_50_000, 2_00_000, 3_00_000],
        "rate":    0.16,
    },
}

# ── Sector groupings for ripple effects ────────────────────────────────────────
SECTORS = {
    "Technology":     ["skylink", "indranet", "bytecorp"],
    "FMCG":           ["freshco", "crownmart"],
    "Defence":        ["shieldgen", "armorinc"],
    "Renewable Energy": ["voltex"],
    "Pharma":         ["mediq"],
    "Logistics":      ["swifthaul"],
    "Manufacturing":  ["zora"],
    "Media / OTT":    ["streamvx"],
    "Fintech":        ["novapay"],
    "Agriculture":    ["greenleaf"],
}

# ── Companies ──────────────────────────────────────────────────────────────────
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
            "ShieldGen doesn't surprise you — it just quietly compounds. Analysts call it "
            "the most boring stock with the most reliable upward drift."
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
            "and the market must decide: PhonePe successor, or overvalued promise? "
            "Volume is real. Profitability is a question mark."
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
            "renew, GreenLeaf scales fast. If they're cut, margins collapse. "
            "The impact story is real. The financial risk is also real."
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
            "units. Revenue is ₹3,200 crore with 19% net margins — lean, efficient, and "
            "contract-backed. The company recently won its first central paramilitary "
            "contract worth ₹840 crore. Management is disciplined, promoter stake is 71%, "
            "and expansion into exports is the next chapter. Under the radar — for now."
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
            "can easily replicate. That thesis may be correct. But right now it's all "
            "potential and no profit. ByteCorp is pure speculative momentum. "
            "Either this is the ground floor of something enormous, or it's nothing."
        ),
        "trait": "The future. Or a ₹0 stock. No in-between.",
    },
}

# Volatility: (min_drift, max_drift, down_bias)
COMPANY_VOL = {
    "zora":      (0.004, 0.016, 0.48),
    "streamvx":  (0.025, 0.075, 0.45),
    "freshco":   (0.003, 0.014, 0.49),
    "voltex":    (0.018, 0.055, 0.44),
    "mediq":     (0.018, 0.065, 0.46),
    "skylink":   (0.030, 0.085, 0.44),
    "swifthaul": (0.010, 0.038, 0.46),
    "crownmart": (0.022, 0.070, 0.45),
    "shieldgen": (0.004, 0.018, 0.49),
    "indranet":  (0.008, 0.030, 0.47),
    "novapay":   (0.038, 0.095, 0.43),
    "greenleaf": (0.015, 0.055, 0.46),
    "armorinc":  (0.006, 0.025, 0.48),
    "bytecorp":  (0.055, 0.140, 0.44),
}

# ── News pool ──────────────────────────────────────────────────────────────────
# type: "verified" | "unverified"
# real: True = always moves price, False = 40% chance for unverified
NEWS_POOL = [
    # ════════════════════════════════════════════════════════════════
    # ZORA INDUSTRIES  (8 items)
    # ════════════════════════════════════════════════════════════════
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

    # ════════════════════════════════════════════════════════════════
    # STREAMVERSE  (9 items)
    # ════════════════════════════════════════════════════════════════
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

    # ════════════════════════════════════════════════════════════════
    # FRESHCO  (8 items)
    # ════════════════════════════════════════════════════════════════
    {"type":"verified",   "label":"Market Event",      "affects":"freshco", "direction": 1, "strength":0.08, "real":True,
     "text":"Rural FMCG consumption hits a 6-year high. FreshCo's 6 million kirana distribution network gives it unmatched last-mile reach in the surge."},
    {"type":"verified",   "label":"Market Event",      "affects":"freshco", "direction":-1, "strength":0.10, "real":True,
     "text":"BREAKING: A cyclone warning is issued for the eastern coast. FreshCo's largest manufacturing cluster in Odisha has suspended operations."},
    {"type":"verified",   "label":"Market Event",      "affects":"freshco", "direction": 1, "strength":0.09, "real":True,
     "text":"FreshCo's new premium biscuit line sells out in 48 hours across modern trade. Early data suggests 22% margin improvement over base SKUs."},
    {"type":"verified",   "label":"Market Event",      "affects":"freshco", "direction":-1, "strength":0.08, "real":True,
     "text":"Palm oil and wheat prices spike 18% globally. FreshCo's input costs set to rise sharply, threatening Q3 margin guidance."},
    {"type":"verified",   "label":"Market Event",      "affects":"freshco", "direction": 1, "strength":0.07, "real":True,
     "text":"FreshCo launches direct-to-consumer app in 12 cities. Analyst notes this could add ₹800 crore in high-margin revenue within 18 months."},
    {"type":"unverified", "label":"Unverified Rumour", "affects":"freshco", "direction":-1, "strength":0.09, "real":False,
     "text":"Rumour: A viral social media post claims FreshCo biscuits contain banned additives. The company says the post is completely fabricated."},
    {"type":"unverified", "label":"Insider Hint",      "affects":"freshco", "direction": 1, "strength":0.12, "real":True,
     "text":"Insider tip: FreshCo is preparing to launch a premium skincare line targeting urban millennials. Could add ₹1,200 crore in new revenues."},
    {"type":"unverified", "label":"Unverified Rumour", "affects":"freshco", "direction":-1, "strength":0.09, "real":False,
     "text":"Rumour: FreshCo's distribution deal with a major modern trade chain is up for renegotiation and may not be renewed at existing terms."},

    # ════════════════════════════════════════════════════════════════
    # VOLTEX ENERGY  (9 items)
    # ════════════════════════════════════════════════════════════════
    {"type":"verified",   "label":"Market Event",      "affects":"voltex", "direction": 1, "strength":0.13, "real":True,
     "text":"BREAKING: Government announces a ₹4,200 crore renewable energy subsidy package. Voltex is named as primary beneficiary in the policy gazette."},
    {"type":"verified",   "label":"Market Event",      "affects":"voltex", "direction":-1, "strength":0.12, "real":True,
     "text":"BREAKING: Two Voltex solar parks in Rajasthan fail safety inspections. Ministry of New Energy has suspended project clearances pending review."},
    {"type":"verified",   "label":"Market Event",      "affects":"voltex", "direction": 1, "strength":0.11, "real":True,
     "text":"Voltex signs its largest single contract — a 900MW solar park for the Tamil Nadu State Electricity Board. Price target revised up 35%."},
    {"type":"verified",   "label":"Market Event",      "affects":"voltex", "direction": 1, "strength":0.09, "real":True,
     "text":"India raises its 2030 solar target to 500GW. Voltex, with the largest installed base, is the most direct beneficiary of the revised policy."},
    {"type":"verified",   "label":"Market Event",      "affects":"voltex", "direction":-1, "strength":0.10, "real":True,
     "text":"Voltex refinances ₹6,200 crore of debt at higher-than-expected rates due to rising bond yields. Interest burden increases materially."},
    {"type":"verified",   "label":"Market Event",      "affects":"voltex", "direction": 1, "strength":0.08, "real":True,
     "text":"Voltex wins 600MW wind energy bid in Gujarat at a competitive tariff. Analysts upgrade from Hold to Buy citing improved project pipeline."},
    {"type":"unverified", "label":"Unverified Rumour", "affects":"voltex", "direction": 1, "strength":0.11, "real":False,
     "text":"Rumour: Voltex is allegedly in merger talks with a UAE sovereign wealth fund. Could value the company at 3× current market cap. Unconfirmed."},
    {"type":"unverified", "label":"Insider Hint",      "affects":"voltex", "direction":-1, "strength":0.10, "real":True,
     "text":"Insider tip: Voltex's key government subsidy renewal is reportedly stalled in parliamentary committee. A 6-month delay looks likely."},
    {"type":"unverified", "label":"Unverified Rumour", "affects":"voltex", "direction":-1, "strength":0.09, "real":False,
     "text":"Rumour: Land acquisition disputes are delaying three major Voltex solar projects, with local protests intensifying in Andhra Pradesh."},

    # ════════════════════════════════════════════════════════════════
    # MEDIQ  (8 items)
    # ════════════════════════════════════════════════════════════════
    {"type":"verified",   "label":"Market Event",      "affects":"mediq", "direction":-1, "strength":0.14, "real":True,
     "text":"BREAKING: DCGI rejects MediQ's Zytravax drug application. Additional Phase 3 trials required — approval timeline pushed back 18 months."},
    {"type":"verified",   "label":"Market Event",      "affects":"mediq", "direction": 1, "strength":0.15, "real":True,
     "text":"BREAKING: DCGI grants fast-track approval to MediQ's Zytravax. The stock is halted for 30 minutes as buy orders flood the exchange."},
    {"type":"verified",   "label":"Market Event",      "affects":"mediq", "direction": 1, "strength":0.09, "real":True,
     "text":"MediQ files 4 new patents for next-generation oncology compounds — a pipeline the market has not yet priced in."},
    {"type":"verified",   "label":"Market Event",      "affects":"mediq", "direction":-1, "strength":0.10, "real":True,
     "text":"A competing pharma company announces a rival oncology drug trial with early data showing superior efficacy to MediQ's Zytravax."},
    {"type":"verified",   "label":"Market Event",      "affects":"mediq", "direction": 1, "strength":0.08, "real":True,
     "text":"MediQ's existing generic API division reports 22% revenue growth, providing a stable floor while the market awaits Zytravax news."},
    {"type":"unverified", "label":"Insider Hint",      "affects":"mediq", "direction": 1, "strength":0.14, "real":True,
     "text":"Insider tip: MediQ's Phase 3 Zytravax results are being submitted to DCGI this week. Internal sources describe the data as 'exceptionally strong'."},
    {"type":"unverified", "label":"Unverified Rumour", "affects":"mediq", "direction": 1, "strength":0.13, "real":False,
     "text":"Rumour: A major global pharma company is in acquisition talks for MediQ at a 60% premium to market price. Neither side has commented."},
    {"type":"unverified", "label":"Unverified Rumour", "affects":"mediq", "direction":-1, "strength":0.11, "real":False,
     "text":"Rumour: Anonymous leak claims MediQ's Zytravax trial data was selectively reported. Company calls it 'defamatory and false'."},

    # ════════════════════════════════════════════════════════════════
    # SKYLINK TECH  (9 items)
    # ════════════════════════════════════════════════════════════════
    {"type":"verified",   "label":"Market Event",      "affects":"skylink", "direction": 1, "strength":0.11, "real":True,
     "text":"SkyLink posts 34% YoY revenue growth in Q2, beating analyst consensus by ₹420 crore. Full-year guidance raised by 12%."},
    {"type":"verified",   "label":"Market Event",      "affects":"skylink", "direction":-1, "strength":0.13, "real":True,
     "text":"BREAKING: A massive data breach at SkyLink exposes 11 million user records. Government issues a show-cause notice; three regulators open investigations."},
    {"type":"verified",   "label":"Market Event",      "affects":"skylink", "direction": 1, "strength":0.12, "real":True,
     "text":"SkyLink announces a $400M AI partnership with a top US tech firm — the largest cross-border deal in Indian enterprise software history."},
    {"type":"verified",   "label":"Market Event",      "affects":"skylink", "direction":-1, "strength":0.11, "real":True,
     "text":"SkyLink's Southeast Asia expansion stalls as two major enterprise clients in Singapore terminate contracts citing product reliability issues."},
    {"type":"verified",   "label":"Market Event",      "affects":"skylink", "direction": 1, "strength":0.10, "real":True,
     "text":"SkyLink wins a ₹3,200 crore cloud infrastructure contract with three central government ministries — largest PSU deal in company history."},
    {"type":"verified",   "label":"Market Event",      "affects":"skylink", "direction":-1, "strength":0.12, "real":True,
     "text":"BREAKING: Founder Aryan Mehta sells ₹900 crore of SkyLink shares at market. No explanation given. Retail sentiment turns sharply negative."},
    {"type":"unverified", "label":"Unverified Rumour", "affects":"skylink", "direction":-1, "strength":0.10, "real":False,
     "text":"Rumour: Three of SkyLink's senior engineering leads have resigned citing 'toxic leadership' and founder interference. Company calls it standard attrition."},
    {"type":"unverified", "label":"Insider Hint",      "affects":"skylink", "direction": 1, "strength":0.14, "real":True,
     "text":"Insider tip: SkyLink is finalising a major product launch for next week that will directly target IndraNet's core B2B SaaS market."},
    {"type":"unverified", "label":"Unverified Rumour", "affects":"skylink", "direction": 1, "strength":0.11, "real":False,
     "text":"Rumour: A Nasdaq-listed tech company is reportedly building a strategic stake in SkyLink as part of an India market entry strategy."},

    # ════════════════════════════════════════════════════════════════
    # SWIFTHAUL LOGISTICS  (8 items)
    # ════════════════════════════════════════════════════════════════
    {"type":"verified",   "label":"Market Event",      "affects":"swifthaul", "direction": 1, "strength":0.10, "real":True,
     "text":"SwiftHaul reports a 28% surge in same-day delivery volume and signs an exclusive 3-year logistics contract with India's largest e-commerce platform."},
    {"type":"verified",   "label":"Market Event",      "affects":"swifthaul", "direction":-1, "strength":0.11, "real":True,
     "text":"BREAKING: Global crude oil surges 18%. SwiftHaul's 18,000-vehicle fleet faces severe margin compression. Management withdraws guidance."},
    {"type":"verified",   "label":"Market Event",      "affects":"swifthaul", "direction": 1, "strength":0.09, "real":True,
     "text":"SwiftHaul launches cold-chain pharma logistics division. First 3 contracts signed with top hospital chains. Analysts call it a margin game-changer."},
    {"type":"verified",   "label":"Market Event",      "affects":"swifthaul", "direction":-1, "strength":0.09, "real":True,
     "text":"A new government-backed logistics startup receives ₹800 crore in funding and targets SwiftHaul's core e-commerce delivery business."},
    {"type":"verified",   "label":"Market Event",      "affects":"swifthaul", "direction": 1, "strength":0.08, "real":True,
     "text":"SwiftHaul signs cross-border delivery agreement covering Nepal, Bangladesh, and Sri Lanka — first international revenue in company history."},
    {"type":"unverified", "label":"Unverified Rumour", "affects":"swifthaul", "direction":-1, "strength":0.09, "real":False,
     "text":"Rumour: SwiftHaul has been under-reporting delivery failure rates to retain contracts. A regulatory audit has allegedly been quietly initiated."},
    {"type":"unverified", "label":"Insider Hint",      "affects":"swifthaul", "direction": 1, "strength":0.12, "real":True,
     "text":"Insider tip: SwiftHaul is finalising a ₹600 crore pharma cold-chain JV with a state government. Margins could improve 3–4 percentage points."},
    {"type":"unverified", "label":"Unverified Rumour", "affects":"swifthaul", "direction": 1, "strength":0.10, "real":False,
     "text":"Rumour: Amazon India is in talks to acquire a 26% strategic stake in SwiftHaul to secure supply chain independence in India."},

    # ════════════════════════════════════════════════════════════════
    # CROWNMART  (8 items)
    # ════════════════════════════════════════════════════════════════
    {"type":"verified",   "label":"Market Event",      "affects":"crownmart", "direction":-1, "strength":0.12, "real":True,
     "text":"BREAKING: Blinkit announces 10-minute grocery delivery expansion to 50 new cities, directly targeting CrownMart's core customer base."},
    {"type":"verified",   "label":"Market Event",      "affects":"crownmart", "direction": 1, "strength":0.10, "real":True,
     "text":"CrownMart's new CEO unveils Phase 2 restructuring: 120 loss-making stores shuttered, private label target raised to 40% of revenue. Market approves."},
    {"type":"verified",   "label":"Market Event",      "affects":"crownmart", "direction": 1, "strength":0.09, "real":True,
     "text":"CrownMart's private label personal care line outsells national brands in 340 stores — first time in company history. Analysts raise target price."},
    {"type":"verified",   "label":"Market Event",      "affects":"crownmart", "direction":-1, "strength":0.10, "real":True,
     "text":"Zepto and Swiggy Instamart report combined grocery GMV surpassing CrownMart's total revenue for the first time. Sentiment hits a 2-year low."},
    {"type":"verified",   "label":"Market Event",      "affects":"crownmart", "direction": 1, "strength":0.08, "real":True,
     "text":"CrownMart announces profitable Q3 — first positive EBITDA quarter in six. CEO calls it a 'turning point'. Market watches cautiously."},
    {"type":"unverified", "label":"Unverified Rumour", "affects":"crownmart", "direction": 1, "strength":0.11, "real":False,
     "text":"Rumour: A private equity firm is quietly accumulating CrownMart shares ahead of an alleged management-led buyout at a 30% premium."},
    {"type":"unverified", "label":"Insider Hint",      "affects":"crownmart", "direction":-1, "strength":0.11, "real":True,
     "text":"Insider tip: CrownMart Q3 same-store sales are down 9%. Results due next week. Senior management are quietly reducing personal holdings."},
    {"type":"unverified", "label":"Unverified Rumour", "affects":"crownmart", "direction":-1, "strength":0.10, "real":False,
     "text":"Rumour: Two of CrownMart's key anchor stores in metro malls are facing lease non-renewal — landlords allegedly prefer quick-commerce dark store tenants."},

    # ════════════════════════════════════════════════════════════════
    # SHIELDGEN DEFENCE  (8 items)
    # ════════════════════════════════════════════════════════════════
    {"type":"verified",   "label":"Market Event",      "affects":"shieldgen", "direction": 1, "strength":0.11, "real":True,
     "text":"BREAKING: Escalating border tensions prompt ₹18,000 crore emergency defence procurement. ShieldGen named as primary supplier across 3 of 5 categories."},
    {"type":"verified",   "label":"Market Event",      "affects":"shieldgen", "direction": 1, "strength":0.09, "real":True,
     "text":"ShieldGen receives export clearance to supply radar systems to two allied nations — the company's first international defence contracts."},
    {"type":"verified",   "label":"Market Event",      "affects":"shieldgen", "direction": 1, "strength":0.10, "real":True,
     "text":"Defence budget hiked 18% in supplementary demands. ShieldGen's existing multi-year contracts automatically indexed to the higher allocation."},
    {"type":"verified",   "label":"Market Event",      "affects":"shieldgen", "direction":-1, "strength":0.08, "real":True,
     "text":"India signs a defence procurement agreement with a foreign OEM, bypassing the domestic industry for a high-value radar contract ShieldGen had expected to win."},
    {"type":"verified",   "label":"Market Event",      "affects":"shieldgen", "direction": 1, "strength":0.09, "real":True,
     "text":"ShieldGen wins 5-year maintenance contract for active army armoured fleet — recurring, high-margin revenue worth ₹4,200 crore over the period."},
    {"type":"unverified", "label":"Unverified Rumour", "affects":"shieldgen", "direction":-1, "strength":0.09, "real":False,
     "text":"Rumour: A parliamentary committee is reviewing ShieldGen's pricing on an armoured vehicle contract, alleging 40% cost inflation. Company denies."},
    {"type":"unverified", "label":"Insider Hint",      "affects":"shieldgen", "direction": 1, "strength":0.13, "real":True,
     "text":"Insider tip: ShieldGen has secured a classified 7-year maintenance contract for India's new drone programme — worth an estimated ₹6,000 crore."},
    {"type":"unverified", "label":"Unverified Rumour", "affects":"shieldgen", "direction": 1, "strength":0.10, "real":False,
     "text":"Rumour: ShieldGen is in talks to set up a joint venture with an Israeli defence firm to manufacture advanced surveillance drones in India."},

    # ════════════════════════════════════════════════════════════════
    # INDRANET  (8 items)
    # ════════════════════════════════════════════════════════════════
    {"type":"verified",   "label":"Market Event",      "affects":"indranet", "direction": 1, "strength":0.09, "real":True,
     "text":"IndraNet announces 18% growth in enterprise ARR and renews multi-year SaaS contracts with 3 PSU banks worth ₹900 crore in total."},
    {"type":"verified",   "label":"Market Event",      "affects":"indranet", "direction":-1, "strength":0.10, "real":True,
     "text":"BREAKING: IndraNet loses a ₹1,200 crore telecom infrastructure contract to a foreign competitor in a government tender. CFO resigns citing 'strategic differences'."},
    {"type":"verified",   "label":"Market Event",      "affects":"indranet", "direction": 1, "strength":0.09, "real":True,
     "text":"IndraNet launches an AI workflow automation layer — early enterprise pilots show 40% efficiency gains. Analysts call it a potential re-rating catalyst."},
    {"type":"verified",   "label":"Market Event",      "affects":"indranet", "direction": 1, "strength":0.08, "real":True,
     "text":"IndraNet expands into Southeast Asia — first 4 enterprise clients signed in Singapore and Malaysia. International revenue target set at 15% of total by FY27."},
    {"type":"verified",   "label":"Market Event",      "affects":"indranet", "direction":-1, "strength":0.09, "real":True,
     "text":"SkyLink announces a competing B2B SaaS platform at 20% lower pricing, directly targeting IndraNet's mid-market enterprise client base."},
    {"type":"unverified", "label":"Insider Hint",      "affects":"indranet", "direction": 1, "strength":0.12, "real":True,
     "text":"Insider tip: IndraNet is quietly preparing a product launch that will directly compete in SkyLink's core cloud infrastructure segment."},
    {"type":"unverified", "label":"Unverified Rumour", "affects":"indranet", "direction":-1, "strength":0.08, "real":False,
     "text":"Rumour: IndraNet's largest banking client is reviewing its SaaS contract renewal. A 20% revenue reduction in that account could hit annual earnings hard."},
    {"type":"unverified", "label":"Unverified Rumour", "affects":"indranet", "direction": 1, "strength":0.10, "real":False,
     "text":"Rumour: A mid-size US PE firm is running due diligence on IndraNet for a potential take-private transaction at a significant premium."},

    # ════════════════════════════════════════════════════════════════
    # NOVAPAY  (8 items — IPO, only after listed)
    # ════════════════════════════════════════════════════════════════
    {"type":"verified",   "label":"Market Event",      "affects":"novapay", "direction": 1, "strength":0.13, "real":True,
     "text":"NovaPay crosses 1 billion transactions in a single day — the first Indian fintech to hit this milestone. Listing premium jumps sharply."},
    {"type":"verified",   "label":"Market Event",      "affects":"novapay", "direction":-1, "strength":0.12, "real":True,
     "text":"BREAKING: RBI issues a show-cause notice to NovaPay over KYC compliance gaps affecting 4.2 million accounts. Operations partially restricted."},
    {"type":"verified",   "label":"Market Event",      "affects":"novapay", "direction": 1, "strength":0.11, "real":True,
     "text":"NovaPay B2B payment gateway signs 3 major e-commerce platforms — combined GMV of ₹1.4 lakh crore. Path to profitability now visible."},
    {"type":"verified",   "label":"Market Event",      "affects":"novapay", "direction":-1, "strength":0.11, "real":True,
     "text":"PhonePe announces zero-fee merchant payments, directly attacking NovaPay's B2B revenue model. Analysts cut NovaPay price targets by 15%."},
    {"type":"verified",   "label":"Market Event",      "affects":"novapay", "direction": 1, "strength":0.10, "real":True,
     "text":"NovaPay BNPL product reaches 8 million users in 5 months — fastest adoption for any credit product in Indian fintech history."},
    {"type":"unverified", "label":"Unverified Rumour", "affects":"novapay", "direction": 1, "strength":0.14, "real":False,
     "text":"Rumour: A Singapore sovereign fund is eyeing a 20% strategic stake in NovaPay at a valuation of 2× current market price. Unconfirmed."},
    {"type":"unverified", "label":"Insider Hint",      "affects":"novapay", "direction":-1, "strength":0.12, "real":True,
     "text":"Insider tip: NovaPay's internal audit has flagged irregularities in transaction fee reporting that may require a revenue restatement."},
    {"type":"unverified", "label":"Unverified Rumour", "affects":"novapay", "direction": 1, "strength":0.11, "real":False,
     "text":"Rumour: NovaPay has quietly applied for a small finance bank licence — if granted, this transforms it from a fintech into a fully regulated bank."},

    # ════════════════════════════════════════════════════════════════
    # GREENLEAF AGRI  (7 items — IPO, only after listed)
    # ════════════════════════════════════════════════════════════════
    {"type":"verified",   "label":"Market Event",      "affects":"greenleaf", "direction": 1, "strength":0.11, "real":True,
     "text":"GreenLeaf Agri onboards 200,000 new farmers this season. The government farm-to-fork subsidy scheme has been renewed for 3 more years."},
    {"type":"verified",   "label":"Market Event",      "affects":"greenleaf", "direction":-1, "strength":0.12, "real":True,
     "text":"BREAKING: Drought conditions declared across 3 of GreenLeaf's key operating states. Crop yield outlook revised down by 28%. Revenue guidance cut."},
    {"type":"verified",   "label":"Market Event",      "affects":"greenleaf", "direction": 1, "strength":0.10, "real":True,
     "text":"GreenLeaf signs supply agreements with 6 major retail chains, securing offtake for 40% of its produce network for the next 2 years."},
    {"type":"verified",   "label":"Market Event",      "affects":"greenleaf", "direction":-1, "strength":0.10, "real":True,
     "text":"A government review of agritech subsidies proposes 30% cuts in allocation. GreenLeaf, which relies on these for 31% of operating costs, faces margin risk."},
    {"type":"verified",   "label":"Market Event",      "affects":"greenleaf", "direction": 1, "strength":0.09, "real":True,
     "text":"GreenLeaf expands cold storage network to 40 new mandis. Post-harvest losses drop 18% — a key metric buyers and subsidisers track closely."},
    {"type":"unverified", "label":"Insider Hint",      "affects":"greenleaf", "direction": 1, "strength":0.11, "real":True,
     "text":"Insider tip: GreenLeaf is in advanced talks with a Gulf sovereign food security fund for a long-term export offtake agreement worth ₹2,000 crore annually."},
    {"type":"unverified", "label":"Unverified Rumour", "affects":"greenleaf", "direction":-1, "strength":0.09, "real":False,
     "text":"Rumour: A government audit has flagged GreenLeaf's subsidy claims as potentially inflated. A formal investigation may be underway."},

    # ════════════════════════════════════════════════════════════════
    # ARMORINC  (7 items — IPO, only after listed)
    # ════════════════════════════════════════════════════════════════
    {"type":"verified",   "label":"Market Event",      "affects":"armorinc", "direction": 1, "strength":0.10, "real":True,
     "text":"ArmorInc wins its first central paramilitary contract — 50,000 bulletproof vests for CRPF at ₹840 crore. Recurring procurement expected annually."},
    {"type":"verified",   "label":"Market Event",      "affects":"armorinc", "direction": 1, "strength":0.09, "real":True,
     "text":"ArmorInc's surveillance equipment division signs a ₹420 crore contract with 3 state police forces. High-margin, recurring service revenue begins."},
    {"type":"verified",   "label":"Market Event",      "affects":"armorinc", "direction":-1, "strength":0.09, "real":True,
     "text":"A foreign OEM wins an import tender for personal protective equipment that ArmorInc had expected to secure. 12% revenue shortfall anticipated."},
    {"type":"verified",   "label":"Market Event",      "affects":"armorinc", "direction": 1, "strength":0.08, "real":True,
     "text":"ArmorInc receives defence export licence for personal protection equipment. First shipment of ₹120 crore to an African nation dispatched."},
    {"type":"verified",   "label":"Market Event",      "affects":"armorinc", "direction": 1, "strength":0.10, "real":True,
     "text":"Escalating internal security concerns prompt ₹3,200 crore state government equipment procurement. ArmorInc wins the largest single order in its history."},
    {"type":"unverified", "label":"Insider Hint",      "affects":"armorinc", "direction": 1, "strength":0.12, "real":True,
     "text":"Insider tip: ArmorInc is in advanced acquisition talks for a Pune-based surveillance tech startup. A deal could double its addressable market overnight."},
    {"type":"unverified", "label":"Unverified Rumour", "affects":"armorinc", "direction": 1, "strength":0.10, "real":False,
     "text":"Rumour: ShieldGen is in preliminary talks to acquire ArmorInc at a 35% premium as part of a consolidation play in the domestic defence space."},

    # ════════════════════════════════════════════════════════════════
    # BYTECORP AI  (8 items — IPO, only after listed)
    # ════════════════════════════════════════════════════════════════
    {"type":"verified",   "label":"Market Event",      "affects":"bytecorp", "direction": 1, "strength":0.15, "real":True,
     "text":"ByteCorp AI's BharatGPT demo goes viral after a prominent US tech analyst calls it 'the most impressive multilingual AI model built outside the US'. Retail frenzy begins."},
    {"type":"verified",   "label":"Market Event",      "affects":"bytecorp", "direction":-1, "strength":0.14, "real":True,
     "text":"BREAKING: ByteCorp's AI enterprise pilot with a major private bank collapses after accuracy failures in Hindi and Tamil. The hype cycle takes a hard hit."},
    {"type":"verified",   "label":"Market Event",      "affects":"bytecorp", "direction": 1, "strength":0.13, "real":True,
     "text":"ByteCorp signs its first revenue-generating enterprise contract — a 2-year deal with a government ministry for AI-powered document processing at ₹180 crore."},
    {"type":"verified",   "label":"Market Event",      "affects":"bytecorp", "direction":-1, "strength":0.13, "real":True,
     "text":"OpenAI launches an Indian-language optimised model that benchmarks above BharatGPT on 7 of 11 regional language tests. ByteCorp's moat narrative cracks."},
    {"type":"verified",   "label":"Market Event",      "affects":"bytecorp", "direction": 1, "strength":0.12, "real":True,
     "text":"ByteCorp partners with India's largest telecom to embed BharatGPT across 480 million mobile users. Distribution reach far exceeds any competitor."},
    {"type":"verified",   "label":"Market Event",      "affects":"bytecorp", "direction":-1, "strength":0.11, "real":True,
     "text":"ByteCorp reports net cash burn of ₹420 crore for the quarter with no clear timeline to profitability. Institutional investors begin trimming positions."},
    {"type":"unverified", "label":"Unverified Rumour", "affects":"bytecorp", "direction": 1, "strength":0.15, "real":False,
     "text":"Rumour: Microsoft is in serious talks to invest ₹2,000 crore in ByteCorp AI. The CEO responded 'no comment'. Market has fully priced in the best case."},
    {"type":"unverified", "label":"Insider Hint",      "affects":"bytecorp", "direction": 1, "strength":0.14, "real":True,
     "text":"Insider tip: ByteCorp is weeks away from announcing a government AI contract worth ₹800 crore — the company's first large public-sector revenue deal."},

    # ════════════════════════════════════════════════════════════════
    # SECTOR-WIDE EVENTS  (20 items)
    # ════════════════════════════════════════════════════════════════
    {"type":"verified", "label":"Market Event", "affects":"sector:Technology", "direction": 1, "strength":0.08, "real":True,
     "text":"SECTOR: Government launches a ₹10,000 crore Digital India 3.0 push. Cloud, SaaS, and AI companies are the primary intended beneficiaries."},
    {"type":"verified", "label":"Market Event", "affects":"sector:Technology", "direction":-1, "strength":0.08, "real":True,
     "text":"SECTOR: A sweeping data localisation bill clears Rajya Sabha. Compliance costs for tech companies estimated at ₹4,000–8,000 crore industry-wide."},
    {"type":"verified", "label":"Market Event", "affects":"sector:Technology", "direction": 1, "strength":0.07, "real":True,
     "text":"SECTOR: India climbs to #3 globally in tech startup funding. Analyst upgrades across the sector as global capital inflows accelerate."},
    {"type":"verified", "label":"Market Event", "affects":"sector:Technology", "direction":-1, "strength":0.07, "real":True,
     "text":"SECTOR: Global tech selloff after US Fed signals higher-for-longer rates. Indian tech stocks, with high P/E multiples, bear the sharpest correction."},
    {"type":"verified", "label":"Market Event", "affects":"sector:FMCG",       "direction": 1, "strength":0.07, "real":True,
     "text":"SECTOR: Rural consumption surges 11% YoY as crop prices rise and rural wages hit a 5-year high. FMCG companies are broadly re-rated upward."},
    {"type":"verified", "label":"Market Event", "affects":"sector:FMCG",       "direction":-1, "strength":0.07, "real":True,
     "text":"SECTOR: Palm oil and edible oil prices spike 22% globally. Input cost pressure hits all FMCG manufacturers simultaneously."},
    {"type":"verified", "label":"Market Event", "affects":"sector:Defence",    "direction": 1, "strength":0.09, "real":True,
     "text":"SECTOR: Defence budget hiked 18% in supplementary demands. Domestic manufacturers across the sector receive order upgrades."},
    {"type":"verified", "label":"Market Event", "affects":"sector:Defence",    "direction": 1, "strength":0.08, "real":True,
     "text":"SECTOR: Government announces 'Make in India' defence mandate requiring 70% domestic content. Foreign OEMs must partner with Indian firms."},
    {"type":"verified", "label":"Market Event", "affects":"sector:Pharma",     "direction":-1, "strength":0.07, "real":True,
     "text":"SECTOR: US FDA issues import alerts on 4 Indian pharmaceutical manufacturing plants. Export revenue for several companies at risk."},
    {"type":"verified", "label":"Market Event", "affects":"sector:Pharma",     "direction": 1, "strength":0.07, "real":True,
     "text":"SECTOR: WHO qualifies 3 more Indian generic drug manufacturers for global supply. Export opportunity worth ₹12,000 crore opens up."},
    {"type":"verified", "label":"Market Event", "affects":"sector:Logistics",  "direction":-1, "strength":0.07, "real":True,
     "text":"SECTOR: New national highway toll policy hikes rates by 15%. All logistics and trucking companies face immediate cost increases."},
    {"type":"verified", "label":"Market Event", "affects":"sector:Logistics",  "direction": 1, "strength":0.07, "real":True,
     "text":"SECTOR: GST Council announces simplified e-way bill process, reducing logistics compliance costs. Entire sector benefits from efficiency gains."},
    {"type":"verified", "label":"Market Event", "affects":"sector:Renewable Energy", "direction": 1, "strength":0.08, "real":True,
     "text":"SECTOR: India achieves new solar installation record. Government doubles renewable energy subsidies for the next 3 fiscal years."},
    {"type":"verified", "label":"Market Event", "affects":"sector:Renewable Energy", "direction":-1, "strength":0.07, "real":True,
     "text":"SECTOR: Solar panel import tariffs hiked 12%. Domestic project costs rise for all renewable energy companies."},
    {"type":"verified", "label":"Market Event", "affects":"sector:Fintech",    "direction": 1, "strength":0.08, "real":True,
     "text":"SECTOR: UPI transaction volume crosses 20 billion monthly. RBI announces new incentive framework for digital payment platforms."},
    {"type":"verified", "label":"Market Event", "affects":"sector:Fintech",    "direction":-1, "strength":0.08, "real":True,
     "text":"SECTOR: RBI tightens digital lending norms. Fintech companies face new capital adequacy requirements that squeeze short-term profitability."},
    {"type":"verified", "label":"Market Event", "affects":"sector:Agriculture","direction": 1, "strength":0.07, "real":True,
     "text":"SECTOR: Government announces largest-ever agritech investment package at ₹8,500 crore. Agritech startups and listed companies both benefit."},
    {"type":"verified", "label":"Market Event", "affects":"sector:Agriculture","direction":-1, "strength":0.07, "real":True,
     "text":"SECTOR: A poor monsoon forecast triggers broad-based selling in agri-dependent businesses. Crop yield estimates revised down 15%."},
    {"type":"verified", "label":"Market Event", "affects":"sector:Media / OTT","direction": 1, "strength":0.07, "real":True,
     "text":"SECTOR: Internet penetration reaches 900 million users in India. OTT platforms are the biggest beneficiaries of the next wave of digital adoption."},
    {"type":"verified", "label":"Market Event", "affects":"sector:Manufacturing","direction": 1, "strength":0.07, "real":True,
     "text":"SECTOR: PLI (Production Linked Incentive) scheme extended for 3 years. Manufacturing companies across steel, defence, and infrastructure to benefit."},
]

# ── DB setup ───────────────────────────────────────────────────────────────────
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
                code     TEXT PRIMARY KEY,
                name     TEXT,
                cash     REAL DEFAULT 50000,
                holdings TEXT DEFAULT '{}',
                loans    TEXT DEFAULT '{}',
                frozen   INTEGER DEFAULT 0,
                avg_cost TEXT DEFAULT '{}',
                bets     TEXT DEFAULT '{}',
                bm_log   TEXT DEFAULT '[]'
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
        "phase":          "lobby",
        "round":          0,
        "round_end_time": None,
        "break_end_time": None,
        "companies":      companies,
        "ipo_listed":     [],          # list of listed IPO ids
        "news":           [],
        "news_used":      [],
        "regulatory_freeze": None,     # sector name or None
        "acquisition_pair":  None,     # [cid1, cid2] or None
        "credit_crunch":     False,
        "merge_bids":        {},
    }

# ── Connection manager ─────────────────────────────────────────────────────────
class ConnectionManager:
    def __init__(self):
        self.players: Dict[str, WebSocket] = {}
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

# ── Player helpers ─────────────────────────────────────────────────────────────
async def all_codes():
    async with aiosqlite.connect(DB_PATH) as db:
        rows = await (await db.execute("SELECT code FROM codes")).fetchall()
    return {r[0] for r in rows}

async def all_players():
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        rows = await (await db.execute("SELECT * FROM players")).fetchall()
    result = []
    for row in rows:
        result.append({
            "code":     row["code"],
            "name":     row["name"],
            "cash":     row["cash"],
            "holdings": json.loads(row["holdings"]),
            "loans":    json.loads(row["loans"]),
            "frozen":   bool(row["frozen"]),
            "avg_cost": json.loads(row["avg_cost"]),
            "bets":     json.loads(row["bets"]),
            "bm_log":   json.loads(row["bm_log"]),
        })
    return result

async def get_player(code: str) -> Optional[dict]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        row = await (await db.execute("SELECT * FROM players WHERE code=?", (code,))).fetchone()
        if not row:
            return None
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
        await db.execute("""
            INSERT OR REPLACE INTO players
            (code,name,cash,holdings,loans,frozen,avg_cost,bets,bm_log)
            VALUES (?,?,?,?,?,?,?,?,?)
        """, (
            p["code"], p.get("name"), p["cash"],
            json.dumps(p["holdings"]),
            json.dumps(p.get("loans", {})),
            int(p.get("frozen", False)),
            json.dumps(p.get("avg_cost", {})),
            json.dumps(p.get("bets", {})),
            json.dumps(p.get("bm_log", [])),
        ))
        await db.commit()

def player_loans_total(p: dict) -> float:
    return sum(p.get("loans", {}).values())

def player_view(p: dict, state: dict) -> dict:
    companies = state["companies"]
    portfolio = {}
    for cid, qty in p["holdings"].items():
        if qty > 0 and cid in companies:
            c    = companies[cid]
            avg  = p.get("avg_cost", {}).get(cid, c["price"])
            price = c["price"]
            val  = qty * price
            portfolio[cid] = {
                "qty":   qty,
                "avg":   avg,
                "price": price,
                "value": val,
                "pnl":   val - qty * avg,
            }
    port_value  = sum(h["value"] for h in portfolio.values())
    total_loans = player_loans_total(p)
    net_worth   = p["cash"] + port_value - total_loans
    return {
        "cash":      p["cash"],
        "loans":     p.get("loans", {}),
        "total_loan": total_loans,
        "frozen":    p["frozen"],
        "net_worth": net_worth,
        "portfolio": portfolio,
        "bets":      p.get("bets", {}),
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

# ── Price fluctuation with sector ripples ──────────────────────────────────────
def fluctuate_prices(state: dict, news: list[dict]):
    companies = state["companies"]
    freeze    = state.get("regulatory_freeze")  # sector name
    acq_pair  = state.get("acquisition_pair")   # [cid1, cid2]
    moved     = {}  # cid -> pct change for ripple reference

    for cid, c in companies.items():
        c["prev_price"] = c["price"]
        # Freeze check
        if freeze and c.get("sector") == freeze:
            continue
        lo, hi, bias = COMPANY_VOL.get(cid, (0.02, 0.06, 0.45))
        mag       = random.uniform(lo, hi)
        direction = 1 if random.random() > bias else -1
        change    = direction * mag

        # News impact
        for n in news:
            aff = n["affects"]
            if aff == cid:
                if n.get("real", True):
                    impact = n.get("strength", random.uniform(0.07, 0.14))
                else:
                    # Unverified: random chance of being real
                    if random.random() < 0.4:
                        impact = n.get("strength", random.uniform(0.07, 0.14)) * 0.6
                    else:
                        impact = random.uniform(0.01, 0.03)
                change += n["direction"] * impact
            elif aff.startswith("sector:"):
                sector = aff.split(":", 1)[1]
                if c.get("sector") == sector and n.get("real", True):
                    change += n["direction"] * n.get("strength", 0.08) * 0.7

        # Acquisition rumour: correlated movement
        if acq_pair and cid in acq_pair:
            other_cid = acq_pair[1] if cid == acq_pair[0] else acq_pair[0]
            other_prev = companies.get(other_cid, {}).get("prev_price", 0)
            if other_prev and cid != acq_pair[0]:  # follower moves with initiator
                if other_cid in moved:
                    change = moved[other_cid] * 0.8 + change * 0.2

        c["price"] = max(10, round(c["price"] * (1 + change)))
        moved[cid] = change

    # Sector ripple: if a company in a sector moved strongly, apply ±3-5% to peers
    for sector, members in SECTORS.items():
        for cid in members:
            if cid not in companies or cid not in moved:
                continue
            pct = moved[cid]
            if abs(pct) > 0.06:
                for peer in members:
                    if peer == cid or peer not in companies:
                        continue
                    if freeze and companies[peer].get("sector") == freeze:
                        continue
                    ripple_mag = random.uniform(0.03, 0.05)
                    ripple_dir = -1 if pct > 0 else 1  # opposite direction
                    companies[peer]["price"] = max(10, round(
                        companies[peer]["price"] * (1 + ripple_dir * ripple_mag)
                    ))

# ── Passive price drift ────────────────────────────────────────────────────────
async def price_drift_loop():
    await asyncio.sleep(30)
    while True:
        await asyncio.sleep(DRIFT_INTERVAL)
        state = await read_state()
        if state.get("phase") != "trading":
            continue
        freeze   = state.get("regulatory_freeze")
        companies = state["companies"]
        changed  = False
        for cid, c in companies.items():
            if freeze and c.get("sector") == freeze:
                continue
            lo, hi, bias = COMPANY_VOL.get(cid, (0.005, 0.03, 0.46))
            mag  = random.uniform(0.002, min(0.03, hi * 0.4))
            direc = 1 if random.random() > bias else -1
            c["price"] = max(10, round(c["price"] * (1 + direc * mag)))
            changed = True
        if changed:
            await write_state(state)
            players = await all_players()
            board   = leaderboard(players, state)
            prices  = {k: v["price"] for k, v in companies.items()}
            await manager.broadcast_all({"type": "prices_bulk", "prices": prices, "board": board})

# ── Pick news from pool ────────────────────────────────────────────────────────
def pick_news(state: dict, count: int = 3) -> list[dict]:
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
        if aff.startswith("sector:"):
            pass  # always eligible
        pool.append(n)
    chosen = random.sample(pool, min(count, len(pool)))
    state["news_used"] = state.get("news_used", []) + [n["text"] for n in chosen]
    return chosen

# ── Prediction market helpers ──────────────────────────────────────────────────
def compute_sentiment(players: list[dict], companies: dict) -> dict:
    """Per stock: tally UP vs DOWN bets. Returns {cid: {up_pct, down_pct, total_bets}}"""
    tally = {cid: {"up": 0, "down": 0} for cid in companies}
    for p in players:
        for cid, bet in (p.get("bets") or {}).items():
            if cid not in tally:
                tally[cid] = {"up": 0, "down": 0}
            if bet.get("direction") == "up":
                tally[cid]["up"] += bet.get("amount", 0)
            else:
                tally[cid]["down"] += bet.get("amount", 0)
    result = {}
    for cid, t in tally.items():
        total = t["up"] + t["down"]
        if total > 0:
            result[cid] = {
                "up_pct":    round(t["up"] / total * 100),
                "down_pct":  round(t["down"] / total * 100),
                "total_bets": total,
            }
    return result

async def resolve_predictions(state: dict, players: list[dict]):
    """Called at round end. Evaluate each player's open bets against final prices."""
    companies = state["companies"]
    for p in players:
        if not p.get("bets"):
            continue
        changed = False
        for cid, bet in list(p["bets"].items()):
            if cid not in companies:
                continue
            curr_price = companies[cid]["price"]
            prev_price = companies[cid].get("prev_price", curr_price)
            direction  = bet.get("direction")
            target     = bet.get("target", 0)
            amount     = bet.get("amount", 0)
            correct_dir = (direction == "up" and curr_price > prev_price) or \
                          (direction == "down" and curr_price < prev_price)
            target_hit  = (direction == "up" and curr_price >= target) or \
                          (direction == "down" and curr_price <= target)
            if correct_dir and target_hit:
                payout = amount * 3
                p["cash"] += payout
                await manager.send_player(p["code"], {
                    "type": "info",
                    "msg":  f"🎯 Prediction HIT! {companies[cid]['name']} — direction + target both correct. 3× payout: +₹{int(payout):,}",
                })
            elif correct_dir:
                payout = int(amount * 1.5)
                p["cash"] += payout
                await manager.send_player(p["code"], {
                    "type": "info",
                    "msg":  f"✅ Prediction PARTIAL — direction correct, target not reached. 1.5× payout: +₹{payout:,}",
                })
            else:
                await manager.send_player(p["code"], {
                    "type": "info",
                    "msg":  f"❌ Prediction WRONG on {companies[cid]['name']}. Bet of ₹{int(amount):,} lost.",
                })
            changed = True
        if changed:
            p["bets"] = {}
            await save_player(p)

# ── Lifespan ───────────────────────────────────────────────────────────────────
@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    asyncio.create_task(price_drift_loop())
    yield

app = FastAPI(lifespan=lifespan)

BASE_DIR = Path(__file__).parent

# ── HTML routes ────────────────────────────────────────────────────────────────
@app.get("/", response_class=HTMLResponse)
async def serve_team():
    p = BASE_DIR / "team.html"
    return HTMLResponse(p.read_text(encoding="utf-8") if p.exists() else "<h1>team.html not found</h1>", status_code=200 if p.exists() else 404)

@app.get("/host", response_class=HTMLResponse)
async def serve_host():
    p = BASE_DIR / "host.html"
    return HTMLResponse(p.read_text(encoding="utf-8") if p.exists() else "<h1>host.html not found</h1>", status_code=200 if p.exists() else 404)

@app.get("/bm", response_class=HTMLResponse)
async def serve_bm():
    # Black market skeleton — items built in Stage 3
    return HTMLResponse("""<!DOCTYPE html><html><head><meta charset='UTF-8'>
<meta name='viewport' content='width=device-width,initial-scale=1'>
<title>Black Market</title>
<style>
body{background:#0a0006;color:#e0c8f0;font-family:monospace;display:flex;align-items:center;justify-content:center;min-height:100vh;margin:0;padding:24px;box-sizing:border-box;}
.c{text-align:center;max-width:360px;}
.skull{font-size:64px;margin-bottom:24px;}
h1{font-size:24px;color:#d1a6f7;margin-bottom:8px;}
p{font-size:14px;color:rgba(255,255,255,0.4);line-height:1.6;}
.enter-btn{margin-top:32px;padding:14px 32px;background:rgba(163,113,247,0.15);border:1px solid rgba(163,113,247,0.4);color:#d1a6f7;border-radius:8px;font-family:monospace;font-size:14px;cursor:pointer;}
.code-input{width:100%;margin-top:16px;background:#0d0010;border:1px solid rgba(163,113,247,0.3);border-radius:8px;padding:12px;color:#e0c8f0;font-family:monospace;font-size:16px;text-align:center;outline:none;}
</style></head><body>
<div class='c'>
  <div class='skull'>🖤</div>
  <h1>Black Market</h1>
  <p>You found it. Not everyone does.</p>
  <p style='margin-top:16px;color:rgba(163,113,247,0.5)'>Items coming online soon. Check back mid-game.</p>
  <input class='code-input' placeholder='Enter BM code' maxlength='8'>
  <button class='enter-btn'>Enter</button>
</div>
</body></html>""")

# ── REST: code management ──────────────────────────────────────────────────────
@app.post("/api/codes/generate")
async def generate_codes(count: int = 10):
    codes = [uuid.uuid4().hex[:6].upper() for _ in range(count)]
    async with aiosqlite.connect(DB_PATH) as db:
        await db.executemany("INSERT OR IGNORE INTO codes (code) VALUES (?)", [(c,) for c in codes])
        await db.commit()
    return {"codes": codes}

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

@app.get("/api/state")
async def api_state():
    state   = await read_state()
    players = await all_players()
    board   = leaderboard(players, state)
    return {"state": state, "board": board, "player_count": len([p for p in players if p["name"]])}

@app.get("/api/banks")
async def api_banks():
    return {"banks": BANKS}

@app.get("/api/players")
async def api_players():
    state   = await read_state()
    players = await all_players()
    board   = leaderboard(players, state)
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
            "code":      p["code"],
            "name":      p["name"],
            "cash":      p["cash"],
            "loans":     p.get("loans", {}),
            "total_loan": player_loans_total(p),
            "frozen":    p["frozen"],
            "net_worth": pv["net_worth"],
        })
    result.sort(key=lambda x: x["net_worth"], reverse=True)
    return {"players": result}

@app.get("/api/predictions/overview")
async def api_predictions_overview():
    state   = await read_state()
    players = await all_players()
    sentiment = compute_sentiment(players, state["companies"])
    all_bets  = []
    for p in players:
        for cid, bet in (p.get("bets") or {}).items():
            all_bets.append({
                "player": p["name"],
                "stock":  cid,
                "stock_name": state["companies"].get(cid, {}).get("name", cid),
                "direction": bet.get("direction"),
                "target":    bet.get("target"),
                "amount":    bet.get("amount"),
            })
    return {"sentiment": sentiment, "bets": all_bets}

@app.delete("/api/players/{code}")
async def kick_player(code: str, pw: str):
    if pw != HOST_PASSWORD:
        raise HTTPException(403, "Wrong password")
    async with aiosqlite.connect(DB_PATH) as db:
        row  = await (await db.execute("SELECT name FROM players WHERE code=?", (code,))).fetchone()
        name = row[0] if row else code
        await db.execute("DELETE FROM players WHERE code=?", (code,))
        await db.execute("DELETE FROM codes WHERE code=?", (code,))
        await db.commit()
    ws = manager.players.get(code)
    if ws:
        try:
            await ws.send_text(json.dumps({"type": "kicked", "msg": "You have been removed from the game by the host."}))
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
async def api_reset():
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("DELETE FROM players")
        await db.execute("DELETE FROM codes")
        await _write_state(db, _default_state())
        await db.commit()
    await manager.broadcast_all({"type": "reset"})
    await manager.broadcast_hosts({"type": "reset"})
    return {"ok": True}

# ── REST: host game controls ───────────────────────────────────────────────────
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
    # Clear per-round chaos that auto-resets
    state["regulatory_freeze"] = None
    state["acquisition_pair"]  = None
    # Reset credit crunch (lasts 1 round only — rates reverted)
    state["credit_crunch"] = False
    # Unfreeze all players
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
        "type":   "phase_change",
        "phase":  "trading",
        "round":  state["round"],
        "prices": {k: c["price"] for k, c in state["companies"].items()},
        "board":  board,
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
        raise HTTPException(400, "Not in trading phase")
    state["phase"]          = "break"
    state["round_end_time"] = None
    state["break_end_time"] = time.time() + 300
    # Clear chaos
    state["regulatory_freeze"] = None
    state["acquisition_pair"]  = None
    # Apply interest on each bank's balance independently
    players = await all_players()
    for p in players:
        loans   = p.get("loans", {})
        changed = False
        for bank_id, bal in list(loans.items()):
            if bal > 0:
                rate         = BANKS[bank_id]["rate"]
                # Credit crunch adds +5%
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
                "msg":    "Interest charged on your loans.",
            })
    # Reset credit crunch for next round
    state["credit_crunch"] = False
    # Resolve prediction market
    players = await all_players()
    await resolve_predictions(state, players)
    await write_state(state)
    players = await all_players()
    board   = leaderboard(players, state)
    await manager.broadcast_all({"type": "phase_change", "phase": "break", "round": state["round"], "board": board})
    await manager.broadcast_hosts({"type": "state_update", "state": state, "board": board})
    return {"ok": True}

@app.post("/api/host/end_game")
async def end_game(pw: str):
    if pw != HOST_PASSWORD:
        raise HTTPException(403)
    state   = await read_state()
    state["phase"] = "ended"
    await write_state(state)
    players = await all_players()
    board   = leaderboard(players, state)
    await manager.broadcast_all({"type": "game_ended", "board": board})
    await manager.broadcast_hosts({"type": "state_update", "state": state, "board": board})
    return {"ok": True}

@app.post("/api/host/adjust_cash")
async def adjust_cash(data: dict, pw: str):
    if pw != HOST_PASSWORD:
        raise HTTPException(403)
    code      = data["code"]
    amount    = int(data["amount"])
    direction = 1 if data.get("direction", 1) > 0 else -1
    p = await get_player(code)
    if not p:
        raise HTTPException(404, "Player not found")
    p["cash"] = max(0, p["cash"] + direction * amount)
    await save_player(p)
    state = await read_state()
    view  = player_view(p, state)
    await manager.send_player(code, {"type": "player_update", "player": view})
    sign = "+" if direction > 0 else "-"
    await manager.send_player(code, {"type": "info", "msg": f"Host adjustment: {sign}₹{amount:,}"})
    players = await all_players()
    board   = leaderboard(players, state)
    await manager.broadcast_hosts({"type": "state_update", "state": state, "board": board, "player_count": len([x for x in players if x["name"]])})
    return {"ok": True}

@app.post("/api/host/inject_news")
async def inject_news(data: dict, pw: str):
    if pw != HOST_PASSWORD:
        raise HTTPException(403)
    state  = await read_state()
    is_verified = data.get("verified", True)
    n = {
        "type":      "verified" if is_verified else "unverified",
        "label":     "Market Event" if is_verified else "Unverified Rumour",
        "text":      data["text"],
        "affects":   data["affects"],
        "direction": data.get("direction", 1),
        "strength":  data.get("strength", 0.10),
        "real":      is_verified,  # verified always real; unverified always treated as maybe
    }
    state["news"].append(n)
    c = state["companies"].get(data["affects"])
    if c and state["phase"] == "trading":
        c["prev_price"] = c["price"]
        if is_verified:
            strength = n.get("strength", random.uniform(0.07, 0.14))
        else:
            strength = n.get("strength", random.uniform(0.01, 0.05)) if random.random() < 0.4 else random.uniform(0.01, 0.03)
        c["price"] = max(10, round(c["price"] * (1 + n["direction"] * strength)))
    await write_state(state)
    await manager.broadcast_all({"type": "news", **n})
    players = await all_players()
    board   = leaderboard(players, state)
    await manager.broadcast_all({"type": "prices_bulk", "prices": {k: v["price"] for k, v in state["companies"].items()}, "board": board})
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

# ── REST: chaos events ─────────────────────────────────────────────────────────
@app.post("/api/chaos/regulatory_freeze")
async def chaos_regulatory_freeze(data: dict, pw: str):
    """Freeze all trading for a sector for the rest of this round."""
    if pw != HOST_PASSWORD:
        raise HTTPException(403)
    sector = data["sector"]
    # Validate sector exists
    sector_companies = [cid for cid, c in (await read_state())["companies"].items() if c.get("sector") == sector]
    if not sector_companies:
        raise HTTPException(400, f"No companies in sector '{sector}'")
    state = await read_state()
    state["regulatory_freeze"] = sector
    await write_state(state)
    msg = f"🚫 REGULATORY FREEZE — All trading halted for the {sector} sector for this round! Cards greyed out."
    await manager.broadcast_all({
        "type": "chaos", "event": "regulatory_freeze",
        "sector": sector, "frozen_stocks": sector_companies, "msg": msg,
    })
    return {"ok": True, "sector": sector, "frozen_stocks": sector_companies}

@app.post("/api/chaos/dividend")
async def chaos_dividend(data: dict, pw: str):
    """Pay dividend per share to all holders of a company."""
    if pw != HOST_PASSWORD:
        raise HTTPException(403)
    state  = await read_state()
    cid    = data["stock"]
    per_share = int(data["per_share"])
    if cid not in state["companies"]:
        raise HTTPException(400, "Unknown stock")
    cname  = state["companies"][cid]["name"]
    players = await all_players()
    total_paid = 0
    for p in players:
        qty = p["holdings"].get(cid, 0)
        if qty > 0:
            dividend = qty * per_share
            p["cash"] += dividend
            total_paid += dividend
            await save_player(p)
            pv = player_view(p, state)
            await manager.send_player(p["code"], {
                "type":   "player_update",
                "player": pv,
                "msg":    f"💰 Dividend! {qty} × {cname} @ ₹{per_share}/share = +₹{dividend:,}",
            })
    players = await all_players()
    board   = leaderboard(players, state)
    msg = f"💰 DIVIDEND DECLARED — {cname} pays ₹{per_share:,} per share to all holders! Total paid out: ₹{total_paid:,}"
    await manager.broadcast_all({"type": "chaos", "event": "dividend", "stock": cid, "msg": msg, "board": board})
    await manager.broadcast_hosts({"type": "state_update", "state": state, "board": board})
    return {"ok": True, "total_paid": total_paid}

@app.post("/api/chaos/acquisition_rumour")
async def chaos_acquisition(data: dict, pw: str):
    """Make two companies' prices correlated for the rest of this round."""
    if pw != HOST_PASSWORD:
        raise HTTPException(403)
    state = await read_state()
    cid1  = data["stock1"]
    cid2  = data["stock2"]
    if cid1 not in state["companies"] or cid2 not in state["companies"]:
        raise HTTPException(400, "Unknown stocks")
    state["acquisition_pair"] = [cid1, cid2]
    await write_state(state)
    n1 = state["companies"][cid1]["name"]
    n2 = state["companies"][cid2]["name"]
    msg = f"🤝 ACQUISITION RUMOUR — {n1} and {n2} rumoured to merge! Their prices are now correlated. (Unverified)"
    await manager.broadcast_all({
        "type": "chaos", "event": "acquisition_rumour",
        "stock1": cid1, "stock2": cid2, "msg": msg,
    })
    # Also broadcast as an unverified news item
    n = {"type": "unverified", "label": "Unverified Rumour", "affects": cid1,
         "direction": 1, "real": False, "text": msg}
    await manager.broadcast_all({"type": "news", **n})
    return {"ok": True}

@app.post("/api/chaos/credit_crunch")
async def chaos_credit_crunch(pw: str):
    """Raise all bank rates +5% for 1 round."""
    if pw != HOST_PASSWORD:
        raise HTTPException(403)
    state = await read_state()
    state["credit_crunch"] = True
    await write_state(state)
    msg = "💸 CREDIT CRUNCH — All bank interest rates +5% this round! Bharat→10%, VentureCapX→14%, ShadowCredit→21%. Heavy borrowers beware."
    await manager.broadcast_all({"type": "chaos", "event": "credit_crunch", "msg": msg})
    return {"ok": True}

@app.post("/api/chaos/ipo_drop/{ipo_id}")
async def chaos_ipo_drop(ipo_id: str, pw: str):
    if pw != HOST_PASSWORD:
        raise HTTPException(403)
    if ipo_id not in IPO_COMPANIES:
        raise HTTPException(400, f"Unknown IPO: {ipo_id}")
    state = await read_state()
    if ipo_id in state.get("ipo_listed", []):
        raise HTTPException(400, f"{ipo_id} already listed")
    ipo = IPO_COMPANIES[ipo_id]
    state["companies"][ipo_id] = {**ipo, "prev_price": ipo["price"]}
    state["ipo_listed"] = state.get("ipo_listed", []) + [ipo_id]
    await write_state(state)
    msg = f"🚀 IPO DROP — {ipo['name']} lists on the exchange! {ipo['trait']} IPO price: ₹{ipo['price']:,}"
    await manager.broadcast_all({
        "type":    "chaos",
        "event":   "ipo_drop",
        "msg":     msg,
        "company": {"id": ipo_id, **ipo},
    })
    return {"ok": True, "company": {"id": ipo_id, **ipo}}

# ── REST: loans (host view + manual override) ──────────────────────────────────
@app.post("/api/host/secret_intel")
async def secret_intel(data: dict, pw: str):
    """Send a private news tip to one player. Only they see it."""
    if pw != HOST_PASSWORD:
        raise HTTPException(403)
    code = data["code"]
    n = {"type": "unverified", "label": "Secret Intel", "text": data["text"], "private": True}
    await manager.send_player(code, {"type": "news", **n})
    return {"ok": True}

@app.post("/api/host/wipe_loan")
async def wipe_loan(data: dict, pw: str):
    """Host manually clears a player's loan at a specific bank."""
    if pw != HOST_PASSWORD:
        raise HTTPException(403)
    code    = data["code"]
    bank_id = data["bank_id"]
    p = await get_player(code)
    if not p:
        raise HTTPException(404)
    p["loans"].pop(bank_id, None)
    await save_player(p)
    state = await read_state()
    await manager.send_player(code, {"type": "player_update", "player": player_view(p, state)})
    return {"ok": True}

# ── WebSocket: player ──────────────────────────────────────────────────────────
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
    already_joined = player is not None and bool(player["name"])

    init_msg = {
        "type":         "init",
        "phase":        state["phase"],
        "round":        state["round"],
        "market":       state["companies"],
        "board":        leaderboard(await all_players(), state),
        "banks":        BANKS,
        "joined":       bool(already_joined),
        "reg_freeze":   state.get("regulatory_freeze"),
        "credit_crunch": state.get("credit_crunch", False),
    }
    if already_joined:
        init_msg["name"]   = player["name"]
        init_msg["player"] = player_view(player, state)
    await websocket.send_text(json.dumps(init_msg))

    try:
        async for raw in websocket.iter_text():
            msg    = json.loads(raw)
            action = msg.get("action")
            state  = await read_state()
            player = await get_player(code)

            # ── Set name ───────────────────────────────────────────────────────
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

            # ── Buy ────────────────────────────────────────────────────────────
            elif action == "buy":
                if state["phase"] != "trading":
                    await websocket.send_text(json.dumps({"type": "error", "msg": "Trading is closed."})); continue
                if not player:
                    await websocket.send_text(json.dumps({"type": "error", "msg": "Join first."})); continue
                if player["frozen"]:
                    await websocket.send_text(json.dumps({"type": "error", "msg": "Portfolio frozen this round."})); continue
                stock = msg.get("stock")
                qty   = int(msg.get("qty", 0))
                if stock not in state["companies"] or qty < 1:
                    await websocket.send_text(json.dumps({"type": "error", "msg": "Invalid stock or quantity."})); continue
                # Regulatory freeze check
                freeze = state.get("regulatory_freeze")
                if freeze and state["companies"][stock].get("sector") == freeze:
                    await websocket.send_text(json.dumps({"type": "error", "msg": f"⛔ {state['companies'][stock]['sector']} sector is under Regulatory Freeze — no trading allowed."})); continue
                price = state["companies"][stock]["price"]
                cost  = price * qty
                if player["cash"] < cost:
                    await websocket.send_text(json.dumps({"type": "error", "msg": f"Need ₹{cost:,}. You have ₹{int(player['cash']):,}."})); continue
                player["cash"] -= cost
                old_qty = player["holdings"].get(stock, 0)
                old_avg = player["avg_cost"].get(stock, price)
                player["avg_cost"][stock] = ((old_avg * old_qty + price * qty) / (old_qty + qty)) if old_qty else price
                player["holdings"][stock] = old_qty + qty
                await save_player(player)
                pv = player_view(player, state)
                await websocket.send_text(json.dumps({
                    "type":   "trade_ok",
                    "msg":    f"Bought {qty}× {state['companies'][stock]['name']} @ ₹{price:,}",
                    "player": pv,
                }))
                board = leaderboard(await all_players(), state)
                await manager.broadcast_all({"type": "leaderboard", "board": board})

            # ── Sell ───────────────────────────────────────────────────────────
            elif action == "sell":
                if state["phase"] != "trading":
                    await websocket.send_text(json.dumps({"type": "error", "msg": "Trading is closed."})); continue
                if not player:
                    await websocket.send_text(json.dumps({"type": "error", "msg": "Join first."})); continue
                if player["frozen"]:
                    await websocket.send_text(json.dumps({"type": "error", "msg": "Portfolio frozen this round."})); continue
                stock = msg.get("stock")
                qty   = int(msg.get("qty", 0))
                owned = player["holdings"].get(stock, 0)
                if qty < 1 or qty > owned:
                    await websocket.send_text(json.dumps({"type": "error", "msg": f"You only own {owned} shares."})); continue
                freeze = state.get("regulatory_freeze")
                if freeze and state["companies"].get(stock, {}).get("sector") == freeze:
                    await websocket.send_text(json.dumps({"type": "error", "msg": "⛔ Regulatory Freeze active — trading halted for this sector."})); continue
                price = state["companies"][stock]["price"]
                player["cash"] += price * qty
                player["holdings"][stock] = owned - qty
                await save_player(player)
                pv = player_view(player, state)
                await websocket.send_text(json.dumps({
                    "type":   "trade_ok",
                    "msg":    f"Sold {qty}× {state['companies'][stock]['name']} @ ₹{price:,}",
                    "player": pv,
                }))
                board = leaderboard(await all_players(), state)
                await manager.broadcast_all({"type": "leaderboard", "board": board})

            # ── Take loan ──────────────────────────────────────────────────────
            elif action == "take_loan":
                if not player:
                    await websocket.send_text(json.dumps({"type": "error", "msg": "Join first."})); continue
                bank_id = msg.get("bank_id")
                amount  = int(msg.get("amount", 0))
                if bank_id not in BANKS:
                    await websocket.send_text(json.dumps({"type": "error", "msg": "Invalid bank."})); continue
                bank = BANKS[bank_id]
                current_bal = player.get("loans", {}).get(bank_id, 0)
                if current_bal + amount > bank["limit"]:
                    remain = bank["limit"] - current_bal
                    await websocket.send_text(json.dumps({"type": "error", "msg": f"Exceeds {bank['name']} limit. Max additional drawdown: ₹{remain:,}."})); continue
                if amount not in bank["options"] and amount > bank["limit"]:
                    pass  # allow any amount up to limit
                player["cash"] += amount
                player["loans"][bank_id] = current_bal + amount
                await save_player(player)
                pv = player_view(player, state)
                rate = bank["rate"]
                if state.get("credit_crunch"):
                    rate += 0.05
                await websocket.send_text(json.dumps({
                    "type":   "trade_ok",
                    "msg":    f"₹{amount:,} from {bank['name']}. Running balance: ₹{int(player['loans'][bank_id]):,}. Interest rate: {rate*100:.0f}%/round.",
                    "player": pv,
                }))

            # ── Repay loan ─────────────────────────────────────────────────────
            elif action == "repay_loan":
                if not player:
                    await websocket.send_text(json.dumps({"type": "error", "msg": "Join first."})); continue
                if state["phase"] != "break":
                    await websocket.send_text(json.dumps({"type": "error", "msg": "Loans can only be repaid during break periods."})); continue
                bank_id   = msg.get("bank_id")
                repay_amt = int(msg.get("amount", 0))
                if bank_id not in BANKS:
                    await websocket.send_text(json.dumps({"type": "error", "msg": "Invalid bank."})); continue
                bal = player.get("loans", {}).get(bank_id, 0)
                if bal <= 0:
                    await websocket.send_text(json.dumps({"type": "error", "msg": f"No balance at {BANKS[bank_id]['name']}."})); continue
                repay_amt = min(repay_amt, int(bal))
                if player["cash"] < repay_amt:
                    await websocket.send_text(json.dumps({"type": "error", "msg": f"Not enough cash. You have ₹{int(player['cash']):,}."})); continue
                player["cash"] -= repay_amt
                remaining = max(0, bal - repay_amt)
                if remaining == 0:
                    player["loans"].pop(bank_id, None)
                else:
                    player["loans"][bank_id] = remaining
                await save_player(player)
                pv = player_view(player, state)
                bank_name = BANKS[bank_id]["name"]
                await websocket.send_text(json.dumps({
                    "type":   "trade_ok",
                    "msg":    f"Repaid ₹{repay_amt:,} to {bank_name}. {'Fully cleared! ✅' if remaining == 0 else f'₹{int(remaining):,} still owed.'}",
                    "player": pv,
                }))

            # ── Voluntary bankruptcy ───────────────────────────────────────────
            elif action == "declare_bankruptcy":
                if not player:
                    await websocket.send_text(json.dumps({"type": "error", "msg": "Join first."})); continue
                player["cash"]     = BANKRUPTCY_RESTART
                player["holdings"] = {}
                player["loans"]    = {}
                player["bets"]     = {}
                player["avg_cost"] = {}
                player["frozen"]   = False
                await save_player(player)
                pv = player_view(player, state)
                await websocket.send_text(json.dumps({
                    "type":   "bankrupt",
                    "msg":    f"💀 You declared bankruptcy. Wiped clean. Restarting with ₹{BANKRUPTCY_RESTART:,}.",
                    "player": pv,
                }))
                players = await all_players()
                board   = leaderboard(players, state)
                await manager.broadcast_all({
                    "type": "chaos", "event": "bankrupt",
                    "msg":  f"💀 {player['name']} declared voluntary bankruptcy and restarted with ₹{BANKRUPTCY_RESTART:,}!",
                    "board": board,
                })

            # ── Place prediction bet ───────────────────────────────────────────
            elif action == "place_bet":
                if state["phase"] != "trading":
                    await websocket.send_text(json.dumps({"type": "error", "msg": "Bets lock at round start and are only placed during trading."})); continue
                if not player:
                    await websocket.send_text(json.dumps({"type": "error", "msg": "Join first."})); continue
                stock     = msg.get("stock")
                direction = msg.get("direction")   # "up" | "down"
                target    = float(msg.get("target", 0))
                amount    = int(msg.get("amount", 0))
                if stock not in state["companies"]:
                    await websocket.send_text(json.dumps({"type": "error", "msg": "Invalid stock."})); continue
                if direction not in ("up", "down"):
                    await websocket.send_text(json.dumps({"type": "error", "msg": "Direction must be 'up' or 'down'."})); continue
                curr_price = state["companies"][stock]["price"]
                if direction == "up" and target <= curr_price:
                    await websocket.send_text(json.dumps({"type": "error", "msg": f"Target must be above current price ₹{curr_price}."})); continue
                if direction == "down" and target >= curr_price:
                    await websocket.send_text(json.dumps({"type": "error", "msg": f"Target must be below current price ₹{curr_price}."})); continue
                if amount < 1000 or amount > player["cash"]:
                    await websocket.send_text(json.dumps({"type": "error", "msg": f"Bet min ₹1,000 and max ₹{int(player['cash']):,}."})); continue
                # One open bet per stock
                if stock in (player.get("bets") or {}):
                    await websocket.send_text(json.dumps({"type": "error", "msg": "Already have an open bet on this stock."})); continue
                player["cash"] -= amount
                if not isinstance(player.get("bets"), dict):
                    player["bets"] = {}
                player["bets"][stock] = {
                    "direction": direction,
                    "target":    target,
                    "amount":    amount,
                    "locked_at": curr_price,
                }
                await save_player(player)
                pv = player_view(player, state)
                cname = state["companies"][stock]["name"]
                # Broadcast updated sentiment to all players
                players_all = await all_players()
                sentiment   = compute_sentiment(players_all, state["companies"])
                await manager.broadcast_all({"type": "sentiment_update", "sentiment": sentiment})
                await websocket.send_text(json.dumps({
                    "type":   "trade_ok",
                    "msg":    f"Bet ₹{amount:,} on {cname} going {direction.upper()} to ₹{int(target):,}.",
                    "player": pv,
                }))

            # ── Merger initiate ────────────────────────────────────────────────
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
                price  = state["companies"][stock]["price"]
                each   = round(price * qty / 2)
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
                    "bid_id": bid_id, "from": player["name"],
                    "stock": stock, "qty": qty, "each": each,
                })
                await websocket.send_text(json.dumps({"type": "info", "msg": f"Merger request sent to {partner['name']}."}))

            # ── Merger respond ─────────────────────────────────────────────────
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
                p_init = await get_player(bid["from_code"])
                p_resp = await get_player(bid["partner_code"])
                stock  = bid["stock"]
                qty    = bid["qty"]
                each   = bid["each"]
                price  = state["companies"][stock]["price"]
                if p_init["cash"] < each or p_resp["cash"] < each:
                    await websocket.send_text(json.dumps({"type": "error", "msg": "Insufficient funds for merger."})); continue
                p_init["cash"] -= each
                p_resp["cash"] -= each
                old_qty = p_init["holdings"].get(stock, 0)
                old_avg = p_init["avg_cost"].get(stock, price)
                p_init["avg_cost"][stock] = ((old_avg * old_qty + price * qty) / (old_qty + qty)) if old_qty else price
                p_init["holdings"][stock] = old_qty + qty
                await save_player(p_init)
                await save_player(p_resp)
                del state["merge_bids"][bid_id]
                await write_state(state)
                cname = state["companies"][stock]["name"]
                await manager.send_player(bid["from_code"],    {"type": "player_update", "player": player_view(p_init, state)})
                await manager.send_player(bid["partner_code"], {"type": "player_update", "player": player_view(p_resp, state)})
                await manager.send_player(bid["from_code"],    {"type": "info", "msg": f"Merger complete! Bought {qty}× {cname} jointly."})
                await websocket.send_text(json.dumps({"type": "info", "msg": f"Merger complete! {bid['from_name']} got {qty}× {cname}."}))

    except WebSocketDisconnect:
        pass
    finally:
        manager.disconnect_player(code)

# ── WebSocket: host ────────────────────────────────────────────────────────────
@app.websocket("/ws/host")
async def ws_host(websocket: WebSocket):
    await manager.connect_host(websocket)
    try:
        state   = await read_state()
        players = await all_players()
        board   = leaderboard(players, state)
        sentiment = compute_sentiment(players, state["companies"])
        await websocket.send_text(json.dumps({
            "type":         "state_update",
            "state":        state,
            "board":        board,
            "player_count": len([p for p in players if p["name"]]),
            "sentiment":    sentiment,
        }))
        async for raw in websocket.iter_text():
            msg = json.loads(raw)
            if msg.get("type") == "ping":
                state   = await read_state()
                players = await all_players()
                board   = leaderboard(players, state)
                sentiment = compute_sentiment(players, state["companies"])
                await websocket.send_text(json.dumps({
                    "type":         "state_update",
                    "state":        state,
                    "board":        board,
                    "player_count": len([p for p in players if p["name"]]),
                    "sentiment":    sentiment,
                }))
    except WebSocketDisconnect:
        pass
    finally:
        manager.disconnect_host(websocket)