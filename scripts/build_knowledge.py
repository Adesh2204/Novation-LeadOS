"""Authoring source for the checked-in, synthetic v1 catalog and market fixtures."""

import json
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# Each row describes a business event, its event phrase and relative strength.
CATALOG = {
    "privacy": {
        "name": "Privacy & Data Protection",
        "description": "Personal-data handling creates a credible privacy readiness or implementation need.",
        "clients": [
            "SaaS",
            "Fintech",
            "Healthtech",
            "Edtech",
            "Recruitment",
            "Payroll",
            "E-commerce",
            "Consumer apps",
        ],
        "problem": "New or changing data processing outpaces privacy controls and documented data flows.",
        "buyers": [
            "General Counsel",
            "Privacy Head",
            "DPO",
            "CISO",
            "Compliance Head",
            "India Country Head",
            "HR Head",
        ],
        "services": [
            "Privacy readiness assessment",
            "Data inventory",
            "Data-flow mapping",
            "DPDP gap assessment",
            "Privacy implementation",
            "Managed Privacy Desk",
        ],
        "related": ["ai_governance", "vendor_governance", "corporate_compliance"],
        "events": [
            (
                "INDIA_MARKET_ENTRY",
                "Company announces an India market launch",
                "India market launch",
                25,
            ),
            ("DPO_HIRING", "Company opens a dedicated DPO vacancy", "DPO vacancy", 20),
            (
                "PRIVACY_HIRING",
                "Company recruits a privacy implementation lead",
                "privacy implementation lead",
                20,
            ),
            (
                "DATA_INTENSIVE_SERVICE",
                "Company launches a personal-data-intensive service",
                "personal-data-intensive service",
                23,
            ),
            (
                "CONSUMER_APP_LAUNCH",
                "Company launches a consumer application collecting profiles",
                "consumer application collecting profiles",
                20,
            ),
            (
                "EMPLOYEE_DATA_GROWTH",
                "Company doubles its employee data processing footprint",
                "employee data processing footprint",
                16,
            ),
            (
                "CROSS_BORDER_DATA",
                "Company begins cross-border customer-data processing",
                "cross-border customer-data processing",
                23,
            ),
            (
                "PRIVACY_POLICY_GAP",
                "Company acknowledges gaps in its published privacy policy",
                "gaps in its published privacy policy",
                21,
            ),
            (
                "OUTDATED_PRIVACY_DOCUMENTS",
                "Company reports materially outdated privacy documentation",
                "outdated privacy documentation",
                18,
            ),
            (
                "PRIVACY_QUESTIONNAIRES",
                "Company receives enterprise privacy questionnaires",
                "enterprise privacy questionnaires",
                19,
            ),
            (
                "PERSONAL_DATA_INCIDENT",
                "Company confirms a personal-data exposure incident",
                "personal-data exposure incident",
                25,
            ),
            (
                "SENSITIVE_DATA_PROCESSOR",
                "Company appoints a new sensitive-data processor",
                "new sensitive-data processor",
                22,
            ),
            (
                "PRIVACY_CONTROL_PROGRAMME",
                "Company starts a privacy control implementation programme",
                "privacy control implementation programme",
                23,
            ),
        ],
    },
    "clm": {
        "name": "Contract Lifecycle Management",
        "description": "Growing contract volume or fragmented commercial workflows call for contract operations support.",
        "clients": [
            "SaaS",
            "Manufacturing",
            "Fintech",
            "E-commerce",
            "Professional services",
        ],
        "problem": "Contracts, renewals and obligations are scattered and commercial throughput is constrained.",
        "buyers": [
            "General Counsel",
            "CFO",
            "Procurement Head",
            "Legal Operations",
            "Sales Operations",
            "Commercial Head",
        ],
        "services": [
            "Contract repository",
            "Contract register",
            "Template standardisation",
            "Negotiation playbook",
            "Contract workflow",
            "Obligation tracking",
            "Renewal tracking",
            "Managed Contract Desk",
        ],
        "related": ["legal_operations", "technology_ip", "vendor_governance"],
        "events": [
            (
                "CONTRACT_MANAGER_HIRING",
                "Company opens a contract manager vacancy",
                "contract manager vacancy",
                20,
            ),
            (
                "CONTRACT_BACKLOG",
                "Company reports a growing contract review backlog",
                "contract review backlog",
                25,
            ),
            (
                "RENEWAL_FAILURES",
                "Company reports missed commercial contract renewals",
                "missed commercial contract renewals",
                24,
            ),
            (
                "CONTRACT_VOLUME_SURGE",
                "Company reports a sharp increase in contract volume",
                "increase in contract volume",
                22,
            ),
            (
                "INTERNATIONAL_CUSTOMERS",
                "Company signs its first international enterprise customers",
                "first international enterprise customers",
                18,
            ),
            (
                "PROCUREMENT_TRANSFORMATION",
                "Company begins a procurement workflow transformation",
                "procurement workflow transformation",
                21,
            ),
            (
                "CONTRACT_REPOSITORY_PROJECT",
                "Company launches a contract repository consolidation project",
                "contract repository consolidation",
                22,
            ),
            (
                "TEMPLATE_STANDARDISATION",
                "Company begins standardising commercial contract templates",
                "standardising commercial contract templates",
                21,
            ),
            (
                "OBLIGATION_TRACKING_GAP",
                "Company acknowledges untracked contractual obligations",
                "untracked contractual obligations",
                24,
            ),
            (
                "SALES_CONTRACT_EXPANSION",
                "Company expands enterprise sales contracting operations",
                "enterprise sales contracting operations",
                20,
            ),
            (
                "CONTRACT_TEAM_SCALING",
                "Company expands its contract operations team",
                "contract operations team",
                18,
            ),
            (
                "MULTI_OFFICE_CONTRACTS",
                "Company consolidates contracts across multiple offices",
                "contracts across multiple offices",
                19,
            ),
            (
                "FUNDED_CONTRACT_SCALE",
                "Company allocates new funding to scale contract operations",
                "funding to scale contract operations",
                18,
            ),
        ],
    },
    "vendor_governance": {
        "name": "Vendor & Third-Party Governance",
        "description": "Vendor onboarding, risk and renewal events require coordinated third-party controls.",
        "clients": ["Fintech", "SaaS", "Healthtech", "Manufacturing", "E-commerce"],
        "problem": "Growing third-party dependencies lack consistent intake, reviews and remediation ownership.",
        "buyers": [
            "Procurement Head",
            "General Counsel",
            "Privacy Head",
            "Security Head",
            "Risk Head",
            "CISO",
        ],
        "services": [
            "Vendor intake",
            "Vendor assessment",
            "Contract review",
            "Privacy review",
            "Security evidence coordination",
            "Remediation tracker",
            "Vendor approval workflow",
            "Renewal/exit governance",
        ],
        "related": ["privacy", "clm", "ai_governance"],
        "events": [
            (
                "VENDOR_ONBOARDING_PROGRAMME",
                "Company starts a large vendor onboarding programme",
                "vendor onboarding programme",
                24,
            ),
            (
                "THIRD_PARTY_RISK_HIRING",
                "Company recruits a third-party risk manager",
                "third-party risk manager",
                20,
            ),
            (
                "CLOUD_MIGRATION",
                "Company starts migrating sensitive workloads to cloud vendors",
                "sensitive workloads to cloud vendors",
                22,
            ),
            (
                "PAYROLL_VENDOR_CHANGE",
                "Company appoints a new payroll processing vendor",
                "new payroll processing vendor",
                21,
            ),
            (
                "CRM_IMPLEMENTATION",
                "Company begins a customer-data CRM implementation",
                "customer-data CRM implementation",
                19,
            ),
            (
                "OUTSOURCING_EXPANSION",
                "Company expands outsourcing of critical business processes",
                "outsourcing of critical business processes",
                21,
            ),
            (
                "VENDOR_SECURITY_REVIEWS",
                "Company introduces mandatory vendor security reviews",
                "mandatory vendor security reviews",
                22,
            ),
            (
                "VENDOR_BREACH",
                "Company confirms a breach affecting a service provider",
                "breach affecting a service provider",
                25,
            ),
            (
                "VENDOR_REMEDIATION",
                "Company starts a third-party control remediation programme",
                "third-party control remediation",
                24,
            ),
            (
                "SUPPLIER_RENEWALS",
                "Company launches a major supplier renewal exercise",
                "major supplier renewal exercise",
                19,
            ),
            (
                "VENDOR_EXIT",
                "Company announces exit from a critical technology supplier",
                "exit from a critical technology supplier",
                22,
            ),
            (
                "VENDOR_BASE_GROWTH",
                "Company doubles its active third-party vendor base",
                "active third-party vendor base",
                18,
            ),
            (
                "PROCUREMENT_INTAKE",
                "Company introduces centralised supplier intake",
                "centralised supplier intake",
                20,
            ),
        ],
    },
    "ai_governance": {
        "name": "AI Governance",
        "description": "A concrete AI deployment or control programme creates an AI governance opportunity.",
        "clients": [
            "SaaS",
            "Fintech",
            "Recruitment",
            "Healthtech",
            "Edtech",
            "Professional services",
        ],
        "problem": "AI deployment introduces decisions and sensitive-data processing without documented oversight.",
        "buyers": [
            "General Counsel",
            "Chief Risk Officer",
            "CISO",
            "CTO",
            "AI Governance Lead",
            "HR Head",
            "Product Head",
            "Privacy Head",
        ],
        "services": [
            "AI inventory",
            "AI risk classification",
            "AI-use assessment",
            "Acceptable-use policy",
            "Human oversight framework",
            "Vendor AI review",
            "AI approval process",
            "AI incident/reassessment programme",
        ],
        "related": ["privacy", "vendor_governance", "technology_ip"],
        "events": [
            (
                "AI_RECRUITMENT_SYSTEM",
                "Company launches an AI recruitment decision system",
                "AI recruitment decision system",
                25,
            ),
            (
                "GENERATIVE_AI_ROLLOUT",
                "Company deploys generative AI across its workforce",
                "deploys generative AI",
                23,
            ),
            (
                "AI_PRODUCT_LAUNCH",
                "Company launches an AI product processing customer records",
                "AI product processing customer records",
                22,
            ),
            (
                "AI_CUSTOMER_SERVICE",
                "Company deploys AI customer-service automation",
                "AI customer-service automation",
                21,
            ),
            (
                "RESPONSIBLE_AI_HIRING",
                "Company recruits a responsible AI lead",
                "responsible AI lead",
                20,
            ),
            (
                "AI_GOVERNANCE_HIRING",
                "Company opens an AI governance vacancy",
                "AI governance vacancy",
                20,
            ),
            (
                "AI_POLICY_PROGRAMME",
                "Company announces an AI acceptable-use policy programme",
                "AI acceptable-use policy programme",
                22,
            ),
            (
                "AI_CUSTOMER_CONTROLS",
                "Company receives enterprise requests for AI controls",
                "enterprise requests for AI controls",
                24,
            ),
            (
                "AI_VENDOR_ADOPTION",
                "Company adopts an external AI processing vendor",
                "external AI processing vendor",
                21,
            ),
            (
                "AI_SENSITIVE_DATA",
                "Company starts using sensitive personal data with AI",
                "sensitive personal data with AI",
                25,
            ),
            (
                "AUTOMATED_DECISIONS",
                "Company deploys automated customer eligibility decisions",
                "automated customer eligibility decisions",
                24,
            ),
            (
                "AI_INCIDENT",
                "Company discloses an AI system incident",
                "AI system incident",
                25,
            ),
            (
                "AI_MODEL_INTEGRATION",
                "Company integrates a third-party model into production",
                "third-party model into production",
                20,
            ),
        ],
    },
    "legal_operations": {
        "name": "Legal Operations",
        "description": "Legal workloads and spending need repeatable intake, matter and counsel coordination.",
        "clients": [
            "SaaS",
            "Manufacturing",
            "Fintech",
            "Professional services",
            "E-commerce",
        ],
        "problem": "Legal demand grows faster than matter visibility, counsel oversight and operational capacity.",
        "buyers": ["General Counsel", "Legal Operations Head", "CFO", "Legal Director"],
        "services": [
            "Legal intake",
            "Matter tracker",
            "Deadline tracking",
            "Outside counsel management",
            "Invoice review",
            "Legal spend dashboard",
            "Workload reporting",
            "Legal Operations Desk",
        ],
        "related": ["clm", "investigations_disputes", "corporate_compliance"],
        "events": [
            (
                "LEGAL_OPS_HIRING",
                "Company opens a legal operations head vacancy",
                "legal operations head vacancy",
                22,
            ),
            (
                "LEGAL_BACKLOG",
                "Company reports a growing legal matter backlog",
                "legal matter backlog",
                25,
            ),
            (
                "OUTSIDE_COUNSEL_SPEND",
                "Company announces an outside-counsel spend review",
                "outside-counsel spend review",
                23,
            ),
            (
                "LEGAL_TEAM_SCALING",
                "Company expands its in-house legal team",
                "in-house legal team",
                18,
            ),
            (
                "MULTIPLE_LAW_FIRMS",
                "Company launches coordination across multiple external law firms",
                "multiple external law firms",
                21,
            ),
            (
                "MATTER_MANAGEMENT_PROJECT",
                "Company starts implementing matter management software",
                "matter management software",
                22,
            ),
            (
                "LEGAL_TECH_PROCUREMENT",
                "Company tenders for a legal technology platform",
                "legal technology platform",
                21,
            ),
            (
                "LEGAL_INTAKE_PROJECT",
                "Company launches centralised legal request intake",
                "centralised legal request intake",
                22,
            ),
            (
                "LEGAL_DEADLINE_GAP",
                "Company reports fragmented legal deadline tracking",
                "fragmented legal deadline tracking",
                24,
            ),
            (
                "LEGAL_INVOICE_REVIEW",
                "Company starts auditing external legal invoices",
                "auditing external legal invoices",
                21,
            ),
            (
                "LEGAL_WORKLOAD_GROWTH",
                "Company reports a material rise in active legal matters",
                "rise in active legal matters",
                20,
            ),
            (
                "LEGAL_REPORTING_PROJECT",
                "Company introduces board-level legal workload reporting",
                "legal workload reporting",
                19,
            ),
        ],
    },
    "investigations_disputes": {
        "name": "Investigations & Disputes Support",
        "description": "Reported disputes or allegations create a need for careful evidence and counsel support.",
        "clients": [
            "Manufacturing",
            "Fintech",
            "SaaS",
            "Professional services",
            "E-commerce",
        ],
        "problem": "Complex records and contested assertions need a traceable chronology and counsel-ready evidence.",
        "buyers": [
            "General Counsel",
            "Management",
            "Compliance Head",
            "Risk Head",
            "External Counsel",
            "Board / Audit Committee",
        ],
        "services": [
            "Evidence organisation",
            "Document review",
            "Chronology",
            "Evidence matrix",
            "Interview support",
            "Investigation support",
            "Counsel briefing",
            "Action tracking",
        ],
        "related": ["legal_operations", "vendor_governance", "corporate_compliance"],
        "events": [
            (
                "FRAUD_ALLEGATION",
                "A source reports fraud allegations concerning a company",
                "fraud allegations",
                22,
            ),
            (
                "WHISTLEBLOWER_COMPLAINT",
                "A source reports a whistleblower complaint",
                "whistleblower complaint",
                22,
            ),
            (
                "EMPLOYEE_MISCONDUCT_ALLEGATION",
                "A source reports employee misconduct allegations",
                "employee misconduct allegations",
                20,
            ),
            (
                "SUPPLIER_INVOICE_IRREGULARITY",
                "Company announces review of supplier invoice irregularities",
                "supplier invoice irregularities",
                21,
            ),
            (
                "AUDITOR_RESIGNATION",
                "An auditor resigns citing unresolved records",
                "auditor resigns citing unresolved records",
                20,
            ),
            (
                "COMMERCIAL_DISPUTE",
                "Company announces a commercial contract dispute",
                "commercial contract dispute",
                23,
            ),
            (
                "ARBITRATION_ANNOUNCEMENT",
                "Company announces arbitration proceedings",
                "arbitration proceedings",
                24,
            ),
            (
                "TERMINATION_DISPUTE",
                "Company reports a contract termination dispute",
                "contract termination dispute",
                23,
            ),
            (
                "SHAREHOLDER_DISPUTE",
                "Company reports a shareholder dispute",
                "shareholder dispute",
                22,
            ),
            (
                "REGULATORY_INVESTIGATION",
                "An authority announces a regulatory investigation",
                "regulatory investigation",
                24,
            ),
            (
                "INTERNAL_COMPLAINT_REVIEW",
                "Company starts an internal complaint evidence review",
                "internal complaint evidence review",
                21,
            ),
            (
                "URGENT_EVIDENCE_REVIEW",
                "Company commissions urgent dispute evidence review",
                "urgent dispute evidence review",
                25,
            ),
            (
                "LITIGATION_ANNOUNCEMENT",
                "Company announces material litigation proceedings",
                "material litigation proceedings",
                23,
            ),
        ],
    },
    "transaction_integration": {
        "name": "Transaction Diligence & Integration",
        "description": "A transaction or integration event requires contract and document coordination.",
        "clients": [
            "SaaS",
            "Manufacturing",
            "Fintech",
            "Professional services",
            "Private equity",
        ],
        "problem": "Transactions expose missing documents, consent requirements and post-closing obligations.",
        "buyers": [
            "Deal Counsel",
            "Corporate Development",
            "PE Investment Team",
            "General Counsel",
            "CFO",
            "Integration Lead",
        ],
        "services": [
            "Contract diligence",
            "Data-room organisation",
            "Missing-document tracker",
            "Consent analysis",
            "Amendment tracking",
            "Integration checklist",
            "Post-closing contract integration",
        ],
        "related": ["clm", "corporate_compliance", "technology_ip"],
        "events": [
            (
                "ACQUISITION_ANNOUNCEMENT",
                "Company announces an acquisition agreement",
                "acquisition agreement",
                25,
            ),
            (
                "MERGER_ANNOUNCEMENT",
                "Company announces a merger agreement",
                "merger agreement",
                25,
            ),
            (
                "PE_TRANSACTION",
                "Company enters a private-equity buyout transaction",
                "private-equity buyout transaction",
                24,
            ),
            (
                "PORTFOLIO_ACQUISITION",
                "A portfolio company announces a bolt-on acquisition",
                "bolt-on acquisition",
                23,
            ),
            (
                "ASSET_PURCHASE",
                "Company announces a business asset purchase",
                "business asset purchase",
                22,
            ),
            (
                "STRATEGIC_INVESTMENT",
                "Company announces strategic investment with diligence underway",
                "strategic investment with diligence",
                20,
            ),
            (
                "DUE_DILIGENCE_PROJECT",
                "Company begins contract due diligence",
                "contract due diligence",
                24,
            ),
            (
                "POST_CLOSING_INTEGRATION",
                "Company launches post-closing contract integration",
                "post-closing contract integration",
                25,
            ),
            (
                "CHANGE_OF_CONTROL_CONSENTS",
                "Company starts obtaining change-of-control consents",
                "change-of-control consents",
                24,
            ),
            (
                "DATA_ROOM_PROJECT",
                "Company opens a transaction data room",
                "transaction data room",
                23,
            ),
            (
                "TRANSACTION_RESTRUCTURING",
                "Company starts a transaction-related business restructuring",
                "transaction-related business restructuring",
                21,
            ),
            (
                "MISSING_DILIGENCE_DOCUMENTS",
                "Company identifies missing documents during diligence",
                "missing documents during diligence",
                24,
            ),
        ],
    },
    "technology_ip": {
        "name": "Technology Contracts & IP",
        "description": "Technology commercialisation and development events need clear licensing and IP terms.",
        "clients": ["SaaS", "Technology", "Fintech", "Healthtech", "Edtech"],
        "problem": "Licensing, development and enterprise procurement create unclear risk and ownership terms.",
        "buyers": [
            "Founder",
            "General Counsel",
            "Commercial Head",
            "Product Head",
            "CTO",
            "Procurement",
            "Sales Leadership",
        ],
        "services": [
            "Software licence",
            "SaaS agreements",
            "Cloud agreements",
            "IP licensing",
            "IP assignments",
            "Development agreements",
            "Statements of work",
            "Reseller agreements",
            "Open-source licence review",
            "Technology contracting desk",
        ],
        "related": ["clm", "ai_governance", "transaction_integration"],
        "events": [
            (
                "ENTERPRISE_SAAS_SALES",
                "Company launches an enterprise SaaS sales programme",
                "enterprise SaaS sales programme",
                23,
            ),
            (
                "SOFTWARE_PRODUCT_LAUNCH",
                "Company launches a commercial software product",
                "commercial software product",
                20,
            ),
            (
                "LICENSING_PROGRAMME",
                "Company introduces a software licensing programme",
                "software licensing programme",
                24,
            ),
            (
                "RESELLER_PARTNERSHIP",
                "Company signs a software reseller partnership",
                "software reseller partnership",
                22,
            ),
            (
                "TECH_INTERNATIONAL_EXPANSION",
                "Company expands software licensing into foreign markets",
                "software licensing into foreign markets",
                21,
            ),
            (
                "DEVELOPMENT_OUTSOURCING",
                "Company outsources a major software development project",
                "major software development project",
                22,
            ),
            (
                "DEVELOPMENT_CONTRACT",
                "Company signs a major custom development contract",
                "major custom development contract",
                23,
            ),
            (
                "IP_OWNERSHIP_REVIEW",
                "Company announces review of software IP ownership",
                "software IP ownership",
                24,
            ),
            (
                "OPEN_SOURCE_REVIEW",
                "Company starts an open-source licence compliance review",
                "open-source licence compliance review",
                22,
            ),
            (
                "WHITE_LABEL_AGREEMENT",
                "Company enters a white-label software agreement",
                "white-label software agreement",
                22,
            ),
            (
                "ROYALTY_ARRANGEMENT",
                "Company introduces an IP royalty arrangement",
                "IP royalty arrangement",
                20,
            ),
            (
                "ENTERPRISE_TECH_NEGOTIATION",
                "Company enters a major enterprise technology negotiation",
                "enterprise technology negotiation",
                24,
            ),
            (
                "SAAS_PRICING_CHANGE",
                "Company introduces a new usage-based SaaS pricing model",
                "usage-based SaaS pricing model",
                18,
            ),
        ],
    },
    "corporate_compliance": {
        "name": "Corporate Compliance & Entity Coordination",
        "description": "Entity growth and reporting changes require organised calendars and professional coordination.",
        "clients": [
            "SaaS",
            "Fintech",
            "Manufacturing",
            "Professional services",
            "Foreign subsidiary",
        ],
        "problem": "Multiple entities, advisers and deadlines obscure accountability and filing evidence.",
        "buyers": [
            "India Country Head",
            "CFO",
            "Finance Head",
            "Company Secretary",
            "General Counsel",
            "Parent-company Legal",
        ],
        "services": [
            "Entity register",
            "Compliance calendar",
            "Responsibility matrix",
            "Professional coordination",
            "Approval tracking",
            "Filing evidence",
            "Deadline tracking",
            "Monthly compliance reporting",
        ],
        "related": ["privacy", "transaction_integration", "legal_operations"],
        "events": [
            (
                "INDIA_SUBSIDIARY",
                "Company forms an Indian subsidiary",
                "forms an Indian subsidiary",
                25,
            ),
            (
                "MULTIPLE_INDIAN_ENTITIES",
                "Company consolidates oversight of multiple Indian entities",
                "multiple Indian entities",
                22,
            ),
            (
                "DIRECTOR_CHANGE_PROGRAMME",
                "Company coordinates director changes across several entities",
                "director changes across several entities",
                18,
            ),
            (
                "CORPORATE_RESTRUCTURING",
                "Company announces a group entity restructuring",
                "group entity restructuring",
                23,
            ),
            (
                "FILING_PROBLEMS",
                "Company reports missed corporate filing deadlines",
                "missed corporate filing deadlines",
                25,
            ),
            (
                "ENTITY_RECORD_FRAGMENTATION",
                "Company reports fragmented entity records",
                "fragmented entity records",
                24,
            ),
            (
                "COMPLIANCE_HIRING",
                "Company recruits a corporate compliance manager",
                "corporate compliance manager",
                20,
            ),
            (
                "RAPID_ENTITY_GROWTH",
                "Company adds several new operating entities",
                "new operating entities",
                21,
            ),
            (
                "NEW_STATE_OFFICE",
                "Company opens offices across new Indian states",
                "offices across new Indian states",
                18,
            ),
            (
                "PARENT_REPORTING",
                "Company introduces parent-company entity reporting",
                "parent-company entity reporting",
                21,
            ),
            (
                "ADVISER_COORDINATION",
                "Company consolidates coordination of corporate advisers",
                "coordination of corporate advisers",
                20,
            ),
            (
                "COMPLIANCE_CALENDAR_GAP",
                "Company acknowledges gaps in its compliance calendar",
                "gaps in its compliance calendar",
                24,
            ),
        ],
    },
}

CROSS = {
    "INDIA_MARKET_ENTRY": ["corporate_compliance", "clm"],
    "AI_RECRUITMENT_SYSTEM": ["privacy"],
    "AI_SENSITIVE_DATA": ["privacy"],
    "SENSITIVE_DATA_PROCESSOR": ["vendor_governance"],
    "PAYROLL_VENDOR_CHANGE": ["privacy"],
    "POST_CLOSING_INTEGRATION": ["clm"],
    "INDIA_SUBSIDIARY": ["privacy"],
}

# Curated starting service for every event, aligned to each vertical's event list.
# Retrieval uses this business mapping as a prior, then ranks related services semantically.
SERVICE_INDEX = {
    "privacy": [0, 5, 4, 1, 2, 1, 2, 3, 3, 5, 4, 2, 4],
    "clm": [7, 4, 6, 1, 3, 4, 0, 2, 5, 4, 7, 0, 1],
    "vendor_governance": [0, 1, 1, 3, 3, 2, 4, 5, 5, 7, 7, 0, 6],
    "ai_governance": [2, 3, 1, 4, 3, 0, 3, 6, 5, 2, 4, 7, 5],
    "legal_operations": [7, 1, 5, 6, 3, 1, 0, 0, 2, 4, 6, 6],
    "investigations_disputes": [0, 5, 4, 3, 1, 2, 6, 3, 6, 5, 4, 1, 7],
    "transaction_integration": [0, 3, 1, 6, 0, 0, 0, 6, 3, 1, 5, 2],
    "technology_ip": [1, 0, 0, 7, 3, 5, 6, 4, 8, 1, 3, 9, 1],
    "corporate_compliance": [0, 0, 2, 3, 5, 0, 7, 0, 1, 7, 3, 1],
}


def write(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n")


def build():
    signals = []
    for vid, v in CATALOG.items():
        events = v["events"]
        definition = {
            "id": vid,
            "name": v["name"],
            "description": v["description"],
            "typical_client": v["clients"],
            "typical_problem": v["problem"],
            "buyer_roles": v["buyers"],
            "services": v["services"],
            "deliverables": [
                f"Documented {s.lower()} with owners, evidence and next actions"
                for s in v["services"]
            ],
            "positive_signals": [e[0] for e in events],
            "negative_signals": [
                "Programme already completed",
                "No operational change",
                "Source retracts the event",
            ],
            "disqualifiers": [
                "Company explicitly denies the event",
                "Event refers to a different company",
            ],
            "follow_on_services": v["services"][-2:],
            "related_verticals": v["related"],
            "keywords": [e[2] for e in events],
            "semantic_queries": [
                f"Find companies where {e[1].lower()} and identify primary-source evidence"
                for e in events[:4]
            ],
            "default_signal_weights": {e[0]: e[3] for e in events},
            "version": "1.0.0",
        }
        # JSON is a strict subset of YAML; no runtime authoring is required.
        write(ROOT / f"knowledge/verticals/{vid}.yaml", definition)
        for event_index, (sid, description, phrase, strength) in enumerate(events):
            signals.append(
                {
                    "signal_id": sid,
                    "name": sid.replace("_", " ").title(),
                    "description": description + ".",
                    "vertical_ids": [vid, *CROSS.get(sid, [])],
                    "keywords": [phrase],
                    "semantic_description": f"An actual announced business event: {description.lower()}. General discussion of the topic is insufficient.",
                    "base_strength": strength,
                    "recency_decay": "standard",
                    "source_reliability_requirement": 0.7,
                    "possible_buyers": [
                        "General Counsel",
                        "HR Head",
                        "CISO",
                        "Privacy Head",
                    ]
                    if sid == "AI_RECRUITMENT_SYSTEM"
                    else v["buyers"][:4],
                    "possible_services": list(
                        dict.fromkeys(
                            [
                                v["services"][SERVICE_INDEX[vid][event_index]],
                                *v["services"][:3],
                            ]
                        )
                    ),
                    "disqualifiers": [
                        "no operational change",
                        "has not deployed",
                        "event denied",
                        "programme already completed",
                    ],
                    "examples": [
                        f"Example Co announced: {description.removeprefix('Company ').removeprefix('A source reports ')}."
                    ],
                    "version": "1.0.0",
                }
            )
    write(ROOT / "knowledge/signals/catalog.yaml", signals)
    write(
        ROOT / "knowledge/scoring.json",
        {
            "version": "1.0.0",
            "components": {
                "identifiable_need": 25,
                "icp_fit": 20,
                "trigger_strength": 20,
                "trigger_recency": 10,
                "mandate_value": 10,
                "buyer_reachability": 5,
                "expertise_match": 5,
                "evidence_quality": 5,
            },
            "signal_strength_max": 25,
            "recency": [
                {"max_days": 7, "factor": 1},
                {"max_days": 30, "factor": 0.8},
                {"max_days": 90, "factor": 0.5},
                {"max_days": 180, "factor": 0.2},
                {"max_days": 1000000, "factor": 0},
            ],
            "bands": [
                {"min": 80, "name": "HOT"},
                {"min": 65, "name": "STRONG"},
                {"min": 50, "name": "MONITOR"},
                {"min": 0, "name": "IGNORE"},
            ],
            "verified_confidence_min": 0.7,
            "high_confidence_min": 0.85,
        },
    )
    make_fixtures()
    print(
        f"Authored {len(CATALOG)} verticals, {len(signals)} signals and 40 companies."
    )


def make_fixtures():
    anchor = date(2026, 10, 6)
    docs = []
    names = {
        "privacy": ["Meridian Health Cloud", "Veda Payroll", "Harbor Consumer Labs"],
        "clm": ["Keystone Commerce", "Aster Manufacturing", "Summit Sales Cloud"],
        "vendor_governance": ["Cedar Fintech", "Beacon Logistics", "Saffron Retail"],
        "ai_governance": ["Atlas AI Systems", "Orion Advisory", "Nimbus Products"],
        "legal_operations": [
            "Northstar Industries",
            "Juniper Group",
            "Cobalt Services",
        ],
        "investigations_disputes": [
            "Clearwater Holdings",
            "Tamarind Supply",
            "Granite Components",
        ],
        "transaction_integration": [
            "Pioneer Capital",
            "Maple Software",
            "Silverline Assets",
        ],
        "technology_ip": ["Lattice Software", "Prism Technologies", "Vector Licensing"],
        "corporate_compliance": [
            "Bluebird Global",
            "Horizon Entities",
            "Lotus Holdings",
        ],
    }

    def document(name, snippet, *, age=3, confidence=0.95, kind="FACT", **overrides):
        domain = name.lower().replace(" ", "-") + ".example"
        d = {
            "company": {
                "name": name,
                "aliases": [],
                "domain": domain,
                "country": "India",
                "sector": "SaaS",
                "employee_range": "201-500",
                "funding_stage": "Series B",
                "locations": ["Bengaluru"],
                "description": f"Synthetic fixture company: {name}.",
            },
            "source_url": f"https://{domain}/news/{len(docs) + 1}",
            "source_name": f"{name} fixture newsroom",
            "source_type": "fixture_primary",
            "published_date": str(anchor - timedelta(days=age))
            if age is not None
            else None,
            "snippet": f"{name}: {snippet}",
            "confidence": confidence,
            "assertion_type": kind,
            "company_match": True,
            "conflict": False,
            "author": "Mock Market",
            "jurisdiction": "India",
            "language": "en",
        }
        d.update(overrides)
        docs.append(d)
        return d

    for vid, group in names.items():
        for index, name in enumerate(group):
            event = CATALOG[vid]["events"][
                6 if vid == "investigations_disputes" and index == 2 else index
            ]
            kind = (
                "ALLEGATION"
                if vid == "investigations_disputes" and index < 2
                else "FACT"
            )
            doc = document(name, event[1] + ".", age=[3, 15, 55][index], kind=kind)
            doc["company"]["sector"] = CATALOG[vid]["clients"][
                index % len(CATALOG[vid]["clients"])
            ]
            doc["company"]["employee_range"] = ["201-500", "501-1000", "51-200"][index]
            if name == "Atlas AI Systems":
                doc["company"]["sector"] = "Recruitment"
    document("Quiet AI Media", "Publishes a blog mentioning AI. No operational change.")
    document(
        "Funding Only Ventures",
        "Announces Series B funding, without a legal operations programme.",
    )
    document(
        "New CFO Enterprises", "Appoints a new CFO; no governance problem is reported."
    )
    document(
        "Stale Contract Works",
        "Company reports a growing contract review backlog.",
        age=400,
    )
    document(
        "Weak AI Rumors",
        "Company launches an AI recruitment decision system.",
        confidence=0.35,
        source_type="fixture_rumour",
    )
    document("Undated Privacy Labs", "Company opens a dedicated DPO vacancy.", age=None)
    document(
        "Conflicted Vendor Co",
        "Company starts a large vendor onboarding programme.",
        conflict=True,
    )
    document(
        "Wrong Entity News",
        "Unrelated Company forms an Indian subsidiary.",
        company_match=False,
    )
    document("Empty Evidence Co", "", confidence=0)
    document(
        "Denial AI Systems",
        "Company has not deployed an AI recruitment decision system. Event denied.",
    )
    document("Twin Name", "Company begins contract due diligence.")
    twin = document("Twin Name", "Company introduces a software licensing programme.")
    twin["company"]["domain"] = "twin-name-uk.example"
    twin["company"]["country"] = "United Kingdom"
    twin["source_url"] = "https://twin-name-uk.example/news/licensing"
    document(
        "Multi Signal Systems",
        "Company launches an AI recruitment decision system. Company forms an Indian subsidiary.",
    )
    # Different aliases and source documents for the same real-world event.
    atlas = next(d for d in docs if d["company"]["name"] == "Atlas AI Systems")
    alias = json.loads(json.dumps(atlas))
    alias["company"]["name"] = "Atlas AI Systems Pvt Ltd"
    alias["company"]["aliases"] = ["Atlas AI Systems"]
    alias["source_url"] += "?utm_source=duplicate"
    docs.append(alias)
    docs.append(json.loads(json.dumps(atlas)))
    corroboration = json.loads(json.dumps(atlas))
    corroboration["source_url"] = "https://market-journal.example/atlas-launch"
    corroboration["source_name"] = "Mock Market Journal"
    corroboration["source_type"] = "fixture_trade_press"
    corroboration["snippet"] += (
        " The company confirmed the programme in a separate release."
    )
    docs.append(corroboration)
    docs.append({**atlas, "source_url": "not-a-url"})
    write(
        ROOT / "fixtures/market.json",
        {"reference_date": str(anchor), "synthetic": True, "documents": docs},
    )


if __name__ == "__main__":
    build()
