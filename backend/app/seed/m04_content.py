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

# E03 workspaces are built from the HARBORLINE v0.3 E03 student packet (app/seed/harborline.py).
