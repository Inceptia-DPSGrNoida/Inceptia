"""
news_presets.py — Market Mayhem

Ready-made headline text for the host's manual "Inject News" tab, organised by
stock id and direction ("up" / "down"). main.py's /api/host/inject_news picks
one at random when the host leaves the text box blank.

Every headline is grounded in the organiser dossier (fictional_stock_exchange_dossiers.docx):
real plot threads, company history and "watch-list hooks" only — nothing here
contradicts the established backstory.

Separate from NEWS_POOL in main.py (the automatic round-start headlines, which
never repeat within a game). This file can repeat across a session.

ORGANISER_NOTES at the bottom is HOST-ONLY: it's served by a password-protected
endpoint and is never sent to players.
"""

NEWS_PRESETS = {

    # ── NEXUS TECHNOLOGIES (IT / Software Services) ─────────────────────
    "nexus": {
        "up": [
            "Nexus Technologies wins a fresh multi-year AI-modernisation contract from a large US client.",
            "Nexus upgrades FY27 revenue guidance, citing strong demand for enterprise AI integration.",
            "Rupee weakens against the dollar — analysts expect a margin tailwind for Nexus's domestic-cost base.",
            "Nexus's AI Delivery Center in Pune gets a green light for expansion.",
            "Brokerages raise Nexus's target price after another quarter of double-digit deal-win growth.",
            "Nexus's cybersecurity arm, acquired in 2025, lands its first marquee banking client.",
            "US client budgets for IT modernisation come in stronger than feared, lifting the whole mid-tier IT pack.",
            "Nexus's DPDP-compliance advisory line signs a dozen large Indian enterprises in a single quarter.",
            "Nexus reportedly in talks to bid for a mid-sized European IT firm; market reads it as growth intent.",
            "Nexus is cleared in the US visa-compliance review with no further penalties.",
        ],
        "down": [
            "US lawmakers revive 'hire local' proposals aimed at outsourced IT contracts; Nexus most exposed among mid-tier names.",
            "A large US insurance client trims discretionary tech spend, pushing back part of Nexus's AI project.",
            "Rupee strengthens sharply, raising fears of margin pressure at Nexus.",
            "Nexus's effective tax rate creeps higher as remaining IT-SEZ benefits expire.",
            "Rival mid-tier IT firm undercuts Nexus on a major deal, snatching a contract it was expected to win.",
            "Nexus's AI Delivery Center expansion is deferred, raising questions on the AI-first strategy.",
            "Key Nexus executives depart for a global consulting major, reviving succession worries.",
            "Analysts warn integration costs of Nexus's US cybersecurity acquisition may weigh on next quarter.",
            "A fresh whistleblower complaint on visa compliance surfaces; Nexus says it is reviewing the claims.",
            "Global tech sell-off dents IT valuations; Nexus falls with the sector.",
        ],
    },

    # ── PIONEER TRUST BANK (Private Banking) ────────────────────────────
    "pioneer": {
        "up": [
            "Pioneer Trust Bank's digital lending book grows faster than expected; credit-rating outlook improves.",
            "RBI clears Pioneer's digital lending partnerships after a routine review.",
            "Pioneer reports a fall in gross NPAs as the merged regional bank's loan book keeps improving.",
            "Government credit-guarantee scheme boosts demand for Pioneer's SME loans.",
            "Pioneer's CASA ratio improves, cutting its funding costs versus peers.",
            "Pioneer is said to be eyeing a bolt-on acquisition of a small NBFC — the market likes the consolidator story.",
            "Pioneer announces a capital raise at a premium, signalling confidence in growth.",
            "A rate-hike cycle expectation lifts net-interest-margin forecasts for banks like Pioneer.",
            "Pioneer's vehicle and small-business NBFC arm posts record disbursements.",
            "Pioneer declares a higher dividend after its strongest profit in years.",
        ],
        "down": [
            "RBI opens a review of Pioneer's digital-lending partnerships, citing customer-protection concerns.",
            "Pioneer reports a jump in provisioning on inherited loans from the merged regional bank.",
            "RBI cuts the repo rate; analysts flag near-term margin compression for Pioneer.",
            "Stricter unsecured-lending norms slow Pioneer's personal-loan growth again.",
            "Pioneer's capital-raise plan raises dilution fears among shareholders.",
            "A large SME borrower defaults, hitting Pioneer's asset-quality numbers.",
            "Global fintech-backed lenders undercut Pioneer's rates in unsecured retail lending.",
            "Reports that Pioneer overpaid for a small NBFC target unsettle investors.",
            "Deposit growth slows for Pioneer as rivals raise fixed-deposit rates.",
            "Pioneer flags higher-than-expected integration costs on its digital banking upgrade.",
        ],
    },

    # ── GENESIS LIFE SCIENCES (Pharmaceuticals) ─────────────────────────
    "genesis": {
        "up": [
            "USFDA clears Genesis's third manufacturing facility after a clean re-inspection.",
            "Genesis wins early US launch of a high-margin generic after a patent ruling in its favour.",
            "Genesis's new vaccine facility wins large contract-manufacturing orders.",
            "Genesis signs an in-licensing deal for a promising biosimilar, widening its specialty pipeline.",
            "Arbitration panel rules in Genesis's favour in its African government supply dispute.",
            "Genesis reports strong US generic sales as a competitor exits a key product line.",
            "Genesis's dividend yield climbs as management signals a higher payout.",
            "Global vaccine demand surges; Genesis's contract capacity is seen as a major beneficiary.",
            "Genesis clears remaining remediation items at both previously flagged plants.",
            "Analysts upgrade Genesis, saying quality-control worries are firmly in the past.",
        ],
        "down": [
            "USFDA issues a fresh observation at a Genesis facility during a re-inspection.",
            "Genesis receives a warning letter over manufacturing-quality lapses; US exports from that plant halted.",
            "A patent ruling goes against Genesis, delaying a planned US launch.",
            "Arbitration over an African government supply contract turns against Genesis.",
            "US generic pricing pressure squeezes Genesis's margins this quarter.",
            "Genesis's biosimilar in-licensing talks collapse over terms.",
            "A batch recall of a Genesis formulation triggers fresh quality-control worries.",
            "Genesis's new vaccine facility faces a commissioning delay.",
            "Rival generics maker launches a cheaper version of Genesis's key US product.",
            "Regulators in an export market flag documentation issues with Genesis shipments.",
        ],
    },

    # ── APEX MOBILITY (Automobile / EV) ─────────────────────────────────
    "apex": {
        "up": [
            "Apex's EV sales jump to a record month, ahead of every analyst estimate.",
            "Government revises the FAME subsidy scheme in a way that favours Apex's EV lineup.",
            "Apex's battery-cell joint venture confirms local production remains on track for 2027.",
            "Apex's new dedicated EV plant hits full production ahead of schedule.",
            "Apex's EV passenger car tops its segment's sales chart for the quarter.",
            "Apex secures a large fleet order from a leading ride-hailing operator.",
            "Independent safety testing awards Apex's newest EV a top rating, easing battery-fire fears.",
            "Apex's export shipments of electric two-wheelers ramp up sharply.",
            "Apex announces a price-competitive new EV model aimed at the mass market.",
            "Fuel prices spike, pushing more buyers to Apex's electric range.",
        ],
        "down": [
            "Apex announces a voluntary recall of an EV batch after a battery-related incident.",
            "A foreign EV brand confirms its India entry with aggressive pricing, worrying Apex investors.",
            "Government signals a cut to EV subsidies; Apex is among the most exposed.",
            "Apex's battery-cell joint venture slips its production timeline.",
            "Apex reports a sharp month-on-month fall in EV sales.",
            "A video of an Apex EV fire circulates widely on social media.",
            "Apex's legacy petrol two-wheeler sales decline faster than expected.",
            "Rising lithium and cell prices squeeze Apex's EV margins.",
            "Apex's EV plant hit by a supply-chain disruption for key components.",
            "Analysts cut Apex's target price, citing heavy capital spending with uncertain returns.",
        ],
    },

    # ── VORTEX CLEAN ENERGY (Renewable Energy) ──────────────────────────
    "vortex": {
        "up": [
            "Vortex wins a large new power-purchase-agreement tender from a state utility.",
            "Vortex signs a green-hydrogen off-take agreement, validating its pilot plant.",
            "Rating agency upgrades Vortex's debt, lowering its borrowing costs.",
            "Government hikes solar import duties, boosting the case for domestic-linked projects like Vortex's.",
            "RBI signals rate cuts — good news for debt-heavy Vortex.",
            "Vortex commissions a large new wind farm ahead of schedule.",
            "New renewable-energy subsidies announced, with Vortex among the biggest expected beneficiaries.",
            "Global solar panel prices stabilise, ending a long margin squeeze for Vortex.",
            "Vortex's green-hydrogen pilot plant meets its output targets for the quarter.",
            "A large industrial buyer signs a long-term clean power deal with Vortex.",
        ],
        "down": [
            "Vortex loses out on a major PPA tender it was widely expected to win.",
            "Interest rates rise — heavy debt makes Vortex especially vulnerable.",
            "Global solar panel prices crash again on Chinese oversupply, squeezing Vortex's margins.",
            "Green-hydrogen off-take talks stall; the pilot plant's commercial future looks uncertain.",
            "State utility delays payments to Vortex, straining working capital.",
            "Government rolls back a key renewable-energy incentive.",
            "A wind-farm equipment failure cuts Vortex's output for the quarter.",
            "Possible new solar import duty hike raises Vortex's project costs.",
            "Analysts warn Vortex's balance sheet is stretched by its capex plans.",
            "Weak wind conditions drag down Vortex's generation this quarter.",
        ],
    },

    # ── AURA DAILY ESSENTIALS (FMCG) ────────────────────────────────────
    "aura": {
        "up": [
            "A good monsoon forecast lifts expectations for rural demand, a key market for Aura.",
            "Palm-oil and crude-derivative prices ease, improving Aura's margins.",
            "Aura's rural distribution platform reaches thousands more small-town retailers.",
            "Aura's relaunched legacy brands gain market share for a second straight quarter.",
            "Government keeps GST on Aura's key product category unchanged.",
            "Aura is said to be acquiring a challenger D2C brand to boost its modern portfolio.",
            "Aura declares its usual steady dividend; defensive investors take comfort.",
            "Aura's volume growth beats expectations on a rural demand recovery.",
            "Investors rotate into defensives as markets wobble, supporting Aura.",
            "Aura's packaged-foods range posts its strongest quarter in years.",
        ],
        "down": [
            "Poor monsoon forecast raises worries about rural incomes and Aura's volumes.",
            "Palm-oil and crude-derivative prices spike, threatening Aura's margins.",
            "GST slab reclassification proposed for one of Aura's key product categories.",
            "D2C challenger brands eat into Aura's share in personal care.",
            "Aura announces price hikes, and analysts fear it will dent volumes.",
            "Aura's acquisition of a challenger brand is seen as overpriced by some analysts.",
            "A rural distribution glitch delays Aura's new product launches.",
            "Aura's quarterly volume growth misses estimates by a small margin.",
            "Rival FMCG giant launches an aggressive discount campaign against Aura's soaps.",
            "Input-cost inflation returns, and analysts trim Aura's margin forecasts.",
        ],
    },

    # ── SKYLINE INFRAPROJECTS (Infrastructure / Real Estate) ────────────
    "skyline": {
        "up": [
            "Skyline wins a large new national highway contract.",
            "Court rules in Skyline's favour in the land-dispute case on its stalled project.",
            "Skyline shortlisted in a major metro-adjacent tender.",
            "RBI signals rate cuts — welcome relief for debt-heavy Skyline.",
            "Skyline's tier-2 city real estate launches sell out ahead of schedule.",
            "Skyline completes a major highway stretch ahead of the deadline, earning a bonus.",
            "Government announces a big infrastructure spending push, with highways a priority.",
            "Skyline's order book reaches an all-time high.",
            "Rating agency upgrades Skyline after its debt restructuring is fully resolved.",
            "Skyline signs a large anchor tenant for its commercial real estate development.",
        ],
        "down": [
            "Court rules against Skyline in the land-dispute case, keeping its stalled project on hold.",
            "Skyline loses a major highway tender to a rival.",
            "Interest rates rise, and analysts flag debt-heavy Skyline as most exposed.",
            "Contractual penalty clauses triggered on a delayed Skyline project.",
            "Skyline's tier-2 real estate launch draws weaker-than-expected demand.",
            "Cement and steel prices spike, squeezing margins on Skyline's fixed-price contracts.",
            "Government delays infrastructure payments, straining Skyline's cash flow.",
            "A fresh land-acquisition dispute halts work on another Skyline site.",
            "Skyline's lenders ask for additional guarantees after slow project execution.",
            "Analysts warn Skyline's real estate expansion is stretching its balance sheet.",
        ],
    },

    # ── PULSE TELECOM (Telecom) ─────────────────────────────────────────
    "pulse": {
        "up": [
            "All three major telecom operators announce tariff hikes; Pulse leads the move.",
            "Pulse adds millions of 5G subscribers, beating estimates.",
            "Supreme Court gives relief on Pulse's remaining AGR dues.",
            "Pulse sells a further stake in its tower subsidiary at a strong valuation, cutting debt.",
            "Government announces a spectrum auction on terms friendly to existing operators.",
            "Pulse's average revenue per user climbs for the fifth straight quarter.",
            "Pulse raises its dividend, following its resumption after years.",
            "Pulse signs a large enterprise-connectivity contract with a national bank.",
            "Analysts upgrade Pulse, citing disciplined industry pricing.",
            "Pulse's broadband arm posts record customer additions.",
        ],
        "down": [
            "Supreme Court review goes against telecom operators on remaining AGR dues; Pulse faces a fresh bill.",
            "A rival launches a surprise price cut, reviving fears of a tariff war.",
            "Government announces a spectrum auction with steep reserve prices.",
            "Pulse's subscriber additions slow as 5G adoption plateaus.",
            "Rumoured tower-stake sale falls through, leaving debt reduction plans in doubt.",
            "Regulator proposes tougher quality-of-service penalties for telecom operators.",
            "Pulse suffers a large network outage, triggering customer complaints and regulator scrutiny.",
            "Tariff-hike plans are delayed after a rival refuses to follow.",
            "Pulse's capex needs for 5G rollout are higher than analysts expected.",
            "Global equipment supplier delays deliveries to Pulse's 5G rollout.",
        ],
    },
}


# ─────────────────────────────────────────────────────────────────────────
#  HOST / ORGANISER ONLY — never sent to players.
#  Cross-links and unresolved plot hooks from the dossier, for planning
#  manual news drops and chaos events.
# ─────────────────────────────────────────────────────────────────────────
ORGANISER_NOTES = {
    "cross_linkages": [
        "RBI rate moves hit Pioneer, Skyline (debt-heavy) and Vortex (capex-heavy) together — one headline can move three stocks. Aura barely reacts to interest rates.",
        "Genesis's unique lever is FDA/regulatory shocks. Apex and Vortex are driven by subsidy/policy shocks. Pulse moves on tariff-hike headlines. Skyline moves on contract wins/losses.",
        "Aura is the deliberate low-volatility anchor — a benchmark showing not every stock swings 20% on news.",
    ],
    "watch_list_hooks": {
        "nexus":   ["Pending US visa policy review", "Rumoured bid for a mid-sized European IT firm", "AI Delivery Center expansion decision due late 2026"],
        "pioneer": ["Rumoured acquisition of a small NBFC", "RBI review of digital lending partnerships", "Upcoming capital-raise decision"],
        "genesis": ["Pending FDA re-inspection of a third facility", "Ongoing arbitration over an African government supply contract", "Possible in-licensing deal for a biosimilar"],
        "apex":    ["Battery JV cell-production timeline", "Rumoured foreign EV brand India entry", "Possible FAME subsidy scheme revision"],
        "vortex":  ["Green hydrogen off-take agreement talks", "Possible further solar import duty hikes", "A large new PPA tender it is bidding for"],
        "aura":    ["Possible GST slab reclassification", "Monsoon forecast (rural income and demand)", "Rumoured challenger-brand acquisition for the D2C portfolio"],
        "skyline": ["Outcome of pending land-dispute court case", "A large new metro-adjacent tender", "Progress of tier-2 real estate bet"],
        "pulse":   ["Possible fourth spectrum auction", "Pending Supreme Court review of remaining AGR dues", "Rumoured further stake sale in the tower subsidiary"],
    },
    "game_schedule": [
        "Round 1: normal, no chaos.",
        "Round 2 start: Vortex lists (automatic).",
        "Round 3 start: Skyline lists + dividends on Nexus, Pioneer, Genesis, Apex, Aura (automatic).",
        "Round 4 start: dividends on all listed stocks (automatic); Nexus/Pulse acquisition rumour at the 5-minute mark, correlating the two prices for the last 15 minutes (automatic).",
    ],
}


# ─────────────────────────────────────────────────────────────────────────
#  PLOT GROUPS — mutually exclusive outcomes of the SAME storyline.
#  Once ANY headline in a group has run (auto-headline, host-injected preset, or the
#  round-start news pool), every other headline in that group is retired for the rest
#  of the game. That's what stops one game from containing both "Court rules in
#  Skyline's favour" and, later, "Court rules against Skyline".
#  Each entry is a substring that identifies a headline.
# ─────────────────────────────────────────────────────────────────────────
PLOT_GROUPS = {
    "skyline_court":       ["Court rules in Skyline's favour", "Court rules against Skyline"],
    "genesis_arbitration": ["Arbitration panel rules in Genesis's favour", "Arbitration over an African government supply contract turns against Genesis"],
    "genesis_fda":         ["USFDA clears Genesis's third", "USFDA issues a fresh observation at a Genesis",
                            "Genesis receives a warning letter over manufacturing", "Genesis Life Sciences receives an FDA warning letter"],
    "genesis_biosimilar":  ["Genesis signs an in-licensing deal", "in-licensing talks collapse"],
    "pulse_agr":           ["Supreme Court gives relief on Pulse", "Supreme Court review goes against telecom operators"],
    "pulse_tower":         ["Pulse sells a further stake in its tower", "Rumoured tower-stake sale falls through"],
    "pulse_spectrum":      ["spectrum auction on terms friendly", "spectrum auction with steep reserve prices"],
    "vortex_ppa":          ["Vortex wins a large new power-purchase-agreement tender", "Vortex loses out on a major PPA tender", "wins a 400MW solar tender"],
    "vortex_hydrogen":     ["signs a green-hydrogen off-take agreement", "Green-hydrogen off-take talks stall"],
    "apex_battery_jv":     ["battery-cell joint venture confirms local production remains on track", "battery-cell joint venture slips its production timeline"],
    "apex_recall":         ["Apex announces a voluntary recall of an EV batch", "Apex Mobility recalls a batch of its flagship EV"],
    "nexus_visa":          ["Nexus is cleared in the US visa-compliance review", "fresh whistleblower complaint on visa compliance"],
    "nexus_ai_center":     ["AI Delivery Center in Pune gets a green light", "AI Delivery Center expansion is deferred"],
    "pioneer_rbi_review":  ["RBI clears Pioneer's digital lending partnerships", "RBI opens a review of Pioneer's digital-lending"],
    "pioneer_capital":     ["Pioneer announces a capital raise at a premium", "Pioneer's capital-raise plan raises dilution fears"],
    "pioneer_nbfc":        ["Pioneer is said to be eyeing a bolt-on acquisition", "Reports that Pioneer overpaid for a small NBFC"],
    "aura_gst":            ["Government keeps GST on Aura", "GST slab reclassification proposed for one of Aura"],
}
