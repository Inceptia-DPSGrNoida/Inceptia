"""
news_presets.py — Market Mayhem (APEX-20 roster)

NEWS_POOL      Round-start news, drawn at random, never repeated within a game. Everything in it is TRUE
               (it moves the price as stated). Entries marked src="rumour" are rumours that turn out to be
               correct; players see them as ordinary news — no verified/unverified labels anywhere.
FALSE_RUMOURS  Rumours that are NOT true. Used ONLY in the Truth-or-False chaos event (one round); the
               host alone knows which headlines are real.
NEWS_PRESETS   Ready-made headlines for the host's "Inject News" tab, per company and direction.
PLOT_GROUPS    Mutually exclusive outcomes of one storyline — once one has run, its opposite is retired.
ORGANISER_NOTES  Host-only notes, never sent to players.
"""

NEWS_PRESETS = {

    # ── ZENITH DYNAMICS LTD. (ZNDY) ──
    "zndy": {
        "up": [
            "Zenith's Southeast Asian export pact is extended with Zenith as lead supplier.",
            "Zenith Dynamics reports record order inflow as global security budgets keep rising.",
            "Institutional defence funds raise their stake in Zenith ahead of the defence budget.",
            "Zenith's second production hub clears a Level-4 security audit, unlocking new classified work.",
            "Defence ministry confirms Zenith as Tier-1 contractor for the next tactical actuator cycle.",
        ],
        "down": [
            "Zenith's Southeast Asian export pact is shelved after a political reshuffle.",
            "Eastern European titanium shipments are held up again; Zenith warns of slipping deliveries.",
            "A supplementary review trims the defence capital budget; Zenith is the most exposed listed name.",
            "Saab and Thales undercut Zenith on a neutral-market export tender in the Middle East.",
            "Optical-microchip sanctions tighten, raising Zenith's input costs.",
        ],
    },

    # ── AURA BIOPHARMA SCIENCES (ABPH) ──
    "abph": {
        "up": [
            "Aura BioPharma's Baddi unit clears its re-inspection, ending the import alert.",
            "Government raises PLI incentives for specialty APIs; Aura is a prime beneficiary.",
            "Aura's HPAPI pipeline lands two new commercial orders in Germany.",
            "Aura adds a fourth GMP-certified line at its Genome Valley campus.",
            "Chinese fermentation plants lose their power subsidy, easing price pressure on Aura.",
        ],
        "down": [
            "US-FDA officials say Aura's Baddi unit fails its re-inspection, prolonging the import alert.",
            "NPPA widens price caps on essential medicines, hitting Aura's domestic portfolio.",
            "Subsidised Chinese APIs flood the market, squeezing Aura's pricing.",
            "A key German distributor shifts part of its order to a rival supplier.",
            "Aura slides as the market braces for a rough inspection season.",
        ],
    },

    # ── VOLTIX ENERGY TECHNOLOGIES (VTXE) ──
    "vtxe": {
        "up": [
            "Voltix's safety clearances are reissued in full, reopening its stalled utility orders.",
            "Voltix lands a second state-utility battery tender on the back of renewable mandates.",
            "Custom-duty waivers on imported lithium cells are extended, protecting Voltix's margins.",
            "Brokerages upgrade Voltix on record revenue growth and widening profits.",
            "Voltix signs a new battery-management software licensing deal with a data-centre operator.",
        ],
        "down": [
            "Regulators extend the safety probe into Voltix's installations; new orders are paused.",
            "Basic customs duty on lithium cells is hiked; Voltix warns of margin compression.",
            "CATL and BYD slash prices on fully assembled storage containers, pressuring Voltix.",
            "Voltix's cash burn worries investors as capex climbs again.",
            "A key cell supplier delays shipments to Voltix by two months.",
        ],
    },

    # ── APEX MERCANTILE BANK (APMB) ──
    "apmb": {
        "up": [
            "Apex Mercantile Bank announces a larger final dividend after a record profit year.",
            "Credit-rating agency upgrades Apex Mercantile's outlook on asset quality.",
            "Retail loan growth beats expectations at Apex Mercantile for a third straight quarter.",
            "Foreign institutions return to Indian banks; Apex Mercantile is a top beneficiary.",
            "Apex Mercantile's net interest margin widens as deposit costs ease.",
        ],
        "down": [
            "Central Bank signals further reserve-ratio hikes, a drag on Apex Mercantile.",
            "Priority Sector Lending norms tighten; Apex Mercantile's returns face pressure.",
            "A US bond sell-off triggers FII outflows from banking stocks, led by Apex Mercantile.",
            "Apex Mercantile's wholesale book shows early signs of stress.",
            "Repo-rate cut expectations squeeze Apex Mercantile's margin outlook.",
        ],
    },

    # ── HARBORLOGIX INFRASTRUCTURE (HBLX) ──
    "hblx": {
        "up": [
            "HarborLogix raises its dividend again, a boost for pension-fund holders.",
            "Maritime Regulatory Authority approves an inflation-linked tariff hike for HarborLogix.",
            "HarborLogix adds container rakes to its fleet as volumes climb.",
            "Infrastructure-bond access cuts HarborLogix's borrowing costs.",
            "A new shipping alliance signs a long-term take-or-pay agreement with HarborLogix.",
        ],
        "down": [
            "Maritime Regulatory Authority freezes port tariffs for a year, a blow to HarborLogix.",
            "Trade-bloc tariffs escalate; analysts cut HarborLogix's container-volume forecasts.",
            "A rival port wins a long-haul transshipment contract away from HarborLogix.",
            "Rail corridor congestion delays HarborLogix's freight transfers.",
            "Shipping-lane disruptions dent HarborLogix's throughput this quarter.",
        ],
    },

    # ── VERVE CONSUMER BRANDS (VRVE) ──
    "vrve": {
        "up": [
            "Verve Consumer Brands lifts its dividend again after a strong monsoon-led quarter.",
            "Verve's baby-care range gains share in metro quick-commerce.",
            "Palm oil prices fall; analysts expect margin expansion at Verve.",
            "Verve widens its direct retail reach beyond 4.2 million stores.",
            "Verve's co-manufacturing model lowers costs on standard packaging.",
        ],
        "down": [
            "Rural slowdown deepens as monsoon disappoints; Verve warns on volumes.",
            "FSSAI tightens nutritional labelling norms; Verve faces higher compliance costs.",
            "Global FMCG rivals ramp up ad spending, pressuring Verve's market share.",
            "Crude palm oil prices spike, squeezing Verve's input costs.",
            "A GST adjustment raises prices on Verve's packaged foods.",
        ],
    },

    # ── KRYOS SEMI-CONDUCTORS LTD. (KRYS) ──
    "krys": {
        "up": [
            "Kryos Semi-Conductors expands its smart-meter chip share past 40%.",
            "National Semiconductor Mission approves fresh tape-out subsidies for Kryos.",
            "Kryos ramps a new motor-drive controller chip to volume production.",
            "A global chip-inventory glut clears; Kryos guides to stronger demand.",
            "Kryos's IoT silicon wins design slots at a leading smart-meter maker.",
        ],
        "down": [
            "Taiwan Strait tensions escalate; Kryos falls on foundry-access fears.",
            "Chip-design software restrictions tighten; Kryos warns of delays.",
            "A glut of microcontrollers reappears, pushing down Kryos's selling prices.",
            "Kryos loses a smart-meter tender to a rival.",
            "Tech valuations compress and Kryos falls with the sector.",
        ],
    },

    # ── TERRAFIRM CEMENT & MATERIALS (TRFM) ──
    "trfm": {
        "up": [
            "TerraFirm Cement says it is not in sale talks, but a bid is widely expected.",
            "Affordable-housing push lifts cement demand; TerraFirm gains.",
            "Coal prices ease, improving TerraFirm's cost position.",
            "TerraFirm commissions a new grinding line ahead of the road-building season.",
            "Highway awards accelerate, a tailwind for TerraFirm.",
        ],
        "down": [
            "TerraFirm Cement shares fall as hopes of a takeover bid fade.",
            "Imported slag tariffs trim TerraFirm's pricing power.",
            "Public infrastructure spending slows; cement stocks, including TerraFirm, fall.",
            "A capacity glut forces cement price cuts; TerraFirm warns on margins.",
            "Sea-borne coal prices jump again, hitting TerraFirm's costs.",
        ],
    },

    # ── NOVASTEEL ALLOYS (NVST) ──
    "nvst": {
        "up": [
            "NovaSteel's green-steel pilot gets a premium offtake commitment from an auto customer.",
            "Auto production rebounds; NovaSteel lifts its output guidance.",
            "Coking-coal prices ease, improving NovaSteel's margin outlook.",
            "Government extends safeguard duties on steel imports, a plus for NovaSteel.",
            "NovaSteel completes its debottlenecking, raising cold-rolled capacity.",
        ],
        "down": [
            "Steel safeguard duties lapse, exposing NovaSteel to a new wave of imports.",
            "Auto production slows sharply; NovaSteel cuts its volume guidance.",
            "Coking-coal prices spike on supply disruptions, hitting NovaSteel.",
            "A rival's capacity expansion triggers a price war in cold-rolled steel.",
            "Global steel prices weaken; NovaSteel slips with the sector.",
        ],
    },

    # ── QUANTIX CLOUD SYSTEMS (QNTX) ──
    "qntx": {
        "up": [
            "Quantix Cloud Systems announces a buyback after another quarter of 32%-plus operating margins.",
            "Global tech earnings beat; Quantix rallies on the sector lift.",
            "Quantix wins a flagship contract with a government agency.",
            "Brokerages raise targets on Quantix as subscription revenue accelerates.",
            "Quantix cloud-security product wins an industry award.",
        ],
        "down": [
            "Quantix Cloud Systems falls as a competitor undercuts it on enterprise security pricing.",
            "Global tech earnings disappoint; Quantix drops with the sector.",
            "An AI-driven rival product launch raises worries about Quantix's moat.",
            "A rate-hike scare hits growth valuations; Quantix is sold off.",
            "A data-sovereignty rule complicates Quantix's cloud deployments.",
        ],
    },

    # ── PRIMUS AUTOWORKS (PRMA) ──
    "prma": {
        "up": [
            "EV incentives are extended another five years; Primus is the biggest winner.",
            "Primus AutoWorks' Pune plant doubles chassis output ahead of schedule.",
            "Lithium prices slump, boosting Primus's margin outlook.",
            "A major delivery fleet orders thousands of Primus electric vans.",
            "Primus's profit more than doubles; brokerages raise targets.",
        ],
        "down": [
            "EV incentives are cut sharply; Primus warns of lower order flow.",
            "Lithium prices jump; Primus flags margin pressure.",
            "Chinese EV makers cut prices in commercial EVs, pressuring Primus.",
            "A state delays payments to Primus, hurting working capital.",
            "Primus's shares slide as bus tender rules are rewritten.",
        ],
    },

    # ── GLOTECH TELECOM LTD. (GLTL) ──
    "gltl": {
        "up": [
            "Glotech Telecom prepays a chunk of debt, easing its interest burden.",
            "Regulator approves higher fibre-lease tariffs for Glotech.",
            "A second carrier commits to an exclusive long-term fibre contract with Glotech.",
            "Glotech's tenancy ratio rises as 5G sites multiply.",
            "Rate cuts bring Glotech's financing costs lower.",
        ],
        "down": [
            "Regulator imposes new tower-sharing caps; Glotech's outlook dims.",
            "Rising interest rates weigh on Glotech's heavily indebted balance sheet.",
            "A tenant carrier delays payments to Glotech.",
            "Equipment-vendor bans slow 5G site rollouts, hitting Glotech.",
            "Glotech's shares drop as rating agencies flag its debt load.",
        ],
    },

    # ── URBANGRID POWER UTILITY (URBN) ──
    "urbn": {
        "up": [
            "UrbanGrid Power raises its dividend again, the highest yield on the exchange.",
            "Regulator approves UrbanGrid's capital-expenditure plan for its metro zones.",
            "UrbanGrid's distribution losses fall to a record low after smart-meter upgrades.",
            "Power demand surges in a heatwave, lifting UrbanGrid's volumes.",
            "A green-bond issue lowers UrbanGrid's cost of capital.",
        ],
        "down": [
            "Regulator rejects UrbanGrid's tariff petition; the dividend outlook is questioned.",
            "Peak-season grid failures draw regulator fines for UrbanGrid.",
            "ESG funds exit UrbanGrid on coal-asset concerns.",
            "Coal-linked power-purchase costs jump, eating into UrbanGrid's margins.",
            "UrbanGrid's shares drop as rate-of-return rules are reviewed.",
        ],
    },

    # ── SOLARIS AGROCHEMICALS (SLRA) ──
    "slra": {
        "up": [
            "Solaris Agrochemicals's subsidy arrears are cleared in full, easing its working capital.",
            "Early monsoon onset lifts sowing and fertiliser offtake; Solaris gains.",
            "Gas prices fall, widening Solaris's urea margins.",
            "Solaris's crop-protection exports win new registrations in Latin America.",
            "Solaris commissions a new NPK complex line, lifting margins.",
        ],
        "down": [
            "Subsidy payments to Solaris are delayed again, straining its working capital.",
            "Monsoon deficit widens; fertiliser sales slump and Solaris falls.",
            "Gas prices spike on global supply fears; Solaris's margins narrow.",
            "EU residue bans curb Solaris's pesticide exports.",
            "Urea price controls are tightened, capping Solaris's returns.",
        ],
    },

    # ── MEDVANTAGE HOSPITALS (MEDV) ──
    "medv": {
        "up": [
            "MedVantage Hospitals reports record occupancy as oncology and transplant volumes climb.",
            "Medical-visa fast-tracking boosts international patient inflows at MedVantage.",
            "MedVantage opens a new cancer centre, expanding high-margin capacity.",
            "Health-insurance penetration rises, lifting MedVantage's volumes.",
            "A leading transplant surgeon team joins MedVantage from a rival.",
        ],
        "down": [
            "Price caps on cardiac and orthopaedic procedures are widened; MedVantage slips.",
            "A key oncology team resigns from MedVantage.",
            "Insurers delay claims settlement to MedVantage, stretching receivables.",
            "Medical-tourism visas are tightened, trimming MedVantage's inflows.",
            "A regulatory probe into a MedVantage hospital weighs on sentiment.",
        ],
    },

    # ── NEXTGEN RETAIL MALLS (NXGN) ──
    "nxgn": {
        "up": [
            "NextGen Retail Malls hikes its distribution per unit as occupancy edges up.",
            "Interest rates are cut; REIT yields look more attractive and NextGen gains.",
            "NextGen's food-and-experience zones push tenant sales to a fresh record.",
            "NextGen adds a new multiplex tenant at a flagship mall.",
            "A refinancing at lower rates trims NextGen's interest costs.",
        ],
        "down": [
            "Rates move higher; NextGen's distribution yield looks less attractive.",
            "Anchor tenant announces exit at a NextGen mall; the owner scrambles to re-let.",
            "E-commerce giants step up discounts; mall footfall dips at NextGen.",
            "Tenant sales soften at NextGen malls in a weak consumption quarter.",
            "NextGen units fall as property-sector sentiment sours.",
        ],
    },

    # ── OCEANAIR CARGO EXPRESS (OCNA) ──
    "ocna": {
        "up": [
            "Global shipping choke-point crisis diverts a wave of cargo to OceanAir.",
            "OceanAir signs a cold-chain deal for next-generation biologics.",
            "Jet-fuel prices ease, widening OceanAir's operating margin.",
            "OceanAir adds a freighter aircraft and launches a new express route.",
            "Pharma exports hit a record, boosting OceanAir's volumes.",
        ],
        "down": [
            "A shipping choke-point reopens; sea freight rates collapse and OceanAir loses its edge.",
            "Jet-fuel prices jump; OceanAir warns on margins.",
            "A global trade slowdown cuts air-cargo volumes at OceanAir.",
            "A key e-commerce customer shifts volume to a rival carrier.",
            "Airport slot-fee hikes trim OceanAir's profit outlook.",
        ],
    },

    # ── FLEXWARE TEXTILES & POLYMERS (FLXW) ──
    "flxw": {
        "up": [
            "Crude oil falls sharply, cutting FlexWare's raw-material costs.",
            "FlexWare's export orders climb on a weaker rupee.",
            "Anti-dumping duties are enforced strictly, protecting FlexWare's domestic prices.",
            "FlexWare commissions a new high-speed extrusion line.",
            "A global brand picks FlexWare for recycled-packaging supply.",
        ],
        "down": [
            "Crude oil jumps again; FlexWare's margin outlook weakens.",
            "Plastic regulation tightens; FlexWare faces higher compliance costs.",
            "Cheap imports flood in as anti-dumping enforcement lapses; FlexWare falls.",
            "Export demand slumps; FlexWare warns on volumes.",
            "FlexWare slips as the textile cycle turns down.",
        ],
    },

    # ── ORBIT AEROSPACE SENSORS (ORBT) ──
    "orbt": {
        "up": [
            "Orbit Aerospace's constellation launch succeeds; imagery revisit time halves.",
            "Government grants Orbit a wider licence to sell high-resolution imagery.",
            "Orbit signs a shipping-lane monitoring contract with a global logistics giant.",
            "Orbit's subscription revenue accelerates as agricultural clients renew.",
            "Orbit's profit margin widens as subscription revenue scales.",
        ],
        "down": [
            "Orbit Aerospace's launch fails; two satellites are lost.",
            "Orbit's launch partner grounds its rocket; the next deployment is delayed indefinitely.",
            "Licensing curbs on imagery resolution hit Orbit's defence revenue.",
            "A rival constellation undercuts Orbit's subscription pricing.",
            "Orbit's shares drop as R&D spending outpaces revenue.",
        ],
    },

    # ── AQUAPURE ENVIRONMENTAL (AQUA) ──
    "aqua": {
        "up": [
            "AquaPure Environmental clears a large batch of pending municipal bills.",
            "Zero-liquid-discharge enforcement widens, driving orders to AquaPure.",
            "AquaPure signs a desalination O&M contract with a coastal state.",
            "Government raises water-recycling targets; AquaPure's order book swells.",
            "AquaPure raises its dividend on strong order execution.",
        ],
        "down": [
            "Municipal payments to AquaPure slip further; its receivables swell.",
            "Environmental enforcement is relaxed; AquaPure's order pipeline thins.",
            "Imported membrane costs surge, squeezing AquaPure's margins.",
            "A major project is cancelled; AquaPure writes down its backlog.",
            "AquaPure shares drop on slower tender awards.",
        ],
    },
}

NEWS_POOL = [   # all TRUE
    # ── ZNDY ──
    {"src":"news", "affects":"zndy", "direction": 1, "strength":0.08, "real":True, "text":"Zenith Dynamics wins a multi-year radar guidance order from the Ministry of Defense, its largest this decade."},
    {"src":"news", "affects":"zndy", "direction": 1, "strength":0.06, "real":True, "text":"Government widens the 'Make in India' defence import-ban list to cover Zenith's counter-drone nodes."},
    {"src":"news", "affects":"zndy", "direction":-1, "strength":0.08, "real":True, "text":"Titanium alloy shipments to Zenith Dynamics are delayed again, stalling airframe output at one hub."},
    {"src":"news", "affects":"zndy", "direction":-1, "strength":0.07, "real":True, "text":"Western export curbs on high-bandwidth optical microchips threaten Zenith's next-generation UAV sensors."},
    {"src":"rumour", "affects":"zndy", "direction": 1, "strength":0.06, "real":True, "text":"Whispers: Zenith is close to a second export pact with a Middle East defence department."},
    {"src":"rumour", "affects":"zndy", "direction":-1, "strength":0.06, "real":True, "text":"Word is a key Zenith radar programme faces a six-month certification delay."},
    # ── ABPH ──
    {"src":"news", "affects":"abph", "direction": 1, "strength":0.1, "real":True, "text":"Aura BioPharma passes a US-FDA inspection with zero observations at its flagship plant."},
    {"src":"news", "affects":"abph", "direction": 1, "strength":0.08, "real":True, "text":"Aura BioPharma wins a multi-year oncology biosimilar supply deal with a top North American distributor."},
    {"src":"news", "affects":"abph", "direction":-1, "strength":0.1, "real":True, "text":"US-FDA issues an import alert on Aura BioPharma's secondary fermentation unit in Baddi."},
    {"src":"news", "affects":"abph", "direction":-1, "strength":0.09, "real":True, "text":"An NPPA price cap on an essential medicine cuts into Aura BioPharma's domestic margins."},
    {"src":"rumour", "affects":"abph", "direction": 1, "strength":0.08, "real":True, "text":"Whispers: Aura is close to a Brazilian distribution deal for its HPAPI range."},
    {"src":"rumour", "affects":"abph", "direction":-1, "strength":0.08, "real":True, "text":"Word is Aura's next US-FDA inspection is imminent and not expected to be clean."},
    # ── VTXE ──
    {"src":"news", "affects":"vtxe", "direction": 1, "strength":0.17, "real":True, "text":"Voltix Energy lands a 500 MWh grid-storage tender, its biggest order yet."},
    {"src":"news", "affects":"vtxe", "direction": 1, "strength":0.14, "real":True, "text":"Voltix's Gujarat plant hits full run-rate on its 3.5 GWh automated pack line."},
    {"src":"news", "affects":"vtxe", "direction":-1, "strength":0.17, "real":True, "text":"A thermal-runaway incident at a Voltix-supplied solar farm triggers a safety probe."},
    {"src":"news", "affects":"vtxe", "direction":-1, "strength":0.15, "real":True, "text":"Government raises basic customs duty on imported lithium cells, squeezing Voltix's margins."},
    {"src":"rumour", "affects":"vtxe", "direction": 1, "strength":0.13, "real":True, "text":"Whispers: Voltix is close to a data-centre storage deal worth several hundred crore."},
    {"src":"rumour", "affects":"vtxe", "direction":-1, "strength":0.13, "real":True, "text":"Word is Voltix's Korean cell supplier may raise prices next quarter."},
    # ── APMB ──
    {"src":"news", "affects":"apmb", "direction": 1, "strength":0.05, "real":True, "text":"Apex Mercantile Bank reports 18% loan growth with GNPA still below 2%."},
    {"src":"news", "affects":"apmb", "direction": 1, "strength":0.04, "real":True, "text":"Apex Mercantile's low-cost deposit base widens again, cutting its funding costs."},
    {"src":"news", "affects":"apmb", "direction":-1, "strength":0.05, "real":True, "text":"The Central Bank raises cash reserve ratios, trimming Apex Mercantile's lendable funds."},
    {"src":"news", "affects":"apmb", "direction":-1, "strength":0.05, "real":True, "text":"Foreign investors pull money from banks as US sovereign yields jump; Apex Mercantile slips."},
    {"src":"rumour", "affects":"apmb", "direction": 1, "strength":0.04, "real":True, "text":"Buzz: Apex Mercantile is planning a large new tranche of branch openings."},
    {"src":"rumour", "affects":"apmb", "direction":-1, "strength":0.04, "real":True, "text":"Word is Priority Sector Lending targets will be raised again, squeezing Apex Mercantile."},
    # ── HBLX ──
    {"src":"news", "affects":"hblx", "direction": 1, "strength":0.05, "real":True, "text":"HarborLogix wins a 30-year operating lease for a chemical terminal."},
    {"src":"news", "affects":"hblx", "direction": 1, "strength":0.04, "real":True, "text":"Container volumes across Asia rebound, lifting throughput at HarborLogix's deep-water berths."},
    {"src":"news", "affects":"hblx", "direction":-1, "strength":0.05, "real":True, "text":"Red Sea disruptions force shipping alliances to reroute away from HarborLogix's berths."},
    {"src":"news", "affects":"hblx", "direction":-1, "strength":0.05, "real":True, "text":"The Maritime Regulatory Authority orders a review of HarborLogix's port tariffs."},
    {"src":"rumour", "affects":"hblx", "direction": 1, "strength":0.04, "real":True, "text":"Whispers: HarborLogix is bidding for a new rail corridor concession."},
    {"src":"rumour", "affects":"hblx", "direction":-1, "strength":0.04, "real":True, "text":"Word is a major shipping alliance is shifting volume to a rival port."},
    # ── VRVE ──
    {"src":"news", "affects":"vrve", "direction": 1, "strength":0.05, "real":True, "text":"Verve Consumer Brands posts steady growth as quick-commerce sales jump in metro cities."},
    {"src":"news", "affects":"vrve", "direction": 1, "strength":0.04, "real":True, "text":"Falling palm-oil and packaging-plastic prices ease margin pressure at Verve."},
    {"src":"news", "affects":"vrve", "direction":-1, "strength":0.05, "real":True, "text":"Weak rural demand dents Verve Consumer Brands' volumes this quarter."},
    {"src":"news", "affects":"vrve", "direction":-1, "strength":0.05, "real":True, "text":"A new front-of-pack labelling rule forces costly packaging changes at Verve."},
    {"src":"rumour", "affects":"vrve", "direction": 1, "strength":0.04, "real":True, "text":"Buzz: Verve is looking to acquire a challenger packaged-foods brand."},
    {"src":"rumour", "affects":"vrve", "direction":-1, "strength":0.04, "real":True, "text":"Word is a GST slab change could hit one of Verve's core categories."},
    # ── KRYS ──
    {"src":"news", "affects":"krys", "direction": 1, "strength":0.13, "real":True, "text":"Kryos Semi-Conductors wins an automotive design from a European automaker."},
    {"src":"news", "affects":"krys", "direction": 1, "strength":0.1, "real":True, "text":"Government fast-tracks smart-meter rollout, lifting Kryos's order book."},
    {"src":"news", "affects":"krys", "direction":-1, "strength":0.13, "real":True, "text":"Taiwan Strait tensions delay wafer shipments to Kryos's foundry partners."},
    {"src":"news", "affects":"krys", "direction":-1, "strength":0.12, "real":True, "text":"US-China export-control changes restrict Kryos's access to advanced design software."},
    {"src":"rumour", "affects":"krys", "direction": 1, "strength":0.1, "real":True, "text":"Whispers: Kryos is close to a second European automotive design win."},
    {"src":"rumour", "affects":"krys", "direction":-1, "strength":0.1, "real":True, "text":"Word is Kryos's Taiwanese foundry will raise wafer prices sharply."},
    # ── TRFM ──
    {"src":"news", "affects":"trfm", "direction": 1, "strength":0.08, "real":True, "text":"TerraFirm Cement benefits as the government lifts highway construction outlays."},
    {"src":"news", "affects":"trfm", "direction": 1, "strength":0.06, "real":True, "text":"TerraFirm's waste-heat recovery plants cut its power bill, lifting margins."},
    {"src":"news", "affects":"trfm", "direction":-1, "strength":0.08, "real":True, "text":"Imported thermal-coal prices spike, squeezing TerraFirm's margins."},
    {"src":"news", "affects":"trfm", "direction":-1, "strength":0.07, "real":True, "text":"The Competition Commission opens a price-fixing inquiry into cement makers, including TerraFirm."},
    {"src":"rumour", "affects":"trfm", "direction": 1, "strength":0.06, "real":True, "text":"Rumour mill: an international conglomerate is eyeing a bid for TerraFirm."},
    {"src":"rumour", "affects":"trfm", "direction":-1, "strength":0.06, "real":True, "text":"Word is a new limestone royalty hike is coming for cement makers."},
    # ── NVST ──
    {"src":"news", "affects":"nvst", "direction": 1, "strength":0.1, "real":True, "text":"NovaSteel wins a long-term supply contract with a leading auto maker for cold-rolled coil."},
    {"src":"news", "affects":"nvst", "direction": 1, "strength":0.08, "real":True, "text":"Anti-dumping duties on cheap imported steel take effect, protecting NovaSteel's pricing."},
    {"src":"news", "affects":"nvst", "direction":-1, "strength":0.1, "real":True, "text":"Coking-coal prices surge, squeezing NovaSteel's margins."},
    {"src":"news", "affects":"nvst", "direction":-1, "strength":0.09, "real":True, "text":"Cheap steel imports from abroad resurface, forcing NovaSteel to cut prices."},
    {"src":"rumour", "affects":"nvst", "direction": 1, "strength":0.08, "real":True, "text":"Whispers: NovaSteel is close to a green-steel offtake deal with a European carmaker."},
    {"src":"rumour", "affects":"nvst", "direction":-1, "strength":0.08, "real":True, "text":"Word is auto demand is softening, which could dent NovaSteel's order book."},
    # ── QNTX ──
    {"src":"news", "affects":"qntx", "direction": 1, "strength":0.13, "real":True, "text":"Quantix Cloud Systems beats guidance as enterprise renewals hit a record."},
    {"src":"news", "affects":"qntx", "direction": 1, "strength":0.1, "real":True, "text":"Quantix launches a new zero-trust platform with a large multinational anchor customer."},
    {"src":"news", "affects":"qntx", "direction":-1, "strength":0.13, "real":True, "text":"Quantix Cloud Systems trims guidance, citing delayed enterprise deal signings."},
    {"src":"news", "affects":"qntx", "direction":-1, "strength":0.12, "real":True, "text":"A rate-hike scare hits long-duration tech valuations; Quantix is sold off."},
    {"src":"rumour", "affects":"qntx", "direction": 1, "strength":0.1, "real":True, "text":"Whispers: Quantix is about to announce a large cybersecurity acquisition."},
    {"src":"rumour", "affects":"qntx", "direction":-1, "strength":0.1, "real":True, "text":"Word is a big customer is moving a Quantix workload in-house."},
    # ── PRMA ──
    {"src":"news", "affects":"prma", "direction": 1, "strength":0.13, "real":True, "text":"Primus AutoWorks wins a state order for 2,000 electric buses."},
    {"src":"news", "affects":"prma", "direction": 1, "strength":0.1, "real":True, "text":"Battery-cell prices fall, easing margin pressure on Primus."},
    {"src":"news", "affects":"prma", "direction":-1, "strength":0.13, "real":True, "text":"EV subsidies are scaled back in the latest budget; Primus is most exposed."},
    {"src":"news", "affects":"prma", "direction":-1, "strength":0.12, "real":True, "text":"Lithium prices spike, squeezing Primus's cost of cells."},
    {"src":"rumour", "affects":"prma", "direction": 1, "strength":0.1, "real":True, "text":"Whispers: Primus is about to sign a battery-swap partnership with a delivery giant."},
    {"src":"rumour", "affects":"prma", "direction":-1, "strength":0.1, "real":True, "text":"Word is a major state may delay payments for its electric bus fleet."},
    # ── GLTL ──
    {"src":"news", "affects":"gltl", "direction": 1, "strength":0.1, "real":True, "text":"Glotech Telecom signs a five-year tower and fibre lease with a major 5G carrier."},
    {"src":"news", "affects":"gltl", "direction": 1, "strength":0.08, "real":True, "text":"Spectrum-auction results leave Glotech's tenants with more capacity to roll out."},
    {"src":"news", "affects":"gltl", "direction":-1, "strength":0.1, "real":True, "text":"The telecom regulator caps tower-lease pricing, a blow to Glotech."},
    {"src":"news", "affects":"gltl", "direction":-1, "strength":0.09, "real":True, "text":"Interest rates rise, increasing Glotech's debt-servicing burden."},
    {"src":"rumour", "affects":"gltl", "direction": 1, "strength":0.08, "real":True, "text":"Whispers: Glotech is nearing a deal to acquire a regional fibre network."},
    {"src":"rumour", "affects":"gltl", "direction":-1, "strength":0.08, "real":True, "text":"Word is a tenant carrier may merge with a rival, cutting Glotech's tenancy ratio."},
    # ── URBN ──
    {"src":"news", "affects":"urbn", "direction": 1, "strength":0.05, "real":True, "text":"UrbanGrid Power gets a regulator-approved tariff hike, protecting its 15.5% return."},
    {"src":"news", "affects":"urbn", "direction": 1, "strength":0.04, "real":True, "text":"UrbanGrid's smart-meter rollout cuts distribution losses, lifting profit."},
    {"src":"news", "affects":"urbn", "direction":-1, "strength":0.05, "real":True, "text":"The power regulator delays UrbanGrid's tariff revision, hitting cash flow."},
    {"src":"news", "affects":"urbn", "direction":-1, "strength":0.05, "real":True, "text":"ESG funds sell down UrbanGrid because of its coal-fired generation assets."},
    {"src":"rumour", "affects":"urbn", "direction": 1, "strength":0.04, "real":True, "text":"Buzz: UrbanGrid is exploring a rooftop-solar partnership in its metro zones."},
    {"src":"rumour", "affects":"urbn", "direction":-1, "strength":0.04, "real":True, "text":"Word is the regulator may cap future returns for grid monopolies."},
    # ── SLRA ──
    {"src":"news", "affects":"slra", "direction": 1, "strength":0.1, "real":True, "text":"Solaris Agrochemicals benefits as a strong monsoon lifts fertiliser demand."},
    {"src":"news", "affects":"slra", "direction": 1, "strength":0.08, "real":True, "text":"Government clears pending subsidy payments owed to Solaris."},
    {"src":"news", "affects":"slra", "direction":-1, "strength":0.1, "real":True, "text":"Monsoon fails in key states, cutting fertiliser demand for Solaris."},
    {"src":"news", "affects":"slra", "direction":-1, "strength":0.09, "real":True, "text":"Natural-gas prices spike, squeezing Solaris's urea margins."},
    {"src":"rumour", "affects":"slra", "direction": 1, "strength":0.08, "real":True, "text":"Whispers: Solaris is close to a long-term gas-supply deal that locks in costs."},
    {"src":"rumour", "affects":"slra", "direction":-1, "strength":0.08, "real":True, "text":"Word is the EU will extend its pesticide-residue ban to Solaris's core exports."},
    # ── MEDV ──
    {"src":"news", "affects":"medv", "direction": 1, "strength":0.08, "real":True, "text":"MedVantage Hospitals reports record oncology and transplant volumes."},
    {"src":"news", "affects":"medv", "direction": 1, "strength":0.06, "real":True, "text":"MedVantage's medical-tourism arrivals jump 20% year on year."},
    {"src":"news", "affects":"medv", "direction":-1, "strength":0.08, "real":True, "text":"Government extends price caps on stents and ICU beds, trimming MedVantage's margins."},
    {"src":"news", "affects":"medv", "direction":-1, "strength":0.07, "real":True, "text":"A malpractice ruling puts MedVantage under regulatory scrutiny."},
    {"src":"rumour", "affects":"medv", "direction": 1, "strength":0.06, "real":True, "text":"Whispers: MedVantage is close to opening a flagship hospital in a new metro."},
    {"src":"rumour", "affects":"medv", "direction":-1, "strength":0.06, "real":True, "text":"Word is insurers will push back hard on MedVantage's tariff increases."},
    # ── NXGN ──
    {"src":"news", "affects":"nxgn", "direction": 1, "strength":0.08, "real":True, "text":"NextGen Retail Malls signs a marquee anchor tenant at its flagship Tier-1 mall."},
    {"src":"news", "affects":"nxgn", "direction": 1, "strength":0.06, "real":True, "text":"NextGen's footfall and tenant sales hit a record, lifting its variable rent."},
    {"src":"news", "affects":"nxgn", "direction":-1, "strength":0.08, "real":True, "text":"Bond yields jump, making NextGen's distributions look less attractive."},
    {"src":"news", "affects":"nxgn", "direction":-1, "strength":0.07, "real":True, "text":"A rival mall opens nearby, pulling footfall from one of NextGen's top assets."},
    {"src":"rumour", "affects":"nxgn", "direction": 1, "strength":0.06, "real":True, "text":"Whispers: NextGen is eyeing a new mall acquisition funded by fresh units."},
    {"src":"rumour", "affects":"nxgn", "direction":-1, "strength":0.06, "real":True, "text":"Word is an anchor tenant may exit one of NextGen's malls at lease end."},
    # ── OCNA ──
    {"src":"news", "affects":"ocna", "direction": 1, "strength":0.1, "real":True, "text":"OceanAir Cargo wins a multi-year pharma cold-chain contract."},
    {"src":"news", "affects":"ocna", "direction": 1, "strength":0.08, "real":True, "text":"Shipping disruptions at sea push more cargo onto OceanAir's freighters."},
    {"src":"news", "affects":"ocna", "direction":-1, "strength":0.1, "real":True, "text":"Jet-fuel prices spike, squeezing OceanAir's margins."},
    {"src":"news", "affects":"ocna", "direction":-1, "strength":0.09, "real":True, "text":"Airport slot fees are raised, adding to OceanAir's costs."},
    {"src":"rumour", "affects":"ocna", "direction": 1, "strength":0.08, "real":True, "text":"Whispers: OceanAir is close to ordering new converted freighters."},
    {"src":"rumour", "affects":"ocna", "direction":-1, "strength":0.08, "real":True, "text":"Word is a major e-commerce partner may build its own air fleet."},
    # ── FLXW ──
    {"src":"news", "affects":"flxw", "direction": 1, "strength":0.1, "real":True, "text":"FlexWare Textiles signs a long-term supply deal for technical textiles with a European buyer."},
    {"src":"news", "affects":"flxw", "direction": 1, "strength":0.08, "real":True, "text":"FlexWare's recycled-packaging range gets a new anchor customer."},
    {"src":"news", "affects":"flxw", "direction":-1, "strength":0.1, "real":True, "text":"Crude oil spikes, raising FlexWare's polymer feedstock costs."},
    {"src":"news", "affects":"flxw", "direction":-1, "strength":0.09, "real":True, "text":"Anti-dumping rules fail to stop cheap imports, hitting FlexWare's pricing."},
    {"src":"rumour", "affects":"flxw", "direction": 1, "strength":0.08, "real":True, "text":"Whispers: FlexWare is about to win a large export order for technical textiles."},
    {"src":"rumour", "affects":"flxw", "direction":-1, "strength":0.08, "real":True, "text":"Word is single-use plastic rules will be tightened for FlexWare's core packaging."},
    # ── ORBT ──
    {"src":"news", "affects":"orbt", "direction": 1, "strength":0.17, "real":True, "text":"Orbit Aerospace's latest imaging satellite deploys successfully, expanding its constellation."},
    {"src":"news", "affects":"orbt", "direction": 1, "strength":0.14, "real":True, "text":"Orbit signs a multi-year geospatial-analytics contract with a defence agency."},
    {"src":"news", "affects":"orbt", "direction":-1, "strength":0.17, "real":True, "text":"Orbit Aerospace's launch is delayed after a third-party rocket fails."},
    {"src":"news", "affects":"orbt", "direction":-1, "strength":0.15, "real":True, "text":"A government licensing hold stops Orbit from selling high-resolution imagery."},
    {"src":"rumour", "affects":"orbt", "direction": 1, "strength":0.13, "real":True, "text":"Whispers: Orbit is about to sign a large agri-insurance data deal."},
    {"src":"rumour", "affects":"orbt", "direction":-1, "strength":0.13, "real":True, "text":"Word is Orbit's next launch window may slip by months."},
    # ── AQUA ──
    {"src":"news", "affects":"aqua", "direction": 1, "strength":0.08, "real":True, "text":"AquaPure Environmental wins a municipal desalination plant order."},
    {"src":"news", "affects":"aqua", "direction": 1, "strength":0.06, "real":True, "text":"A river-cleaning mandate lifts AquaPure's order book."},
    {"src":"news", "affects":"aqua", "direction":-1, "strength":0.08, "real":True, "text":"Municipal clients delay payments to AquaPure, stretching its working capital."},
    {"src":"news", "affects":"aqua", "direction":-1, "strength":0.07, "real":True, "text":"Import duties on membranes raise AquaPure's project costs."},
    {"src":"rumour", "affects":"aqua", "direction": 1, "strength":0.06, "real":True, "text":"Whispers: AquaPure is shortlisted for a big industrial water-recycling project."},
    {"src":"rumour", "affects":"aqua", "direction":-1, "strength":0.06, "real":True, "text":"Word is the environment regulator will soften discharge norms, hurting AquaPure's demand."},
]

FALSE_RUMOURS = [   # NOT true — Truth-or-False event only
    {"src":"rumour", "affects":"zndy", "direction": 1, "strength":0.06, "real":False, "text":"Chatter: Zenith has secured a classified ₹5,000 crore interceptor contract."},
    {"src":"rumour", "affects":"zndy", "direction":-1, "strength":0.06, "real":False, "text":"Talk that the Ministry of Defense plans to cut Zenith's actuator orders by a third."},
    {"src":"rumour", "affects":"abph", "direction": 1, "strength":0.08, "real":False, "text":"Chatter: Aura is about to be named a top PLI scheme beneficiary with a huge payout."},
    {"src":"rumour", "affects":"abph", "direction":-1, "strength":0.08, "real":False, "text":"Talk that a Chinese rival will slash API prices by 40% across Aura's core molecules."},
    {"src":"rumour", "affects":"vtxe", "direction": 1, "strength":0.13, "real":False, "text":"Chatter: Voltix is about to announce its first-ever dividend."},
    {"src":"rumour", "affects":"vtxe", "direction":-1, "strength":0.13, "real":False, "text":"Talk that a Chinese giant will undercut Voltix on every utility tender this year."},
    {"src":"rumour", "affects":"apmb", "direction": 1, "strength":0.04, "real":False, "text":"Chatter: Apex Mercantile is about to declare a bumper special dividend."},
    {"src":"rumour", "affects":"apmb", "direction":-1, "strength":0.04, "real":False, "text":"Talk of a sudden jump in bad loans in Apex Mercantile's wholesale book."},
    {"src":"rumour", "affects":"hblx", "direction": 1, "strength":0.04, "real":False, "text":"Chatter: HarborLogix has won an exclusive new take-or-pay deal worth thousands of crores."},
    {"src":"rumour", "affects":"hblx", "direction":-1, "strength":0.04, "real":False, "text":"Talk that unilateral tariffs will cut container volumes at HarborLogix by a fifth."},
    {"src":"rumour", "affects":"vrve", "direction": 1, "strength":0.04, "real":False, "text":"Chatter: Verve is about to announce a large share buyback."},
    {"src":"rumour", "affects":"vrve", "direction":-1, "strength":0.04, "real":False, "text":"Talk that Verve will hike prices across its hygiene range by double digits."},
    {"src":"rumour", "affects":"krys", "direction": 1, "strength":0.1, "real":False, "text":"Chatter: Kryos is about to announce a ₹3,000 crore smart-grid chip order."},
    {"src":"rumour", "affects":"krys", "direction":-1, "strength":0.1, "real":False, "text":"Talk that a rival is about to win Kryos's smart-meter incumbency."},
    {"src":"rumour", "affects":"trfm", "direction": 1, "strength":0.06, "real":False, "text":"Chatter: TerraFirm has locked in a multi-year government housing supply deal."},
    {"src":"rumour", "affects":"trfm", "direction":-1, "strength":0.06, "real":False, "text":"Talk that TerraFirm will shut a grinding unit for six months."},
    {"src":"rumour", "affects":"nvst", "direction": 1, "strength":0.08, "real":False, "text":"Chatter: NovaSteel will win a giant railway-wagon steel order."},
    {"src":"rumour", "affects":"nvst", "direction":-1, "strength":0.08, "real":False, "text":"Talk that NovaSteel's captive iron-ore lease will not be renewed."},
    {"src":"rumour", "affects":"qntx", "direction": 1, "strength":0.1, "real":False, "text":"Chatter: Quantix has been shortlisted for a billion-dollar government cloud contract."},
    {"src":"rumour", "affects":"qntx", "direction":-1, "strength":0.1, "real":False, "text":"Talk that Quantix's CEO may step down next quarter."},
    {"src":"rumour", "affects":"prma", "direction": 1, "strength":0.1, "real":False, "text":"Chatter: Primus has secured a mega order of 10,000 buses from one city."},
    {"src":"rumour", "affects":"prma", "direction":-1, "strength":0.1, "real":False, "text":"Talk that Primus will recall a bus model over a battery fault."},
    {"src":"rumour", "affects":"gltl", "direction": 1, "strength":0.08, "real":False, "text":"Chatter: Glotech's debt will be refinanced at half its current rate."},
    {"src":"rumour", "affects":"gltl", "direction":-1, "strength":0.08, "real":False, "text":"Talk that equipment-vendor sanctions will halt Glotech's 5G rollout."},
    {"src":"rumour", "affects":"urbn", "direction": 1, "strength":0.04, "real":False, "text":"Chatter: UrbanGrid will announce a huge special dividend."},
    {"src":"rumour", "affects":"urbn", "direction":-1, "strength":0.04, "real":False, "text":"Talk that UrbanGrid will lose one metro-zone licence at renewal."},
    {"src":"rumour", "affects":"slra", "direction": 1, "strength":0.08, "real":False, "text":"Chatter: Solaris will receive a ₹2,000 crore subsidy arrears payout next week."},
    {"src":"rumour", "affects":"slra", "direction":-1, "strength":0.08, "real":False, "text":"Talk that a plant explosion has shut down one of Solaris's urea units."},
    {"src":"rumour", "affects":"medv", "direction": 1, "strength":0.06, "real":False, "text":"Chatter: MedVantage will be acquired by a global hospital chain."},
    {"src":"rumour", "affects":"medv", "direction":-1, "strength":0.06, "real":False, "text":"Talk that a major oncology surgeon team is leaving MedVantage."},
    {"src":"rumour", "affects":"nxgn", "direction": 1, "strength":0.06, "real":False, "text":"Chatter: NextGen will announce a huge special distribution."},
    {"src":"rumour", "affects":"nxgn", "direction":-1, "strength":0.06, "real":False, "text":"Talk that NextGen will face a major rent-relief demand from tenants."},
    {"src":"rumour", "affects":"ocna", "direction": 1, "strength":0.08, "real":False, "text":"Chatter: OceanAir will sign an exclusive deal with a global pharma giant."},
    {"src":"rumour", "affects":"ocna", "direction":-1, "strength":0.08, "real":False, "text":"Talk that OceanAir will ground part of its fleet for inspection."},
    {"src":"rumour", "affects":"flxw", "direction": 1, "strength":0.08, "real":False, "text":"Chatter: FlexWare will be added to a major index."},
    {"src":"rumour", "affects":"flxw", "direction":-1, "strength":0.08, "real":False, "text":"Talk that a polymer plant fire has shut a FlexWare unit."},
    {"src":"rumour", "affects":"orbt", "direction": 1, "strength":0.13, "real":False, "text":"Chatter: Orbit has been picked for a billion-dollar national surveillance programme."},
    {"src":"rumour", "affects":"orbt", "direction":-1, "strength":0.13, "real":False, "text":"Talk that one of Orbit's satellites has lost contact."},
    {"src":"rumour", "affects":"aqua", "direction": 1, "strength":0.06, "real":False, "text":"Chatter: AquaPure will win the nation's largest sewage-treatment contract."},
    {"src":"rumour", "affects":"aqua", "direction":-1, "strength":0.06, "real":False, "text":"Talk that AquaPure's key membrane supplier is halting shipments."},
]


# ─────────────────────────────────────────────────────────────────────────
#  HOST / ORGANISER ONLY — never sent to players.
#  Cross-links and unresolved plot hooks from the company list, for planning
#  manual news drops and chaos events.
# ─────────────────────────────────────────────────────────────────────────
ORGANISER_NOTES = {
    "cross_linkages": [
        "Interest-rate and bond-yield headlines hit NextGen (REIT), Glotech (debt-heavy), Apex Mercantile (margins) and Quantix (valuation) together. UrbanGrid, Verve and MedVantage barely react.",
        "Crude oil is a shared lever: FlexWare and OceanAir fall when it spikes; Solaris reacts to gas, TerraFirm and NovaSteel to coal and coking coal.",
        "Lithium-cell and customs-duty news moves Voltix and Primus together (both buy imported cells). Chinese price cuts (CATL/BYD) hurt both.",
        "Taiwan / export-control headlines hit Kryos, Zenith (optical chips) and Quantix (visa and data rules) in different ways.",
        "Shipping-lane crises are good for OceanAir and bad for HarborLogix — the one stock helped by chaos at sea, the other hurt.",
        "Healthcare moves together on drug-pricing or inspection headlines: Aura BioPharma (US-FDA) and MedVantage (price caps).",
        "Verve, UrbanGrid and HarborLogix are the deliberate low-volatility anchors; Voltix and Orbit are the highest-beta new listings.",
    ],
    "watch_list_hooks": {
        "zndy": ["Titanium alloy shipment delays from Eastern Europe", "Western sanctions on optical microchips", "Extension of the Southeast Asian export pact"],
        "abph": ["Next US-FDA inspection of the Baddi unit", "Chinese API price war", "PLI incentives for specialty APIs"],
        "vtxe": ["Customs duty on imported lithium cells", "Safety / thermal-runaway incidents", "A large utility storage tender"],
        "apmb": ["Reserve-ratio changes", "Priority-sector lending targets", "Foreign investor flows"],
        "hblx": ["Red Sea / shipping-lane disruptions", "Maritime Regulatory Authority tariff review", "Tariffs between trading blocs"],
        "vrve": ["Monsoon and rural demand", "Palm-oil and packaging costs", "FSSAI labelling rules and GST slabs"],
        "krys": ["Taiwan Strait tensions", "National smart-meter mandate", "Semiconductor Mission subsidies"],
        "trfm": ["Rumoured international takeover bid", "Coal prices", "Competition Commission price-fixing inquiry"],
        "nvst": ["Coking-coal prices", "Anti-dumping / safeguard duties", "Green-steel offtake"],
        "qntx": ["Missed-guidance risk", "Data-localization law fines", "H-1B visa restrictions"],
        "prma": ["EV subsidy scheme revision", "Lithium cell prices", "State bus-tender payments"],
        "gltl": ["Spectrum-auction debt", "Tower / fibre tariff caps", "Equipment-vendor sanctions"],
        "urbn": ["Tariff-revision approvals", "ESG selling of coal assets", "Heatwave demand"],
        "slra": ["Monsoon timing", "Late DBT subsidy payouts", "EU insecticide bans (18% of exports)"],
        "medv": ["Stent / ICU price caps", "Medical-tourism visas", "Competition from Thailand and Singapore"],
        "nxgn": ["Interest rates", "FDI rules for multi-brand retail", "Anchor-tenant exits"],
        "ocna": ["Jet-fuel prices", "Slot fees", "Sea-freight disruptions"],
        "flxw": ["Crude oil", "Plastic regulation", "Anti-dumping enforcement"],
        "orbt": ["Third-party launch outcomes", "Ministry of Defense licensing", "Planet Labs competition"],
        "aqua": ["Municipal payment delays", "Membrane import duties", "Environmental enforcement"],
    },
    "game_schedule": [
        "6 rounds of 20 minutes. Rounds 1-2: normal, no chaos events. Rounds 3-6: exactly one chaos event each.",
        "Round 3 — IPO Drop: Voltix Energy and Orbit Aerospace (different sectors) list at round start. Until then they do not exist on the exchange.",
        "Round 4 — Dividend Payout: the 8 dividend payers pay at round start AND again at the 10-minute mark.",
        "Round 5 — Acquisition Rumour: at the 5-minute mark Quantix and Glotech (different sectors) become linked and both move to High volatility until the round ends.",
        "Round 6 — Truth or False: real news and rumours are dropped every 4 minutes, all shown to players as ordinary news. Only the host panel shows which are TRUE and which are FALSE.",
    ],
}


# ─────────────────────────────────────────────────────────────────────────
#  PLOT GROUPS — mutually exclusive outcomes of the SAME storyline.
# ─────────────────────────────────────────────────────────────────────────
PLOT_GROUPS = {
    "zndy_story": ["Southeast Asian export pact is extended", "Southeast Asian export pact is shelved"],
    "abph_story": ["Baddi unit clears its re-inspection", "Baddi unit fails its re-inspection"],
    "vtxe_story": ["safety clearances are reissued in full", "extend the safety probe into Voltix"],
    "apmb_story": ["dividend after a record profit year", "signals further reserve-ratio hikes"],
    "hblx_story": ["HarborLogix raises its dividend again", "freezes port tariffs for a year"],
    "vrve_story": ["lifts its dividend again after a strong", "tightens nutritional labelling norms"],
    "krys_story": ["expands its smart-meter chip share", "Taiwan Strait tensions escalate"],
    "trfm_story": ["a bid is widely expected", "hopes of a takeover bid fade"],
    "nvst_story": ["extends safeguard duties on steel imports", "safeguard duties lapse"],
    "qntx_story": ["announces a buyback", "competitor undercuts it"],
    "prma_story": ["incentives are extended another five years", "incentives are cut sharply"],
    "gltl_story": ["prepays a chunk of debt", "imposes new tower-sharing caps"],
    "urbn_story": ["raises its dividend again, the highest", "rejects UrbanGrid's tariff petition"],
    "slra_story": ["subsidy arrears are cleared in full", "payments to Solaris are delayed again"],
    "medv_story": ["reports record occupancy as oncology", "Price caps on cardiac and orthopaedic procedures are widened"],
    "nxgn_story": ["hikes its distribution per unit", "Anchor tenant announces exit"],
    "ocna_story": ["cargo to OceanAir", "sea freight rates collapse"],
    "flxw_story": ["export orders climb on a weaker rupee", "Cheap imports flood in"],
    "orbt_story": ["constellation launch succeeds", "launch fails; two satellites are lost"],
    "aqua_story": ["clears a large batch of pending municipal bills", "Municipal payments to AquaPure slip further"],
}
