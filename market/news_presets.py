"""
news_presets.py — Market Mayhem / Inceptia

A large bank of ready-made headline text, organised by stock and by
direction ("up" / "down"). Used by main.py's /api/host/inject_news
endpoint whenever the host leaves the "News Text" field blank: it looks
up NEWS_PRESETS[<stock>][<"up" or "down">] and picks one at random.

This is intentionally kept separate from NEWS_POOL (in main.py), which
powers the automatic 2-3 news drops at the start of each round. That
pool tracks "already used" headlines across the whole game so the same
line never repeats; this file is for the host's manual injection tab
and can repeat across a session (there are enough options per stock/
direction that repeats are rare in a normal 6-round game).

To add more later: just append more strings to any list below. Nothing
else needs to change — inject_news() always re-reads this dict fresh.
"""

NEWS_PRESETS = {

    # ── ZORA INDUSTRIES (Manufacturing) ──────────────────────────────────
    "zora": {
        "up": [
            "Zora Industries lands a ₹1,200 crore railway-infrastructure order from the Ministry of Railways.",
            "Zora's Q3 export numbers beat estimates by 18% on strong Gulf demand for structural steel.",
            "Credit rating agency upgrades Zora Industries to AA+, citing debt reduction and steady cash flow.",
            "Zora announces a new automated plant in Gujarat, expected to cut production costs by 12%.",
            "A large mutual fund house discloses a fresh 3% stake in Zora Industries this week.",
            "Zora wins a multi-year maintenance contract for national highway bridges worth ₹850 crore.",
            "Government fast-tracks environmental clearance for Zora's new manufacturing unit.",
            "Zora Industries reports its best quarterly order book in five years.",
            "Steel prices firm up globally, lifting margins across Zora's core product lines.",
            "Zora's management reaffirms full-year guidance and hints at a special dividend.",
        ],
        "down": [
            "Zora Industries faces a show-cause notice over delayed delivery on a state government contract.",
            "A key raw-material supplier to Zora halts shipments amid a payment dispute.",
            "Labour unrest resurfaces at Zora's Pune facility as wage talks stall.",
            "Zora's largest client trims order volumes by 15% citing its own demand slowdown.",
            "Import tariffs on finished steel are cut, exposing Zora to cheaper foreign competition.",
            "Zora Industries misses quarterly delivery targets due to a machinery breakdown.",
            "An equipment fire at a secondary Zora unit halts production for several days.",
            "Analysts flag rising input costs squeezing Zora's margins this quarter.",
            "Zora's promoter family reportedly pledges a larger share of holdings against loans.",
            "A regulatory audit into Zora's environmental compliance is opened this week.",
        ],
    },

    # ── STREAMVERSE (Media / OTT) ─────────────────────────────────────────
    "streamvx": {
        "up": [
            "StreamVerse crosses 40 million paid subscribers, beating its own internal target.",
            "A StreamVerse original series becomes the most-watched regional show of the year.",
            "StreamVerse signs an exclusive streaming deal for a major upcoming cricket tournament.",
            "Subscription price hike sails through with minimal churn, boosting StreamVerse's ARPU.",
            "StreamVerse announces expansion into three new international markets.",
            "A global media giant is reportedly in early talks to license content from StreamVerse.",
            "StreamVerse's ad-supported tier posts record engagement numbers this quarter.",
            "StreamVerse trims content costs while viewership holds steady — margins improve sharply.",
            "Award-season buzz builds around a StreamVerse-produced film, driving new sign-ups.",
            "StreamVerse announces a profitable quarter for the first time since listing.",
        ],
        "down": [
            "StreamVerse loses a bidding war for marquee sports streaming rights to a rival platform.",
            "Subscriber growth stalls as StreamVerse faces intensifying competition from global players.",
            "A high-profile StreamVerse original is cancelled mid-production after budget overruns.",
            "Password-sharing crackdown backfires, triggering a wave of subscription cancellations.",
            "StreamVerse's content spend balloons past guidance, spooking margin-focused investors.",
            "A data-privacy complaint against StreamVerse draws regulatory scrutiny.",
            "Key creative leadership exits StreamVerse amid reports of internal disagreements.",
            "StreamVerse delays its flagship show's release by two quarters, frustrating subscribers.",
            "Churn rate ticks up sharply after StreamVerse's latest price increase.",
            "A rival platform undercuts StreamVerse with a cheaper bundled offering.",
        ],
    },

    # ── FRESHCO (FMCG) ─────────────────────────────────────────────────────
    "freshco": {
        "up": [
            "FreshCo's rural distribution push pays off with 22% volume growth outside metro cities.",
            "FreshCo launches a premium snacking range that sells out in early markets within days.",
            "Falling palm-oil prices ease input costs across FreshCo's product portfolio.",
            "FreshCo signs a large retail partnership, adding shelf space in 5,000 new stores.",
            "FreshCo's new ad campaign drives a noticeable uptick in brand recall and sales.",
            "A festive-season demand surge lifts FreshCo's quarterly volumes well above forecast.",
            "FreshCo announces a share buyback, citing confidence in long-term cash generation.",
            "Analysts upgrade FreshCo after a stronger-than-expected same-store sales report.",
            "FreshCo's export orders to Southeast Asia jump on a newly signed trade deal.",
            "FreshCo unveils a cost-cutting logistics overhaul projected to lift margins by 3%.",
        ],
        "down": [
            "Rising palm-oil and packaging costs squeeze FreshCo's gross margins this quarter.",
            "A product recall hits one of FreshCo's flagship snack lines over quality concerns.",
            "FreshCo's rural demand softens as an uneven monsoon dents consumer spending.",
            "A newer, cheaper competitor gains rapid market share in FreshCo's core segment.",
            "FreshCo delays a planned price hike, absorbing costs and hurting near-term margins.",
            "Distribution disruptions in key states dent FreshCo's quarterly volumes.",
            "FreshCo's ad spend surges but fails to move the needle on sales growth.",
            "A social-media complaint about packaging goes viral, denting FreshCo's brand sentiment.",
            "FreshCo's largest regional distributor exits the network amid a contract dispute.",
            "Weak festive-season sales fall short of FreshCo's internal projections.",
        ],
    },

    # ── VOLTEX ENERGY (Renewable Energy) ──────────────────────────────────
    "voltex": {
        "up": [
            "Voltex Energy wins a 500MW solar tender, its largest single project to date.",
            "Government announces fresh subsidies for renewable energy — Voltex is a direct beneficiary.",
            "Voltex signs a long-term power purchase agreement with a major industrial client.",
            "A breakthrough in battery-storage efficiency boosts Voltex's next-gen project economics.",
            "International green-energy fund takes a strategic stake in Voltex Energy.",
            "Voltex commissions its largest wind farm ahead of schedule and under budget.",
            "Falling solar panel import costs improve Voltex's project margins significantly.",
            "Voltex announces a joint venture to enter the green-hydrogen space.",
            "Credit agencies upgrade Voltex's outlook citing a de-risked project pipeline.",
            "Voltex Energy's quarterly capacity addition beats guidance by a wide margin.",
        ],
        "down": [
            "Delays in land acquisition push back Voltex's flagship solar project by two quarters.",
            "Rising interest rates raise borrowing costs for Voltex's capital-heavy project pipeline.",
            "A grid-connectivity dispute stalls power evacuation from a completed Voltex project.",
            "Import duties on solar components are hiked, denting Voltex's project economics.",
            "Voltex writes down a stalled wind project after a change in state policy.",
            "A key state government cancels a renewable tender Voltex had already bid heavily on.",
            "Monsoon damage to transmission infrastructure disrupts a major Voltex project site.",
            "Voltex's debt load draws scrutiny after a larger-than-expected capex overrun.",
            "A competitor undercuts Voltex sharply in a high-profile solar tender bid.",
            "Voltex delays its green-hydrogen pilot, citing technology and funding hurdles.",
        ],
    },

    # ── MEDIQ (Pharma) ──────────────────────────────────────────────────────
    "mediq": {
        "up": [
            "MediQ receives regulatory approval to export a key generic drug to the EU market.",
            "MediQ's new diabetes drug shows strong results in late-stage clinical trials.",
            "A large government tender for essential medicines is awarded largely to MediQ.",
            "MediQ announces a licensing deal that opens up a major new international market.",
            "Raw-material (API) costs ease, improving MediQ's margins across its generics portfolio.",
            "MediQ's R&D pipeline update surprises analysts with two new molecules in trials.",
            "A US regulatory inspection of MediQ's plant closes with zero observations.",
            "MediQ signs a co-marketing deal with a global pharma major for the Indian market.",
            "Strong flu-season demand drives a sales spike across MediQ's respiratory range.",
            "MediQ announces capacity expansion at its largest formulation plant.",
        ],
        "down": [
            "A US regulatory inspection flags quality-control lapses at a MediQ manufacturing plant.",
            "MediQ's key export market imposes new price controls, pressuring margins.",
            "A patent dispute delays MediQ's launch of a high-value generic drug.",
            "Raw-material shortages from a key API supplier disrupt MediQ's production schedule.",
            "MediQ recalls a batch of medication after a quality-control flag during routine testing.",
            "Government price caps on essential medicines squeeze MediQ's largest product line.",
            "A competitor's cheaper generic wins a major tender MediQ had counted on.",
            "MediQ's clinical trial for a flagship drug is paused pending additional safety data.",
            "Currency headwinds dent MediQ's overseas earnings when converted back to rupees.",
            "MediQ delays a plant expansion after cost overruns and permitting issues.",
        ],
    },

    # ── SKYLINK TECH (Technology) ──────────────────────────────────────────
    "skylink": {
        "up": [
            "SkyLink Tech wins a large multi-year cloud infrastructure contract from a Fortune 500 client.",
            "SkyLink's new AI-powered analytics product sees faster-than-expected enterprise adoption.",
            "A major client renews and expands its contract with SkyLink Tech by 40%.",
            "SkyLink announces record quarterly bookings, beating street estimates comfortably.",
            "SkyLink Tech is named a leader in an independent industry analyst report.",
            "SkyLink signs a strategic partnership with a global hyperscaler to co-sell products.",
            "Strong deal momentum in North America lifts SkyLink's revenue guidance for the year.",
            "SkyLink Tech announces a share buyback funded by strong free cash flow.",
            "A key SkyLink product wins a prestigious industry innovation award.",
            "SkyLink's attrition rate drops sharply, easing margin pressure from wage inflation.",
        ],
        "down": [
            "SkyLink Tech loses a marquee client to a lower-cost competitor after contract renewal talks stall.",
            "Slower enterprise IT spending in key overseas markets weighs on SkyLink's order book.",
            "A data breach at SkyLink Tech triggers a client audit and reputational concerns.",
            "SkyLink misses quarterly revenue guidance, citing project delays from a major client.",
            "Rising employee attrition forces SkyLink to hike wages, pressuring near-term margins.",
            "A key SkyLink executive departs abruptly amid reports of a strategy disagreement.",
            "Currency headwinds dent SkyLink's dollar-denominated revenue when repatriated.",
            "SkyLink's largest contract is put under review after a client's own budget cuts.",
            "A botched product rollout forces SkyLink to delay a flagship platform launch.",
            "Analysts flag margin compression as SkyLink invests heavily in unproven AI bets.",
        ],
    },

    # ── SWIFTHAUL LOGISTICS (Logistics) ─────────────────────────────────────
    "swifthaul": {
        "up": [
            "SwiftHaul Logistics wins a nationwide contract with a major e-commerce player.",
            "Falling fuel prices ease operating costs across SwiftHaul's fleet.",
            "SwiftHaul announces a tech upgrade that cuts delivery times by 20% in key metros.",
            "A new highway corridor opening cuts transit times on SwiftHaul's busiest routes.",
            "SwiftHaul reports record quarterly volumes as e-commerce shipments surge.",
            "SwiftHaul expands its cold-chain logistics arm, opening a new high-margin revenue line.",
            "A large FMCG client consolidates all its logistics needs under SwiftHaul.",
            "SwiftHaul's fleet electrification pilot cuts costs faster than expected.",
            "Government infrastructure push accelerates key freight corridors SwiftHaul depends on.",
            "SwiftHaul announces a joint venture to enter international freight forwarding.",
        ],
        "down": [
            "Rising diesel prices squeeze margins across SwiftHaul's delivery network.",
            "A major client shifts volumes in-house, cutting SwiftHaul's largest revenue stream.",
            "Nationwide trucker protests over fuel prices disrupt SwiftHaul's operations for days.",
            "SwiftHaul faces regulatory scrutiny over driver working-condition complaints.",
            "A warehouse fire disrupts SwiftHaul's operations in a key distribution hub.",
            "Intensifying price competition from new logistics entrants pressures SwiftHaul's margins.",
            "Monsoon flooding disrupts key SwiftHaul freight corridors for over a week.",
            "SwiftHaul's expansion into cold-chain logistics stalls due to funding delays.",
            "A key highway toll hike raises SwiftHaul's per-shipment costs significantly.",
            "SwiftHaul loses a major e-commerce contract to a lower-bid competitor.",
        ],
    },

    # ── CROWNMART (FMCG) ─────────────────────────────────────────────────────
    "crownmart": {
        "up": [
            "CrownMart's same-store sales growth beats estimates on strong festive demand.",
            "CrownMart announces aggressive store expansion into tier-2 and tier-3 cities.",
            "A private-label range launch drives higher margins across CrownMart's stores.",
            "CrownMart signs a large real-estate deal securing prime retail locations cheaply.",
            "Footfall at CrownMart outlets jumps after a well-received loyalty programme relaunch.",
            "CrownMart's online delivery arm posts its first profitable quarter.",
            "A major FMCG brand signs an exclusive in-store promotion deal with CrownMart.",
            "CrownMart announces cost savings from a new automated supply-chain system.",
            "Strong quarterly results prompt analysts to upgrade CrownMart's growth outlook.",
            "CrownMart's new express-delivery format gains rapid traction in metro markets.",
        ],
        "down": [
            "Rising retail rents in key cities squeeze CrownMart's store-level profitability.",
            "CrownMart's same-store sales growth slows sharply as online competition intensifies.",
            "A quality complaint about a private-label product goes viral, denting CrownMart's brand image.",
            "CrownMart shelves its aggressive store-expansion plan citing capital constraints.",
            "Weak consumer sentiment in urban markets dents CrownMart's discretionary category sales.",
            "A key supplier dispute leads to stock-outs across several CrownMart categories.",
            "CrownMart's online delivery arm posts wider-than-expected losses this quarter.",
            "Employee unrest over wages disrupts operations at several CrownMart outlets.",
            "A larger rival undercuts CrownMart aggressively on pricing in overlapping markets.",
            "CrownMart delays store openings after cost overruns on its logistics backbone.",
        ],
    },

    # ── SHIELDGEN DEFENCE (Defence) ─────────────────────────────────────────
    "shieldgen": {
        "up": [
            "ShieldGen Defence wins a ₹3,000 crore order for next-generation surveillance systems.",
            "Government clears a major defence export deal benefiting ShieldGen directly.",
            "ShieldGen announces a successful test of a new indigenous defence technology.",
            "A foreign defence ministry signs a preliminary agreement to procure ShieldGen systems.",
            "ShieldGen's order book hits an all-time high after a string of fresh contract wins.",
            "Policy push for domestic defence manufacturing gives ShieldGen a direct tailwind.",
            "ShieldGen announces a joint venture with a global defence major for co-production.",
            "Strong quarterly execution allows ShieldGen to raise its full-year revenue guidance.",
            "ShieldGen wins a competitive tender against larger rivals for a key system upgrade.",
            "Analysts flag ShieldGen's healthy order backlog as a multi-year growth driver.",
        ],
        "down": [
            "A key ShieldGen defence contract faces delays amid budget reprioritisation.",
            "ShieldGen's export order is put on hold following a shift in the buyer nation's policy.",
            "A test failure forces ShieldGen to delay delivery on a flagship system.",
            "Rising raw-material costs for specialised alloys squeeze ShieldGen's project margins.",
            "ShieldGen faces increased competition from a foreign player undercutting on price.",
            "A parliamentary panel raises questions over delays in a major ShieldGen programme.",
            "ShieldGen's largest contract is renegotiated at lower margins after a cost audit.",
            "Currency fluctuations dent the value of ShieldGen's dollar-denominated export orders.",
            "A component shortage from an overseas supplier stalls ShieldGen's production line.",
            "ShieldGen writes down costs on a cancelled joint development programme.",
        ],
    },

    # ── INDRANET (Technology) ────────────────────────────────────────────────
    "indranet": {
        "up": [
            "IndraNet wins a large government contract to build a next-gen digital infrastructure platform.",
            "IndraNet's cybersecurity division reports record enterprise client additions.",
            "A major telecom operator signs a multi-year deal with IndraNet for network software.",
            "IndraNet announces a breakthrough partnership to expand into Southeast Asia.",
            "Strong demand for IndraNet's cloud-security suite drives record quarterly bookings.",
            "IndraNet's new data-centre facility comes online ahead of schedule.",
            "A positive analyst report highlights IndraNet's growing recurring-revenue base.",
            "IndraNet signs a co-development deal with a global technology major.",
            "IndraNet reports its highest-ever quarterly profit on strong enterprise demand.",
            "Government's digital infrastructure push directly benefits IndraNet's core business.",
        ],
        "down": [
            "IndraNet faces scrutiny after a client reports a network outage tied to its platform.",
            "A key government tender is delayed, pushing back expected IndraNet revenue.",
            "IndraNet's largest telecom client signals plans to build capabilities in-house.",
            "Rising competition from global cloud players pressures IndraNet's pricing power.",
            "A cybersecurity incident at a client using IndraNet's platform draws unwanted attention.",
            "IndraNet delays its Southeast Asia expansion citing regulatory hurdles.",
            "Weaker enterprise IT budgets globally weigh on IndraNet's near-term order book.",
            "A senior IndraNet executive resigns amid reports of missed product timelines.",
            "IndraNet's data-centre expansion runs into cost overruns and permitting delays.",
            "Analysts flag slowing growth in IndraNet's core network-software segment.",
        ],
    },

    # ── NOVAPAY (Fintech — IPO) ──────────────────────────────────────────────
    "novapay": {
        "up": [
            "NovaPay crosses 10 million monthly active users faster than any fintech in the category.",
            "NovaPay secures a payment-aggregator licence, unlocking a major new revenue stream.",
            "A leading bank signs an exclusive co-branded card partnership with NovaPay.",
            "NovaPay's transaction volumes double year-on-year, beating analyst expectations.",
            "A global payments major takes a strategic minority stake in NovaPay.",
            "NovaPay launches a lending product that sees rapid early adoption.",
            "NovaPay announces its first profitable quarter since its market debut.",
            "Regulatory clarity on digital payments removes a key overhang on NovaPay's stock.",
            "NovaPay signs up 50,000 new merchants in a single quarter.",
            "NovaPay's fraud-detection AI wins industry recognition, boosting enterprise trust.",
        ],
        "down": [
            "Regulators tighten digital lending norms, directly impacting NovaPay's newest product line.",
            "NovaPay reports slower-than-expected merchant acquisition amid intense competition.",
            "A payment outage during a peak shopping event dents NovaPay's user trust.",
            "NovaPay's largest banking partner scales back its co-branded card programme.",
            "Rising customer-acquisition costs widen NovaPay's losses this quarter.",
            "A data-security lapse at NovaPay triggers a regulatory inquiry.",
            "Competition from larger payment players intensifies, pressuring NovaPay's market share.",
            "NovaPay delays its lending product launch amid new compliance requirements.",
            "Investor sentiment sours on fintech names broadly, dragging NovaPay down with the sector.",
            "NovaPay's transaction take-rate is cut after a renegotiation with a key partner.",
        ],
    },

    # ── GREENLEAF AGRI (Agriculture — IPO) ───────────────────────────────────
    "greenleaf": {
        "up": [
            "GreenLeaf Agri signs a large export deal for organic produce to European markets.",
            "A bumper harvest season boosts GreenLeaf's processing volumes sharply.",
            "GreenLeaf announces a new cold-storage network, cutting post-harvest losses significantly.",
            "Government subsidies for agri-tech adoption give GreenLeaf a direct tailwind.",
            "GreenLeaf's direct-to-farmer sourcing model shows sharp margin improvement.",
            "A major retail chain signs an exclusive supply agreement with GreenLeaf.",
            "GreenLeaf's new seed technology shows strong yield improvements in field trials.",
            "Favourable monsoon forecasts lift sentiment across GreenLeaf's entire supply chain.",
            "GreenLeaf announces expansion into packaged organic foods, a higher-margin category.",
            "Strong quarterly results beat expectations on robust rural demand.",
        ],
        "down": [
            "An unseasonal hailstorm damages crops across GreenLeaf's key sourcing regions.",
            "Export restrictions on agricultural produce are imposed, hitting GreenLeaf's overseas sales.",
            "A pest outbreak disrupts yields in one of GreenLeaf's primary growing regions.",
            "Rising fertiliser costs squeeze margins for GreenLeaf's contracted farmer network.",
            "GreenLeaf's cold-storage expansion is delayed due to funding constraints.",
            "A weak monsoon forecast dents sentiment across GreenLeaf's entire supply chain.",
            "A quality dispute with a major export client stalls a large shipment.",
            "GreenLeaf writes down inventory after unexpected spoilage at a storage facility.",
            "Volatile commodity prices squeeze GreenLeaf's processing margins this quarter.",
            "A key retail partner delays payments, straining GreenLeaf's working capital.",
        ],
    },

    # ── ARMORINC (Defence — IPO) ─────────────────────────────────────────────
    "armorinc": {
        "up": [
            "ArmorInc wins a large domestic order for next-generation protective equipment.",
            "ArmorInc successfully completes trials for a new armoured vehicle component.",
            "A foreign government places its first export order with ArmorInc.",
            "ArmorInc announces a joint venture to localise a critical defence component.",
            "Policy support for domestic defence manufacturing gives ArmorInc a direct boost.",
            "ArmorInc's order book swells after a string of competitive tender wins.",
            "ArmorInc's IPO-funded capacity expansion comes online ahead of schedule.",
            "A large multi-year maintenance contract is awarded to ArmorInc.",
            "ArmorInc announces its first profitable quarter as a listed company.",
            "Analysts highlight ArmorInc's improving margins as scale kicks in.",
        ],
        "down": [
            "A key ArmorInc contract is delayed pending additional government approvals.",
            "Component shortages from an overseas supplier disrupt ArmorInc's production schedule.",
            "ArmorInc faces increased competition from an established defence manufacturer.",
            "A test setback forces ArmorInc to push back a key product delivery timeline.",
            "Rising raw-material costs squeeze margins on ArmorInc's flagship product line.",
            "ArmorInc's export order is paused following a shift in the buyer nation's budget priorities.",
            "A parliamentary review flags delays in a defence programme involving ArmorInc.",
            "ArmorInc's capacity expansion runs into cost overruns post-IPO.",
            "Currency swings dent the value of ArmorInc's dollar-denominated contracts.",
            "ArmorInc reports a wider-than-expected quarterly loss as a newly listed company.",
        ],
    },

    # ── BYTECORP AI (Technology — IPO) ───────────────────────────────────────
    "bytecorp": {
        "up": [
            "ByteCorp AI signs its first major enterprise pilot-to-contract conversion.",
            "ByteCorp's BharatGPT model tops an independent regional-language benchmark.",
            "A global tech major announces a partnership to integrate ByteCorp's AI models.",
            "ByteCorp AI raises a fresh funding round at a sharply higher valuation.",
            "ByteCorp signs a government pilot to deploy its AI models in public services.",
            "ByteCorp's founder-led TED talk goes viral, driving a wave of investor interest.",
            "ByteCorp announces its first paying enterprise customer at meaningful scale.",
            "A positive third-party audit validates ByteCorp's AI model performance claims.",
            "ByteCorp AI is named in a global list of most-watched AI startups.",
            "ByteCorp signs a data-partnership deal that meaningfully improves its model training.",
        ],
        "down": [
            "ByteCorp AI's enterprise pilots fail to convert into paying contracts this quarter.",
            "A rival's foundation model outperforms ByteCorp's BharatGPT on key benchmarks.",
            "ByteCorp burns through cash faster than expected, raising runway concerns.",
            "ByteCorp AI's much-hyped demo draws criticism after independent testing reveals gaps.",
            "A senior ByteCorp researcher departs for a rival AI lab.",
            "ByteCorp's valuation is questioned publicly by a well-known market commentator.",
            "ByteCorp delays a planned product launch citing technical setbacks.",
            "A funding round for ByteCorp reportedly closes at a lower valuation than expected.",
            "ByteCorp's largest enterprise pilot is put on hold pending budget review.",
            "Regulatory uncertainty around AI governance weighs on sentiment toward ByteCorp.",
        ],
    },
}
