"""Provisional M04 lesson, P02 development rubric criteria and E03 role-specific assignment templates.

Everything here is DEVELOPMENT CONTENT with approval_status='draft'. The topic outline is taken from the
curriculum workbook (Modules sheet, M04 row). Explanatory text is placeholder pending the approved lesson
plan (source inventory: Digital Evidence/day2_lecture1_lesson_plan.docx, not supplied to this repository).
"""

from __future__ import annotations

LESSON_PROVENANCE = (
    "Topic outline from PACT_Task_Objective_Assessment_Matrix_v0.1.xlsx (Modules!M04, POI Schedule Tue 08:45). "
    "Explanatory text is development placeholder; the source lesson plan "
    "'Digital Evidence/day2_lecture1_lesson_plan.docx' has not been supplied. Requires instructor and SME "
    "review before delivery (QA gate Q09/Q10)."
)

M04_LESSON = {
    "code": "M04-L1",
    "title": "Evidence sources, volatility and collection",
    "duration_minutes": 90,
    "sections": [
        {
            "kind": "callout",
            "heading": "Provisional content",
            "body": (
                "This lesson page is development content for the platform prototype. It is not an approved lesson "
                "plan and must not be used for delivery until reviewed under the content approval workflow."
            ),
        },
        {
            "kind": "list",
            "heading": "Topic outline (from curriculum workbook)",
            "items": [
                "Cloud artifacts",
                "Endpoint artifacts",
                "Network artifacts",
                "Provider records",
                "Identity artifacts",
                "Volatility and custody",
                "Source scoring",
            ],
        },
        {
            "kind": "definitions",
            "heading": "Working notes (placeholder)",
            "items": [
                {
                    "term": "Cloud artifacts",
                    "text": "Service audit logs, file activity and administrative exports held by a cloud provider "
                    "or tenant administrator. Note who exported them, when, and in what format.",
                },
                {
                    "term": "Identity artifacts",
                    "text": "Sign-in, multi-factor and device-registration records. Often short retention on "
                    "lower service tiers.",
                },
                {
                    "term": "Network artifacts",
                    "text": "Firewall, proxy and flow records. Summaries prepared by third parties reflect their "
                    "filtering choices; confirm clock and timezone settings.",
                },
                {
                    "term": "Endpoint artifacts",
                    "text": "Workstation and server state. Volatile data can be lost when a device is powered "
                    "down, remediated or reimaged; examination is a specialist referral.",
                },
                {
                    "term": "Provider records",
                    "text": "Records held by hosting, email or service providers. Retention periods vary and "
                    "disclosure requires appropriate process — a decision point for counsel.",
                },
                {
                    "term": "Volatility and custody",
                    "text": "How quickly a record may change or disappear, and who has handled it. Remediation "
                    "by the victim or a service provider can alter evidence before it is preserved.",
                },
                {
                    "term": "Source scoring",
                    "text": "Recording provenance, limitations and reliability for each source so that later "
                    "conclusions can be traced and weighed.",
                },
            ],
        },
        {
            "kind": "roles",
            "heading": "Common fact pattern, different products",
            "items": [
                {
                    "role": "Investigator",
                    "text": "Produce an evidence preservation and acquisition matrix: which records matter, what "
                    "must be preserved and how quickly, what requires legal review or referral, and next "
                    "steps with owners.",
                },
                {
                    "role": "Intelligence Analyst",
                    "text": "Produce a collection-and-correlation ledger: normalized indicators, relationships "
                    "between sources, provenance and limitations, gaps, and collection priorities.",
                },
            ],
        },
        {
            "kind": "callout",
            "heading": "Boundaries",
            "body": (
                "This course is introductory practitioner training. Identify when to consult examiners, counsel, "
                "partner liaisons and agency resources; do not assert legal authorities or decide referral "
                "outcomes yourself."
            ),
        },
    ],
}

RUBRIC_SOURCE = (
    "Proposed common scoring dimensions, PACT_Curriculum_Architecture_v0.1 §7 ('Common scoring dimension "
    "examples (proposed)'). Workbook Traceability lists P02 criteria as 'Individual criterion TBD'. "
    "DEVELOPMENT PLACEHOLDER — not approved; no cut score or weighting (Action Register B05, QA gate Q12)."
)

P02_CRITERIA = [
    (
        "P02-CD1",
        "Factual accuracy and scope",
        "Assertions correspond to source records and stay within professional/agency authority.",
    ),
    (
        "P02-CD2",
        "Traceability",
        "Key claims or decisions connect to identifiable sources, artifacts or observations.",
    ),
    (
        "P02-CD3",
        "Reasoning",
        "Explanations address alternatives, uncertainty, significance, and decision consequences.",
    ),
    (
        "P02-CD4",
        "Professional output",
        "Deliverable is usable by the intended recipient and clearly identifies next action and owner.",
    ),
]

PRIORITY = ["High", "Medium", "Low"]

INVESTIGATOR_TEMPLATE = {
    "code": "E03-P02-INV",
    "pathway": "investigator",
    "title": "E03 Acquisition Matrix — Investigator",
    "product_name": "Evidence Preservation & Acquisition Matrix",
    "instructions": (
        "Using only the released GLASS HARBOR evidence, prepare an individual evidence preservation and "
        "acquisition matrix. Work independently; this artifact is reviewed as your individual work product. "
        "Cite evidence identifiers (e.g. EV-002) for every claim. Flag decisions that require legal review or "
        "referral rather than deciding them."
    ),
    "sections": [
        {
            "key": "relevant_records",
            "kind": "table",
            "label": "1. Relevant records",
            "prompt": "Identify the records most relevant to the investigation and why. Include records not yet in "
            "hand that you believe exist.",
            "columns": [
                {"key": "record", "label": "Record / evidence"},
                {"key": "relevance", "label": "Why it matters", "wide": True},
                {"key": "priority", "label": "Priority", "options": PRIORITY},
                {"key": "holder", "label": "Holder / custodian"},
            ],
        },
        {
            "key": "preservation",
            "kind": "text",
            "label": "2. Preservation considerations",
            "prompt": "Describe what must be preserved, by whom, and how integrity should be maintained (native "
            "exports, hashes, chain of custody). Note any actions that may already have altered evidence.",
        },
        {
            "key": "volatility",
            "kind": "table",
            "label": "3. Volatility and retention concerns",
            "prompt": "List sources at risk of loss or change. State the estimated window and the timezone you used.",
            "columns": [
                {"key": "source", "label": "Source"},
                {"key": "concern", "label": "Volatility / retention concern", "wide": True},
                {"key": "window", "label": "Estimated window (state TZ)"},
                {"key": "basis", "label": "Basis & confidence"},
            ],
        },
        {
            "key": "legal_triggers",
            "kind": "table",
            "label": "4. Legal-review and referral triggers",
            "prompt": "Identify decision points that require counsel, supervisory approval, specialist or partner "
            "referral. Do not assert that a specific authority applies.",
            "columns": [
                {"key": "decision_point", "label": "Decision point", "wide": True},
                {"key": "reason", "label": "Why review / referral is needed", "wide": True},
                {"key": "route_to", "label": "Route to"},
            ],
        },
        {
            "key": "next_steps",
            "kind": "table",
            "label": "5. Recommended next steps",
            "prompt": "Recommend prioritized next steps with an owner and rationale.",
            "columns": [
                {"key": "action", "label": "Action", "wide": True},
                {"key": "owner", "label": "Owner"},
                {"key": "priority", "label": "Priority", "options": PRIORITY},
                {"key": "rationale", "label": "Rationale", "wide": True},
            ],
        },
    ],
}

ANALYST_TEMPLATE = {
    "code": "E03-P02-ANA",
    "pathway": "analyst",
    "title": "E03 Indicator Exploitation — Intelligence Analyst",
    "product_name": "Collection-and-Correlation Ledger",
    "instructions": (
        "Using only the released GLASS HARBOR evidence, prepare an individual collection-and-correlation ledger. "
        "Work independently; this artifact is reviewed as your individual work product. Record indicators exactly "
        "as observed and in normalized form, keep provenance and limitations with each source, and distinguish "
        "what is observed from what is assessed."
    ),
    "sections": [
        {
            "key": "indicators",
            "kind": "table",
            "label": "1. Technical indicators",
            "prompt": "Extract technical indicators and normalize them (e.g. timestamps to UTC, lower-case domains).",
            "columns": [
                {"key": "raw", "label": "As recorded"},
                {
                    "key": "type",
                    "label": "Type",
                    "options": [
                        "IPv4",
                        "Domain",
                        "Email address",
                        "Account",
                        "User agent",
                        "Device / host",
                        "Other",
                    ],
                },
                {"key": "normalized", "label": "Normalized value"},
                {"key": "first_seen_utc", "label": "First observed (UTC)"},
                {"key": "sources", "label": "Source record(s)"},
            ],
        },
        {
            "key": "relationships",
            "kind": "table",
            "label": "2. Source and entity relationships",
            "prompt": "Describe relationships between indicators, entities and records. State your confidence.",
            "columns": [
                {"key": "entity_a", "label": "Entity / indicator A"},
                {"key": "relationship", "label": "Relationship", "wide": True},
                {"key": "entity_b", "label": "Entity / indicator B"},
                {"key": "sources", "label": "Source(s)"},
                {"key": "confidence", "label": "Confidence", "options": ["Low", "Moderate", "High"]},
            ],
        },
        {
            "key": "provenance",
            "kind": "table",
            "label": "3. Provenance and limitations",
            "prompt": "For each source you rely on, record provenance, limitations and a reliability caveat.",
            "columns": [
                {"key": "source", "label": "Source"},
                {"key": "provenance", "label": "Provenance", "wide": True},
                {"key": "limitations", "label": "Limitations", "wide": True},
                {"key": "caveat", "label": "Reliability caveat"},
            ],
        },
        {
            "key": "gaps",
            "kind": "text",
            "label": "4. Intelligence gaps",
            "prompt": "What do you not know that matters? Distinguish unknowns from assumptions.",
        },
        {
            "key": "collection",
            "kind": "table",
            "label": "5. Collection priorities",
            "prompt": "Recommend prioritized collection requirements linked to the gaps above.",
            "columns": [
                {"key": "rank", "label": "Rank"},
                {"key": "requirement", "label": "Collection requirement", "wide": True},
                {"key": "rationale", "label": "Rationale / gap addressed", "wide": True},
                {"key": "source_holder", "label": "Likely holder"},
            ],
        },
    ],
}
