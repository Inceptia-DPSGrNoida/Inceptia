"""
apex20.py — Market Mayhem: the APEX-20 company roster.

Built from companies.docx. Game fields (name / sector / risk / price / bio / trait / ticker) drive the
simulation. `risk` is used ONLY by the host and the engine — players never see it. The dossier (52-week
range, FY23-FY26 financials, price history, policy, international competition) feeds the in-app Guide.

Dividends: only the 8 companies in DIVIDEND_PAYERS have a dividend history. For every other company the
dividend row is dropped from its dossier so the guide never shows a payout that the game will not make.
"""

APEX20 = {
    "zndy": {
        "ticker": "ZNDY", "name": "Zenith Dynamics Ltd.", "sector": "Aerospace & Defense", "risk": "Medium",
        "price": 520, "range52": [410, 565],
        "vol": (0.008, 0.028, 0.46), "dividend": 0, "ipo": False,
        "bio": ("A defence engineering house making radar guidance, counter-drone nodes and UAVs, with 78% of orders tied to public defence budgets. Make-in-India import bans shield it at home, but Western export sanctions on optical chips and delayed titanium shipments can hurt."),
        "trait": "Order book backed by the defence ministry; sanctions are the risk.",
        "dossier": {
            "sector_full": "Aerospace, Precision Ballistics & Defense Engineering",
            "background": "Founded in 1988 as an engineering sub-contractor for the state-run defense sector, Zenith Dynamics transitioned into an autonomous defense supplier in 2008. The company manufactures radar guidance systems, counter-drone interception nodes, unmanned surveillance vehicles (UAVs), and carbon-composite airframe components. It operates two production hubs covering 180 acres in specialized industrial corridors with Level-4 military clearances. It commands a 34% domestic market share in tactical missile actuators and is a Tier-1 contractor for the Ministry of Defense.",
            "financials": {"Gross Revenue (₹ Cr)": [2750.0, 3120.0, 3680.0, 4150.0], "Net Profit / PAT (₹ Cr)": [330.0, 390.0, 485.0, 560.0], "Annual CAPEX/Investments (₹ Cr)": [420.0, 510.0, 640.0, 780.0]},
            "price_history": [["2023", "Traded in a narrow consolidation band of ₹340–₹390."], ["2024", "Broke out to ₹460 following a bilateral export pact with Southeast Asian defense departments."], ["2025", "Reached an all-time high of ₹565 on the back of rising global security budgets, before experiencing a correction to ₹480 triggered by delays in titanium alloy shipments from Eastern Europe."], ["2026", "Stabilized around ₹520. Institutional defense funds hold 62% of free float."]],
            "government_policies": "78% of order flow depends directly on public defense capital budgets. Zenith is a primary beneficiary of \"Make in India\" defense import-ban lists, which shield it from open international competitive bidding.",
            "international_competition": "Vulnerable to Western export sanctions on high-bandwidth optical microchips. Competes against established global contractors like Saab and Thales in neutral export markets (Middle East and ASEAN).",
        },
    },
    "abph": {
        "ticker": "ABPH", "name": "Aura BioPharma Sciences", "sector": "Healthcare", "risk": "Medium-High",
        "price": 340, "range52": [260, 415],
        "vol": (0.012, 0.045, 0.46), "dividend": 0, "ipo": False,
        "bio": ("A specialty API and oncology-biosimilar maker supplying 14 of the world's top 20 generic distributors. Zero-observation FDA audits send it up; an import alert sends it down. Highly volatile around inspection dates."),
        "trait": "Great science, one FDA inspection away from a very bad week.",
        "dossier": {
            "sector_full": "Specialty Active Pharmaceutical Ingredients (APIs) & Biosimilars",
            "background": "Founded in 2004 in Genome Valley, Aura BioPharma spent the last eight years pivoting to high-potency active pharmaceutical ingredients (HPAPIs) and oncology biosimilars. The company supplies bulk APIs to 14 of the world’s top 20 generic drug distributors across North America, Germany, and Brazil. Aura operates four manufacturing facilities, three of which hold US-FDA, UK-MHRA, and EU-GMP certifications.",
            "financials": {"Gross Revenue (₹ Cr)": [2100.0, 2450.0, 2820.0, 3100.0], "Net Profit / PAT (₹ Cr)": [310.0, 340.0, 445.0, 470.0], "Annual CAPEX/Investments (₹ Cr)": [350.0, 480.0, 520.0, 390.0]},
            "price_history": [["2023", "Traded between ₹240 and ₹290 due to pricing pressure in the US oral solid dosage market."], ["2024", "Surged to ₹370 after receiving zero inspection observations from the US-FDA."], ["2025", "Dropped to ₹260 over a two-month period following an unexpected import alert on its secondary fermentation unit in Baddi, followed by a recovery to ₹330."], ["2026", "Trading around ₹340. Highly volatile around regulatory inspection dates."]],
            "government_policies": "Subject to National Pharmaceutical Pricing Authority (NPPA) price caps on essential medicines. Highly dependent on government Production Linked Incentive (PLI) schemes.",
            "international_competition": "Faces intense pricing competition from Chinese fermentation facilities operating with state-subsidized power. Subject to rigorous oversight from the US-FDA.",
        },
    },
    "vtxe": {
        "ticker": "VTXE", "name": "Voltix Energy Technologies", "sector": "Energy & Power", "risk": "Very High",
        "price": 215, "range52": [135, 285],
        "vol": (0.025, 0.075, 0.44), "dividend": 0, "ipo": True,
        "bio": ("A fast-growing maker of solar inverters and LFP battery-storage systems for utilities and data centres. Revenue has tripled in three years but it still pays no dividend and burns cash. Customs duties on imported cells and safety incidents move it hard."),
        "trait": "Newly listed. The highest-beta stock on the exchange.",
        "dossier": {
            "sector_full": "Clean Energy, Battery Storage & Micro-Inverters",
            "background": "Voltix Energy is a high-growth renewable hardware company. It builds utility-grade solar inverters and Lithium Iron Phosphate (LFP) stationary energy storage systems (BESS) for state utilities and data centers. Voltix runs a 3.5 GWh automated pack assembly facility in Gujarat. It imports raw cells under bilateral agreements with South Korean and Taiwanese manufacturers and integrates them with its proprietary battery management software.",
            "financials": {"Gross Revenue (₹ Cr)": [980.0, 1420.0, 2150.0, 2900.0], "Net Profit / PAT (₹ Cr)": [42.0, 88.0, 165.0, 225.0], "Annual CAPEX/Investments (₹ Cr)": [290.0, 450.0, 680.0, 850.0]},
            "price_history": [["2023", "Traded as a small-cap favorite between ₹95 and ₹140. High cash burn depressed institutional interest."], ["2024", "Surged to ₹240 after landing a 500 MWh grid storage tender."], ["2025", "Dropped to ₹135 following a thermal runaway fire at an experimental solar farm, later rallying back to ₹220 as safety clearances were reissued."], ["2026", "Trading around ₹215. One of the highest beta stocks on the exchange."]],
            "government_policies": "Relies directly on renewable energy mandates and custom duty waivers on imported lithium cells. Any increase in basic customs duties (BCD) reduces gross margins.",
            "international_competition": "Faces intense competition from Chinese vertically-integrated storage giants (e.g., CATL, BYD) that sell fully assembled battery storage containers at lower prices.",
        },
    },
    "apmb": {
        "ticker": "APMB", "name": "Apex Mercantile Bank", "sector": "Banking", "risk": "Low",
        "price": 410, "range52": [350, 445],
        "vol": (0.005, 0.018, 0.48), "dividend": 10.0, "ipo": False,
        "bio": ("A 1,150-branch private bank with a 52/48 retail-wholesale loan mix, strong low-cost deposits and GNPA of just 1.95%. Reliable until the central bank changes reserve ratios or foreign investors pull out."),
        "trait": "A defensive index pillar with a very clean loan book.",
        "dossier": {
            "sector_full": "Private Commercial Banking & Financial Services",
            "background": "Apex Mercantile is a domestic commercial bank operating across 1,150 branches. Over the past decade, APMB rebalanced its book to maintain a loan mix of 52% Retail and 48% Wholesale Corporate. The bank holds a strong low-cost deposit franchise. Its Gross Non-Performing Asset (GNPA) ratio is exceptionally healthy at 1.95%.",
            "financials": {"Net Interest Income (₹ Cr)": [4200.0, 4850.0, 5600.0, 6350.0], "Net Profit / PAT (₹ Cr)": [1450.0, 1780.0, 2150.0, 2480.0], "Dividend Per Share (₹)": [6.0, 7.5, 9.0, 10.0], "Annual Branch Expansion (₹ Cr)": [320.0, 390.0, 450.0, 510.0]},
            "price_history": [["2023", "Traded steadily between ₹310 and ₹355. Resilient asset quality shielded the stock."], ["2024", "Advanced to ₹395 as loan book growth reached 18% year-on-year."], ["2025", "Reached a peak of ₹445, before pulling back to ₹380 when the Central Bank raised cash reserve ratios."], ["2026", "Stabilized at ₹410. Regarded as a defensive index pillar."]],
            "government_policies": "Heavily regulated by the Reserve Bank. Exposed to Priority Sector Lending (PSL) requirements, statutory liquidity reserves, and central bank interest rate repo cycles.",
            "international_competition": "Sovereign bond yield fluctuations in the US and Europe trigger foreign institutional investor (FII) capital inflows or outflows, driving swings in bank valuation.",
        },
    },
    "hblx": {
        "ticker": "HBLX", "name": "HarborLogix Infrastructure", "sector": "Transport & Logistics", "risk": "Low",
        "price": 295, "range52": [240, 330],
        "vol": (0.004, 0.015, 0.48), "dividend": 9.5, "ipo": False,
        "bio": ("A port and rail-corridor operator earning 68% of revenue from inflation-linked take-or-pay contracts with shipping alliances. Steady and high-dividend, but exposed to route disruptions and tariff wars."),
        "trait": "Pension-fund favourite. Take-or-pay contracts and fat dividends.",
        "dossier": {
            "sector_full": "Maritime Ports, Rail Corridors & Container Terminals",
            "background": "HarborLogix manages long-term port concessions and dedicated container rail routes. The company is vertically integrated: it handles vessels at deep-water berths, unloads containers, and transfers freight onto its fleet of 45 container rakes. HarborLogix generates 68% of revenues from long-term, inflation-linked \"take-or-pay\" contracts with multinational shipping alliances.",
            "financials": {"Gross Revenue (₹ Cr)": [3100.0, 3450.0, 3920.0, 4300.0], "Net Profit / PAT (₹ Cr)": [720.0, 830.0, 980.0, 1060.0], "Dividend Per Share (₹)": [6.5, 7.5, 9.0, 9.5], "Annual CAPEX/Investments (₹ Cr)": [850.0, 1100.0, 1250.0, 950.0]},
            "price_history": [["2023", "Traded steadily between ₹210 and ₹255. High dividend yields insulated the stock."], ["2024", "Climbed steadily to ₹285 as container volumes rebounded across Asia."], ["2025", "Peaked at ₹330 after acquiring a 30-year operational lease for a chemical terminal."], ["2026", "Trading around ₹295. Substantial dividend payouts make it favored by pension funds."]],
            "government_policies": "Port tariffs are subject to review by the Maritime Regulatory Authority. Infrastructure status provides access to low-cost sovereign bonds.",
            "international_competition": "Vulnerable to shipping route disruptions (e.g., Red Sea lanes) and unilateral tariffs imposed between major global trading blocs.",
        },
    },
    "vrve": {
        "ticker": "VRVE", "name": "Verve Consumer Brands", "sector": "FMCG", "risk": "Low",
        "price": 460, "range52": [385, 495],
        "vol": (0.003, 0.012, 0.49), "dividend": 13.0, "ipo": False,
        "bio": ("A packaged-foods, hygiene and baby-care giant in 4.2 million stores. Asset-light co-manufacturing and a rising dividend make it the classic defensive holding. Weak rural demand and commodity swings are the main worries."),
        "trait": "The anchor. Low beta on purpose.",
        "dossier": {
            "sector_full": "Fast-Moving Consumer Goods (FMCG) & Packaged Foods",
            "background": "Verve Consumer Brands is an established consumer goods company with a direct retail footprint across 4.2 million stores. Its portfolio spans packaged foods, home hygiene, and baby care. Verve maintains an Asset-Light Co-Manufacturing model, outsourcing 40% of standard packaging while keeping proprietary flavoring, fragrance formulation, and brand marketing in-house.",
            "financials": {"Gross Revenue (₹ Cr)": [5400.0, 5950.0, 6600.0, 7250.0], "Net Profit / PAT (₹ Cr)": [610.0, 660.0, 790.0, 920.0], "Dividend Per Share (₹)": [8.5, 9.5, 11.5, 13.0], "Annual CAPEX/Investments (₹ Cr)": [210.0, 250.0, 280.0, 310.0]},
            "price_history": [["2023", "Traded between ₹360 and ₹410. Rural demand slowed due to erratic monsoon patterns."], ["2024", "Rallied to ₹445 as crude palm oil and packaging plastic prices declined."], ["2025", "Moved between ₹420 and ₹495. Strong quick-commerce growth in metropolitan centers countered weak performance in rural areas."], ["2026", "Trading around ₹460. A classic low-beta defensive portfolio anchor."]],
            "government_policies": "Regulated by the Food Safety and Standards Authority (FSSAI). Subject to mandatory front-of-pack nutritional labeling laws and GST adjustments.",
            "international_competition": "Competes with global FMCG conglomerates (Unilever, Nestlé) with massive ad budgets. Sensitive to global agricultural commodity cycles.",
        },
    },
    "krys": {
        "ticker": "KRYS", "name": "Kryos Semi-Conductors Ltd.", "sector": "Technology", "risk": "High",
        "price": 580, "range52": [380, 690],
        "vol": (0.018, 0.06, 0.45), "dividend": 0, "ipo": False,
        "bio": ("A fabless designer of microcontrollers for smart meters, automotive dashboards and motor drives, with 40% share of domestic smart-meter chips. It lives on design wins and policy mandates, and on peace in the Taiwan Strait."),
        "trait": "Fabless chip designer. Government meters up, Taiwan risk down.",
        "dossier": {
            "sector_full": "Fabless Microcontroller Design & IoT Silicon",
            "background": "Kryos designs application-specific integrated circuits (ASICs) used in automotive dashboards, smart electrical meters, and industrial motor drives. Kryos operates an Asset-Light Fabless Architecture: its in-house engineering team designs intellectual property, while physical wafer manufacturing is outsourced to contract foundries in Taiwan and South Korea. Kryos commands a 40% market share in microcontrollers for domestic smart electricity meters.",
            "financials": {"Gross Revenue (₹ Cr)": [820.0, 1180.0, 1640.0, 2100.0], "Net Profit / PAT (₹ Cr)": [145.0, 225.0, 340.0, 440.0], "Annual CAPEX/R&D Inv (₹ Cr)": [180.0, 260.0, 370.0, 490.0]},
            "price_history": [["2023", "Traded around ₹290–₹360 amid a global semiconductor inventory glut."], ["2024", "Surged to ₹510 after the government mandated the deployment of 250 million smart meters."], ["2025", "Reached an all-time high of ₹690 on reports of an automotive design win with a European automaker, before falling to ₹480 due to Taiwan geopolitical tensions."], ["2026", "Stabilized at ₹580. High price volatility driven by tech valuations."]],
            "government_policies": "Beneficiary of the National Semiconductor Mission which subsidizes up to 50% of qualifying design software and tape-out tooling expenses.",
            "international_competition": "Vulnerable to disruption in the Taiwan Strait. Changes in US-China semiconductor export restrictions can limit access to advanced design software.",
        },
    },
    "trfm": {
        "ticker": "TRFM", "name": "TerraFirm Cement & Materials", "sector": "Materials", "risk": "Medium",
        "price": 180, "range52": [130, 215],
        "vol": (0.01, 0.035, 0.47), "dividend": 0, "ipo": False,
        "bio": ("An 18.5 MT cement maker with captive limestone and 70 MW of captive power. Highway and housing outlays lift it; coal prices and imported-slag tariffs squeeze it. Takeover chatter has surfaced before."),
        "trait": "Cyclical cement play tied to public infrastructure spending.",
        "dossier": {
            "sector_full": "Basic Materials & Heavy Building Cement",
            "background": "TerraFirm Cement operates six clinker and grinding facilities with a capacity of 18.5 Million Tonnes. The company holds captive limestone mining leases with 35 years of reserves. TerraFirm maintains a network of 48 warehouses and operates 70 MW of captive thermal and waste-heat recovery power plants to protect margins against grid electricity price spikes.",
            "financials": {"Gross Revenue (₹ Cr)": [3800.0, 4200.0, 4650.0, 5100.0], "Net Profit / PAT (₹ Cr)": [280.0, 240.0, 360.0, 410.0], "Annual CAPEX/Investments (₹ Cr)": [620.0, 750.0, 510.0, 480.0]},
            "price_history": [["2023", "Traded down from ₹175 to ₹130 as imported coal prices reached historic highs."], ["2024", "Rebounded to ₹165 as the central government increased highway construction outlays."], ["2025", "Rallied to ₹215 on rumors of an acquisition bid by an international conglomerate, later settling back to ₹170."], ["2026", "Trading around ₹180. Follows cyclical patterns tied to public infrastructure spending."]],
            "government_policies": "Closely monitored by the Competition Commission for price-fixing. Directly benefits from national road construction and affordable housing initiatives.",
            "international_competition": "Exposed to swings in international sea-borne thermal coal prices and imported slag tariffs.",
        },
    },
    "nvst": {
        "ticker": "NVST", "name": "NovaSteel Alloys", "sector": "Materials", "risk": "Medium-High",
        "price": 310, "range52": [250, 345],
        "vol": (0.011, 0.04, 0.47), "dividend": 0, "ipo": False,
        "bio": ("A specialty cold-rolled steel producer for auto chassis and appliances, with captive iron ore covering 40% of needs and a green-steel push. Highly cyclical, and perpetually threatened by cheap imports."),
        "trait": "High-margin auto steel, at the mercy of coking coal and dumping.",
        "dossier": {
            "sector_full": "Specialty Metallurgy & Cold-Rolled Auto Steel",
            "background": "NovaSteel produces high-margin, cold-rolled specialty steel used in automotive chassis and appliance manufacturing. It operates two modernized blast furnaces and holds captive iron ore leases that fulfill 40% of its raw material needs, heavily investing in green-steel electric arc furnaces.",
            "financials": {"Gross Revenue (₹ Cr)": [3900.0, 4350.0, 4800.0, 5250.0], "Net Profit / PAT (₹ Cr)": [220.0, 290.0, 410.0, 465.0], "Annual CAPEX/Investments (₹ Cr)": [780.0, 650.0, 520.0, 810.0]},
            "price_history": [["2023", "Traded around ₹250 as supply chain bottlenecks inflated logistics costs."], ["2024", "Rallied to ₹330 on the back of a domestic auto manufacturing boom."], ["2025", "Dropped to ₹290 when global coking coal prices spiked."], ["2026", "Stabilized at ₹310. A highly cyclical stock."]],
            "government_policies": "Protected by domestic Minimum Import Price (MIP) floors and infrastructure quotas. Sensitive to mining royalty tax hikes.",
            "international_competition": "Faces constant threat of \"dumping\" (selling below cost) from state-subsidized Chinese and Vietnamese mega-mills.",
        },
    },
    "qntx": {
        "ticker": "QNTX", "name": "Quantix Cloud Systems", "sector": "Technology", "risk": "High",
        "price": 620, "range52": [450, 710],
        "vol": (0.016, 0.055, 0.45), "dividend": 0, "ipo": False,
        "bio": ("An enterprise SaaS and zero-trust cybersecurity company with a 32% operating margin and an entirely subscription-based model. It reacts violently to missed guidance, global tech earnings and interest-rate shifts."),
        "trait": "Recurring revenue, ₹850 Cr of cash, zero patience for a miss.",
        "dossier": {
            "sector_full": "Enterprise SaaS & Cybersecurity",
            "background": "Quantix provides scalable cloud infrastructure, machine-learning data analytics, and zero-trust cybersecurity frameworks. It operates entirely on a subscription-based recurring revenue model. With zero physical manufacturing constraints, Quantix boasts a massive 32% operating margin and holds ₹850 Crore in cash reserves.",
            "financials": {"Gross Revenue (₹ Cr)": [1100.0, 1480.0, 1950.0, 2520.0], "Net Profit / PAT (₹ Cr)": [180.0, 275.0, 420.0, 560.0], "Annual R&D Investments (₹ Cr)": [310.0, 450.0, 580.0, 720.0]},
            "price_history": [["2023", "Valued at ₹450 during a broad tech-sector correction."], ["2024", "Surged to ₹710 as enterprise AI adoption created massive demand for its APIs."], ["2025", "Corrected to ₹580 after missing quarterly revenue guidance by 2%."], ["2026", "Trading at ₹620. Reacts aggressively to global tech earnings and interest rate shifts."]],
            "government_policies": "Exposed to sovereign Data Localization Laws and Digital Personal Data Protection Acts, which carry massive fines for breaches.",
            "international_competition": "Competes for contracts against global titans like AWS, Microsoft Azure, and CrowdStrike. Highly sensitive to US H-1B visa restrictions.",
        },
    },
    "prma": {
        "ticker": "PRMA", "name": "Primus AutoWorks", "sector": "Automobile", "risk": "High",
        "price": 390, "range52": [210, 420],
        "vol": (0.016, 0.055, 0.44), "dividend": 0, "ipo": False,
        "bio": ("A commercial-EV maker with 45% of state-procured electric buses and its own local chassis plant. Profits are scaling fast, but it depends on EV subsidies and imported lithium cells."),
        "trait": "Electric buses and vans. Subsidies and lithium prices decide everything.",
        "dossier": {
            "sector_full": "Electric Commercial Fleets & Heavy Vehicles",
            "background": "Primus executed a successful pivot to commercial electric vehicles (EVs) in 2018. It specializes in electric municipal buses, light urban cargo vans, and hybrid powertrains, securing a 45% market share in state-procured electric buses. It relies on imported lithium cells but manufactures its own modular chassis locally.",
            "financials": {"Gross Revenue (₹ Cr)": [3800.0, 4600.0, 5200.0, 6100.0], "Net Profit / PAT (₹ Cr)": [110.0, 185.0, 310.0, 440.0], "Annual CAPEX/Investments (₹ Cr)": [820.0, 950.0, 1100.0, 1250.0]},
            "price_history": [["2023", "Languished at ₹210 under heavy R&D debt."], ["2024", "Climbed to ₹340 as state transport boards mass-retired diesel fleets."], ["2025", "Reached ₹420 after testing a solid-state battery prototype."], ["2026", "Consolidating at ₹390. Tied to green-energy subsidies and lithium spot prices."]],
            "government_policies": "Survival depends heavily on government EV subsidy schemes and vehicle scrappage policies.",
            "international_competition": "Total reliance on China and South Korea for raw battery cells makes its supply chain highly vulnerable to geopolitical trade wars.",
        },
    },
    "gltl": {
        "ticker": "GLTL", "name": "Glotech Telecom Ltd.", "sector": "Telecom", "risk": "Medium-High",
        "price": 270, "range52": [180, 295],
        "vol": (0.01, 0.038, 0.46), "dividend": 6.2, "ipo": False,
        "bio": ("A deep-fibre and tower operator leasing capacity to 5G carriers on long lock-in contracts. Predictable cash flows, but heavy debt makes it sensitive to rates, regulator rulings and equipment bans."),
        "trait": "Dark fibre and towers, carrying a spectrum-sized debt pile.",
        "dossier": {
            "sector_full": "5G Optical Fiber Infrastructure & Telecom Towers",
            "background": "Glotech lays deep underground dark fiber networks and builds telecom transmission towers, leasing bandwidth to consumer 5G operators. Operating under an intensely capital-heavy model, it carries massive debt from spectrum auctions, but its long-term lock-in contracts generate highly predictable cash flows.",
            "financials": {"Gross Revenue (₹ Cr)": [4800.0, 5350.0, 6100.0, 6750.0], "Net Profit / PAT (₹ Cr)": [210.0, 340.0, 480.0, 550.0], "Dividend Per Share (₹)": [4.0, 4.8, 5.4, 6.2], "Annual CAPEX/Investments (₹ Cr)": [1200.0, 1400.0, 1150.0, 950.0]},
            "price_history": [["2023", "Crashed to ₹180 under severe spectrum debt and interest rate hikes."], ["2024", "Recovered to ₹250 as 5G rollouts forced operators to lease heavily from its grid."], ["2025", "Peaked at ₹295 following a favorable court ruling on historic tax dues."], ["2026", "Trading at ₹270. Sensitive to Central Bank interest rates due to its debt pile."]],
            "government_policies": "Strictly controlled by the Telecom Regulatory Authority (TRAI). Spectrum pricing and historic tax demands dictate its survival.",
            "international_competition": "Bans on cheap Chinese telecom hardware (Huawei/ZTE) force Glotech to buy more expensive European routing equipment, squeezing margins.",
        },
    },
    "urbn": {
        "ticker": "URBN", "name": "UrbanGrid Power Utility", "sector": "Energy & Power", "risk": "Low",
        "price": 245, "range52": [205, 265],
        "vol": (0.003, 0.012, 0.49), "dividend": 10.5, "ipo": False,
        "bio": ("A privatised grid operator serving three metro zones as a legal monopoly with a regulated 15.5% ROE. It pays the highest dividend yield on the exchange; tariff delays and ESG selling of coal assets are the risks."),
        "trait": "The cash cow. A regulated monopoly paying the top dividend yield.",
        "dossier": {
            "sector_full": "Thermal & Hydro Power Distribution",
            "background": "UrbanGrid is a privatized state grid operator managing electricity distribution for three metropolitan zones via a mix of aging coal-fired plants and hydroelectric dams. Operating as a legal monopoly, it guarantees a regulated Return on Equity (ROE) of 15.5%. It is a cash cow paying the highest dividend yield on the exchange.",
            "financials": {"Gross Revenue (₹ Cr)": [3800.0, 4100.0, 4400.0, 4650.0], "Net Profit / PAT (₹ Cr)": [420.0, 460.0, 510.0, 545.0], "Dividend Per Share (₹)": [8.5, 9.3, 10.0, 10.5], "Annual CAPEX/Investments (₹ Cr)": [410.0, 450.0, 390.0, 420.0]},
            "price_history": [["2023", "Steady at ₹220, ignoring tech crashes."], ["2024", "Crept up to ₹235 as urban power demand hit record highs during heatwaves."], ["2025", "Reached ₹260 after acquiring a struggling neighboring municipal grid."], ["2026", "Trading at ₹245. Moves almost entirely based on dividend announcements."]],
            "government_policies": "Tariffs are completely controlled by the State Electricity Regulatory Commission. Political delays in tariff hikes force the company to absorb cost increases.",
            "international_competition": "Faces institutional selling pressure from foreign ESG funds refusing to hold companies with coal-fired thermal generation assets.",
        },
    },
    "slra": {
        "ticker": "SLRA", "name": "Solaris Agrochemicals", "sector": "Agriculture", "risk": "Medium-High",
        "price": 365, "range52": [295, 410],
        "vol": (0.01, 0.038, 0.46), "dividend": 0, "ipo": False,
        "bio": ("A fertiliser and crop-protection maker whose year depends on monsoon timing. Urea prices are capped with subsidy payouts that can run late, and EU bans threaten 18% of its export revenue."),
        "trait": "Trades on the monsoon and on natural gas.",
        "dossier": {
            "sector_full": "Fertilizers, Herbicides & Crop Protection",
            "background": "Solaris manufactures synthetic urea, complex NPK fertilizers, and patented crop-protection chemicals. The company’s business is intensely seasonal, relying entirely on the timing of the annual monsoon. Solaris has expanded its export footprint to Latin America and Africa to offset domestic seasonality.",
            "financials": {"Gross Revenue (₹ Cr)": [2300.0, 2650.0, 2900.0, 3350.0], "Net Profit / PAT (₹ Cr)": [180.0, 240.0, 295.0, 360.0], "Annual CAPEX/Investments (₹ Cr)": [320.0, 280.0, 410.0, 360.0]},
            "price_history": [["2023", "Traded at ₹310 after an erratic monsoon suppressed rural fertilizer spraying."], ["2024", "Spiked to ₹400 as a global fertilizer shortage boosted export margins."], ["2025", "Fell to ₹350 when global natural gas prices stabilized."], ["2026", "Trading at ₹365. Trades purely on meteorological forecasts and natural gas prices."]],
            "government_policies": "Domestic urea pricing is strictly capped; the government pays the difference via Direct Benefit Transfer (DBT) subsidies. Delays in payouts drain working capital.",
            "international_competition": "Changing environmental laws in the EU threaten to ban key insecticide molecules that make up 18% of Solaris’s export revenue.",
        },
    },
    "medv": {
        "ticker": "MEDV", "name": "MedVantage Hospitals", "sector": "Healthcare", "risk": "Medium",
        "price": 490, "range52": [380, 540],
        "vol": (0.006, 0.022, 0.47), "dividend": 0, "ipo": False,
        "bio": ("22 quaternary-care hospitals focused on oncology, transplants and cardiology, with 28% of revenue from medical tourism. Price caps on stents and ICU beds are the main regulatory risk."),
        "trait": "High-end hospitals and medical tourism. Defensive with a growth kicker.",
        "dossier": {
            "sector_full": "Multi-Specialty Healthcare Chains & Medical Tourism",
            "background": "Operating 22 high-end quaternary care hospitals, MedVantage focuses on high-margin procedures: oncology, organ transplants, and advanced cardiology. MedVantage derives 28% of its revenue from lucrative Medical Tourism, treating patients flying in for world-class surgeries at a fraction of Western costs.",
            "financials": {"Gross Revenue (₹ Cr)": [2500.0, 2850.0, 3250.0, 3700.0], "Net Profit / PAT (₹ Cr)": [210.0, 290.0, 390.0, 460.0], "Annual CAPEX/Investments (₹ Cr)": [450.0, 620.0, 750.0, 580.0]},
            "price_history": [["2023", "Traded at ₹390 as routine elective surgeries rebounded post-pandemic."], ["2024", "Rose to ₹430 upon completion of two new oncology centers."], ["2025", "Reached an all-time high of ₹520 as medical tourism volumes surged."], ["2026", "Trading at ₹490. A defensive stock that grows steadily with private medical insurance penetration."]],
            "government_policies": "Vulnerable to populist government price caps on essential medical devices (cardiac stents) and regulatory limits on private ICU bed pricing.",
            "international_competition": "Faces intense competition for global medical tourists from aggressively marketed hospital chains in Thailand, Malaysia, and Singapore.",
        },
    },
    "nxgn": {
        "ticker": "NXGN", "name": "NextGen Retail Malls", "sector": "Real Estate", "risk": "Medium",
        "price": 330, "range52": [260, 360],
        "vol": (0.006, 0.024, 0.47), "dividend": 14.0, "ipo": False,
        "bio": ("A REIT owning 12 premium malls in Tier-1 cities, earning fixed rent plus a share of tenant sales, with 45% of space given to food and experiences. Rate hikes make its distributions less attractive versus bonds."),
        "trait": "A mall REIT that moves inversely to interest rates.",
        "dossier": {
            "sector_full": "Commercial Retail Real Estate & REIT",
            "background": "Structured as a REIT, NextGen owns 12 ultra-premium mega-malls in Tier-1 cities. It profits from fixed base rent plus a percentage of tenant sales revenue. NextGen dedicates 45% of its floor space to food, beverage, and experiential entertainment which cannot be replicated by e-commerce.",
            "financials": {"Gross Revenue (Rentals ₹ Cr)": [1200.0, 1450.0, 1650.0, 1880.0], "Net Operating Income (₹ Cr)": [780.0, 960.0, 1120.0, 1310.0], "Distribution Per Unit (₹)": [9.5, 11.0, 12.5, 14.0], "Annual CAPEX/Investments (₹ Cr)": [210.0, 350.0, 420.0, 300.0]},
            "price_history": [["2023", "Recovered from ₹260 to ₹290 as physical retail footfall returned."], ["2024", "Climbed to ₹310 as luxury global brands expanded physical footprints."], ["2025", "Peaked at ₹360 before a sudden central bank interest rate hike lowered its dividend attractiveness compared to safe bonds."], ["2026", "Trading at ₹330. Moves inversely to interest rates."]],
            "government_policies": "Vulnerable to zoning law changes, municipal property tax hikes, and central bank interest rate cycles which dictate debt refinancing costs.",
            "international_competition": "Changes in Foreign Direct Investment (FDI) rules for multi-brand retail dictate whether global anchors can lease space. Constantly threatened by global e-commerce giants.",
        },
    },
    "ocna": {
        "ticker": "OCNA", "name": "OceanAir Cargo Express", "sector": "Transport & Logistics", "risk": "Medium-High",
        "price": 425, "range52": [350, 510],
        "vol": (0.012, 0.042, 0.46), "dividend": 0, "ipo": False,
        "bio": ("A freighter airline dominating pharma cold chain and next-day e-commerce. Fuel prices and slot fees set its margins; shipping choke-point crises send cargo its way."),
        "trait": "A direct proxy for global trade. Chaos at sea helps it.",
        "dossier": {
            "sector_full": "Scheduled Air Cargo & Pharma Cold Chain",
            "background": "OceanAir operates a dedicated fleet of converted Boeing freighters. It dominates pharmaceutical cold-chain transport and guaranteed next-day e-commerce delivery. Because it flies cargo rather than passengers, its routing is highly flexible, but profit margins are entirely at the mercy of global jet fuel prices.",
            "financials": {"Gross Revenue (₹ Cr)": [2800.0, 3150.0, 3600.0, 4050.0], "Net Profit / PAT (₹ Cr)": [190.0, 260.0, 320.0, 375.0], "Annual CAPEX/Investments (₹ Cr)": [550.0, 680.0, 420.0, 850.0]},
            "price_history": [["2023", "Peaked at ₹500 during global ocean shipping bottlenecks forcing air freight usage."], ["2024", "Dropped back to ₹410 as ocean shipping normalized."], ["2025", "Rebounded to ₹450 after securing exclusive e-commerce logistics contracts."], ["2026", "Trading at ₹425. Acts as a direct proxy for global trade health."]],
            "government_policies": "Highly impacted by Aviation Turbine Fuel (ATF) excise taxes and exorbitant airport landing/parking slot fees.",
            "international_competition": "Benefits from geopolitical chaos; when maritime choke points face military threats, companies panic and shift high-value cargo to OceanAir. Competes with DHL and FedEx.",
        },
    },
    "flxw": {
        "ticker": "FLXW", "name": "FlexWare Textiles & Polymers", "sector": "Textiles & Polymers", "risk": "Medium-High",
        "price": 225, "range52": [150, 255],
        "vol": (0.01, 0.038, 0.47), "dividend": 5.62, "ipo": False,
        "bio": ("A maker of technical textiles and engineered packaging that exports 45% of output and uses crude derivatives as raw material. It depends on crude prices, plastic regulation and anti-dumping enforcement."),
        "trait": "Volume-driven commodity stock riding crude oil.",
        "dossier": {
            "sector_full": "Technical Synthetic Fabrics & Engineered Packaging",
            "background": "FlexWare manufactures ultra-durable technical textiles like geo-textiles used beneath highways and heavy-duty polymer packaging. Operating on razor-thin margins but massive volumes, FlexWare exports 45% of its output. The company uses crude oil derivatives as its primary raw material.",
            "financials": {"Gross Revenue (₹ Cr)": [1500.0, 1800.0, 2100.0, 2350.0], "Net Profit / PAT (₹ Cr)": [70.0, 110.0, 160.0, 195.0], "Dividend Per Share (₹)": [4.05, 4.5, 4.95, 5.62], "Annual CAPEX/Investments (₹ Cr)": [210.0, 180.0, 240.0, 150.0]},
            "price_history": [["2023", "Struggled at ₹160 due to high crude oil prices inflating raw material costs."], ["2024", "Rallied to ₹240 as crude stabilized and highway construction orders surged."], ["2025", "Dipped to ₹200 amid a labor strike at its primary weaving facility."], ["2026", "Trading at ₹225. A volume-driven commodity stock."]],
            "government_policies": "Sensitive to bans on single-use plastics. Dependent on government export incentives and currency devaluation.",
            "international_competition": "Faces brutal price wars from state-subsidized textile mills in Bangladesh and Vietnam. Relies on the EU enforcing anti-dumping laws.",
        },
    },
    "orbt": {
        "ticker": "ORBT", "name": "Orbit Aerospace Sensors", "sector": "Aerospace & Defense", "risk": "Very High",
        "price": 550, "range52": [280, 630],
        "vol": (0.025, 0.075, 0.43), "dividend": 0, "ipo": True,
        "bio": ("A micro-satellite company selling radar and optical imagery by subscription to farms, shippers and defence agencies. Revenue is exploding, but it depends on third-party launches and on government permission to sell."),
        "trait": "Newly listed. Every rocket launch is a coin-flip on its price.",
        "dossier": {
            "sector_full": "Commercial Satellites & Space Data Imagery",
            "background": "Orbit Aerospace builds micro-satellites equipped with Synthetic Aperture Radar (SAR) and high-resolution cameras that see through clouds and operate at night. It sells subscription-based imagery to agricultural firms, maritime logistics trackers, and sovereign defense agencies, relying on third-party rockets for launches.",
            "financials": {"Gross Revenue (₹ Cr)": [220.0, 450.0, 750.0, 1120.0], "Net Profit / PAT (₹ Cr)": [-40.0, 65.0, 185.0, 310.0], "Annual R&D Investments (₹ Cr)": [190.0, 380.0, 540.0, 810.0]},
            "price_history": [["2023", "Traded wildly around ₹300 on speculative R&D success."], ["2024", "Surged to ₹480 after successfully deploying its first 12-satellite constellation."], ["2025", "Peaked at ₹630 after securing a massive defense data contract."], ["2026", "Trading at ₹550. Prone to massive price swings based on rocket launch success rates."]],
            "government_policies": "Operates under extreme scrutiny from the Ministry of Defense. National Space Privatization policies dictate who they can sell imagery to, occasionally blocking foreign contracts.",
            "international_competition": "Faces intense competition from global players like Planet Labs. Relies on SpaceX and state-run agencies for ride-share launches.",
        },
    },
    "aqua": {
        "ticker": "AQUA", "name": "AquaPure Environmental", "sector": "Water & Environment", "risk": "Medium",
        "price": 270, "range52": [190, 310],
        "vol": (0.006, 0.022, 0.47), "dividend": 5.67, "ipo": False,
        "bio": ("A builder and operator of zero-liquid-discharge plants and desalination works with a ₹3,400 Cr order book. Environmental enforcement drives demand, while municipal payment delays and imported membranes drive the risk."),
        "trait": "Policy-driven order book. Slow payers, steady demand.",
        "dossier": {
            "sector_full": "Industrial Water Recycling & Desalination EPC",
            "background": "AquaPure designs, builds, and operates Zero-Liquid-Discharge (ZLD) effluent treatment plants for highly polluting industries (textiles, chemicals) and coastal seawater desalination plants. It maintains an Engineering, Procurement, and Construction (EPC) order book exceeding ₹3,400 Crore, giving it years of revenue visibility.",
            "financials": {"Gross Revenue (₹ Cr)": [950.0, 1180.0, 1450.0, 1720.0], "Net Profit / PAT (₹ Cr)": [85.0, 115.0, 155.0, 195.0], "Dividend Per Share (₹)": [3.78, 4.32, 5.13, 5.67], "Annual CAPEX/Investments (₹ Cr)": [150.0, 210.0, 280.0, 310.0]},
            "price_history": [["2023", "Languished at ₹190 due to delays in municipal payments."], ["2024", "Climbed to ₹220 as ESG mandates forced factories to invest in water recycling."], ["2025", "Rallied to ₹310 after winning a municipal desalination tender."], ["2026", "Trading at ₹270. A steady, policy-driven defensive stock."]],
            "government_policies": "Survival is dependent on the strictness of the National Green Tribunal. Municipal budget deficits frequently delay their EPC payments.",
            "international_competition": "Highly reliant on reverse-osmosis membrane technology patented by global water-tech firms; currency fluctuations make importing these membranes expensive.",
        },
    },
}


GAME_FIELDS = ("ticker", "name", "sector", "risk", "price", "bio", "trait")

def _public(c):
    d = {k: c[k] for k in GAME_FIELDS}
    d["range52"] = c["range52"]
    return d

BASE_COMPANIES = {k: _public(c) for k, c in APEX20.items() if not c["ipo"]}   # 18 — trade from Round 1
IPO_COMPANIES  = {k: _public(c) for k, c in APEX20.items() if c["ipo"]}       # 2, from DIFFERENT sectors — unlisted until the IPO Drop event

SECTORS = {}
for _k, _c in APEX20.items():
    SECTORS.setdefault(_c["sector"], []).append(_k)

COMPANY_VOL        = {k: c["vol"] for k, c in APEX20.items()}
PRICE_FLOORS       = {k: round(c["price"] * 0.20) for k, c in APEX20.items()}     # 20% of starting price
DIVIDEND_PER_SHARE = {k: c["dividend"] for k, c in APEX20.items() if c["dividend"] > 0}   # the 8 payers only
ACQUISITION_PAIR   = ("qntx", "gltl")      # different sectors (Technology / Telecom)
HIGH_VOL           = (0.018, 0.060, 0.45)  # the "High" profile both acquisition stocks are bumped up to

assert len(DIVIDEND_PER_SHARE) == 8
assert len({APEX20[k]["sector"] for k in IPO_COMPANIES}) == len(IPO_COMPANIES), "IPO companies must be in different sectors"
assert APEX20[ACQUISITION_PAIR[0]]["sector"] != APEX20[ACQUISITION_PAIR[1]]["sector"]

# Public guide data (sent to players only for companies that are currently listed).
GUIDE = {k: {"ticker": c["ticker"], "name": c["name"], "sector": c["sector"], "range52": c["range52"], "price": c["price"],
             "pays_dividend": c["dividend"] > 0, **c["dossier"]} for k, c in APEX20.items()}

# Host-only: same data plus the engine settings.
DOSSIER = {k: {**GUIDE[k], "risk": c["risk"], "price": c["price"], "dividend": c["dividend"]} for k, c in APEX20.items()}


# ── Company mergers: ON HOLD. The curated pairs are kept here so the feature can be revived later;
#    nothing in the game reads this and the host panel has no merger option. ──
MERGER_PAIRS_ON_HOLD = {
    "gltl|qntx": {
        "name": "Quantix Glotech Networks", "sector": "Technology", "risk": "High",
        "bio": ("Quantix's cloud and zero-trust security stack merged with Glotech's fibre and tower network — "
                "the pitch is a vertically integrated digital backbone, from the physical network up to the "
                "software running on it. One combined balance sheet, with Glotech's debt now attached."),
        "trait": "The network and the cloud on top of it.",
    },
    "prma|vtxe": {
        "name": "Primus Voltix Mobility", "sector": "Automobile", "risk": "Very High",
        "bio": ("Primus's electric buses and vans combined with Voltix's battery-storage and pack-assembly "
                "capability, aimed at owning the cell-to-chassis chain both companies currently buy from abroad. "
                "Also now carries both companies' lithium and subsidy exposure in one stock."),
        "trait": "Builds the bus and the battery inside it.",
    },
    "orbt|zndy": {
        "name": "Zenith Orbit Defence Systems", "sector": "Aerospace & Defense", "risk": "High",
        "bio": ("Zenith's guidance and UAV hardware paired with Orbit's radar and optical satellites — "
                "sovereign-grade sensing from the ground to orbit, sold to one customer: defence ministries. "
                "Licensing and sanctions risk now sits on both halves."),
        "trait": "Defence hardware with eyes in orbit.",
    },
    "hblx|ocna": {
        "name": "HarborLogix OceanAir Global Logistics", "sector": "Transport & Logistics", "risk": "Medium",
        "bio": ("Ports and rail corridors combined with a dedicated air-cargo fleet — sea, rail and air freight "
                "under one contract. Smooths out the old pattern where one half gained when the other suffered "
                "from shipping-lane disruptions."),
        "trait": "Sea, rail and air in one booking.",
    },
    "abph|medv": {
        "name": "Aura MedVantage Healthcare", "sector": "Healthcare", "risk": "Medium",
        "bio": ("Aura BioPharma's specialty drug manufacturing joined to MedVantage's quaternary-care hospital "
                "chain — oncology from molecule to bedside. Regulatory risk now spans both FDA inspections and "
                "domestic price caps."),
        "trait": "Oncology, from the plant to the ward.",
    },
    "nvst|trfm": {
        "name": "TerraFirm NovaSteel Materials", "sector": "Materials", "risk": "Medium-High",
        "bio": ("Cement and specialty steel under one roof, sharing captive power, logistics and a customer base in "
                "infrastructure and construction. Both halves are cyclical and both are exposed to coal prices."),
        "trait": "The raw materials of every build.",
    },
}
