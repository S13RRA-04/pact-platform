"""Case HARBORLINE — the platform's scenario, built from the PACT reinforcing exercise suite v0.3.

Nothing here is authored curriculum: every record, briefing, answer key and knowledge-check item is read
from the suite's own files at install time (paths below), so the platform shows exactly what the course
materials say. The few labels this module adds (inject titles, item codes, provenance notes) say where the
content came from and are not instructional content.

Sources (relative to the repository):
  pact curriculum/PACT_Instructor_Exercise_Master_v0.3/
    Student/Case_Records/Day{1-4}/*.csv|*.txt   → evidence library (one record = one evidence item)
    Student/E03_Student_Packet.docx             → E03 investigator/analyst workspaces (tasks + response grids)
    Instructor/PACT_HARBORLINE_Instructor_Master_v0.3.docx      → release checklists, answer keys
    Instructor/PACT_HARBORLINE_Annotated_Instructor_Key_v0.3.docx → per-source key rows
    Instructor/PACT_Development_Knowledge_Checks_v0.3.docx       → K01/K02 development items
"""

from __future__ import annotations

import csv
import re
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from app.config import REPO_ROOT
from app.curriculum_import.exercise_suite import docx_text

SUITE_DIR = REPO_ROOT / "pact curriculum" / "PACT_Instructor_Exercise_Master_v0.3"
CASE_CODE = "HARBORLINE"
SCENARIO_VERSION = "0.3"

# Exercises in delivery order: (exercise, deck/module, record batch released first in this exercise).
# Batches come from each exercise's "Only release current record(s)" checklist in the Instructor Master,
# minus records already released by an earlier exercise. H-PXY-02 is listed in the Day 2 source index but in
# no checklist; it is released with E03 because the faculty release plan releases the "Day2 proxy" records
# for Tuesday morning (recorded in docs/OPEN_DECISIONS.md for curriculum-owner confirmation).
EXERCISES: list[tuple[str, str | None, list[list[str]]]] = [
    ("E00", None, [["H-INT-01"]]),
    ("E01", "M01", [["H-IDP-01", "H-IDP-02", "H-EDR-01", "H-IAM-01", "H-DNS-01", "H-EDR-02"]]),
    ("E02", "M02", [["H-VND-01"]]),
    ("EPROV", "M03", [["H-AI-01"]]),
    ("E03", "M04", [["H-PXY-01", "H-PXY-02", "H-IR-01"]]),
    ("E04", "M05", [["H-FIN-01", "H-FIN-02"]]),
    ("E05", "M06", [["H-LAB-02"]]),
    ("E06", "M07", [["H-LAB-01"], ["H-LAB-03"]]),  # faculty plan: H-LAB-01, then -02, then -03
    ("E07", "M08", [["H-FOR-01", "H-FOR-02"]]),
    ("E08", "M09", [["H-ATR-01"]]),
    ("P05", "M10", []),
]
HEADER_RE = re.compile(r"^(E\d{2}|EPROV|P05)  \|  (.+)$", re.M)
TS_RE = re.compile(r"(\d{4}-\d{2}-\d{2})[ T](\d{2}:\d{2}:\d{2})Z")


@dataclass
class Record:
    code: str
    day: str
    source_type: str
    observation: str
    limitation: str
    raw: list[tuple[str, str]] = field(default_factory=list)  # (file, rendered raw lines)
    timestamp: datetime | None = None
    as_recorded: str = "Not recorded in source"


def load_records(suite: Path = SUITE_DIR) -> dict[str, Record]:
    base = suite / "Student" / "Case_Records"
    records: dict[str, Record] = {}
    for day_dir in sorted(base.glob("Day*")):
        index = day_dir / f"{day_dir.name}_source_index.csv"
        with index.open(encoding="utf-8-sig", newline="") as fh:
            for row in csv.DictReader(fh):
                rec = Record(
                    row["record_id"],
                    row["release"],
                    row["source_type"],
                    row["record_observation"],
                    row["known_limitation"],
                )
                match = TS_RE.search(rec.observation)
                if match:
                    rec.timestamp = datetime.fromisoformat(f"{match.group(1)}T{match.group(2)}+00:00")
                    rec.as_recorded = f"{match.group(1)} {match.group(2)}Z (UTC)"
                records[rec.code] = rec
        for raw in sorted(day_dir.iterdir()):
            if raw == index or raw.suffix not in (".csv", ".txt"):
                continue
            if raw.suffix == ".csv":
                with raw.open(encoding="utf-8-sig", newline="") as fh:
                    for row in csv.DictReader(fh):
                        rec = records.get(row.get("record_id", ""))
                        if rec is None:
                            continue
                        lines = "\n".join(f"{k}: {v}" for k, v in row.items() if k != "record_id")
                        rec.raw.append((raw.name, lines))
                        stamp = row.get("timestamp_raw") or row.get("timestamp_utc")
                        if stamp:
                            basis = row.get("time_basis") or "UTC"
                            rec.as_recorded = f"{stamp} ({basis}, as recorded)"
            else:
                # A record starts at a line "H-XXX-NN | ..."; following lines without a record id continue it.
                current: tuple[str, list[str]] | None = None
                found: list[tuple[str, list[str]]] = []
                for line in raw.read_text(encoding="utf-8-sig").splitlines():
                    code = line.split("|", 1)[0].strip()
                    if "|" in line and code in records:
                        current = (code, [line.strip()])
                        found.append(current)
                    elif current is not None and line.strip():
                        current[1].append(line.strip())
                for code, lines in found:
                    records[code].raw.append((raw.name, "\n".join(lines)))
    return records


def evidence_specs(records: dict[str, Record]) -> list[dict]:
    specs = []
    for seq, rec in enumerate(records.values(), start=1):
        content = rec.observation
        for name, lines in rec.raw:
            content += f"\n\nRaw record ({name}):\n{lines}"
        files = ", ".join(sorted({n for n, _ in rec.raw})) or "none"
        specs.append(
            {
                "code": rec.code,
                "sequence": seq,
                "title": rec.source_type,
                "source_type": rec.source_type,
                "observed_at": rec.timestamp,
                "observed_timezone": "UTC" if rec.timestamp else None,
                "observed_as_recorded": rec.as_recorded,
                "provenance": (
                    f"HARBORLINE v0.3 {rec.day} release. Source index: {rec.day}_source_index.csv; raw "
                    f"record file(s): {files}. Collector, export method and custody chain are not stated "
                    "in the source."
                ),
                "limitations": rec.limitation,
                "content": content,
            }
        )
    return specs


def _blocks(text: str, end_marker: str | None = None) -> dict[str, tuple[str, str]]:
    """Split a master/key document into {exercise: (title, block text)}."""
    if end_marker and end_marker in text:
        text = text.split(end_marker, 1)[0]
    heads = list(HEADER_RE.finditer(text))
    out = {}
    for i, h in enumerate(heads):
        end = heads[i + 1].start() if i + 1 < len(heads) else len(text)
        out[h.group(1)] = (h.group(2).strip(), text[h.start() : end].strip())
    return out


def _tidy(block: str) -> str:
    """Make extracted table text readable: one cell per line, no stray separators."""
    block = re.sub(r"\n \| ", "\n", block)
    block = re.sub(r" \| \n", "\n", block)
    return re.sub(r"\n{3,}", "\n\n", block).strip()


@dataclass
class SuiteContent:
    titles: dict[str, str]
    master: dict[str, str]
    key: dict[str, str]
    k01: str
    k02: str
    k01_key: str
    k02_key: str
    e03_packet: str


def load_suite(suite: Path = SUITE_DIR) -> SuiteContent:
    instr = suite / "Instructor"
    master = _blocks(
        docx_text(instr / "PACT_HARBORLINE_Instructor_Master_v0.3.docx"),
        end_marker="Objective-by-objective provisional evaluation grid",
    )
    key = _blocks(docx_text(instr / "PACT_HARBORLINE_Annotated_Instructor_Key_v0.3.docx"))
    kc = docx_text(instr / "PACT_Development_Knowledge_Checks_v0.3.docx")
    preamble, _, rest = kc.partition("\nK01\n")
    k01_full, _, k02_full = rest.partition("\nK02\n")
    note = next((ln for ln in preamble.splitlines() if ln.startswith("These questions")), "")

    def strip_keys(part: str) -> str:
        return "\n".join(ln for ln in part.splitlines() if not ln.startswith("INSTRUCTOR KEY")).strip()

    return SuiteContent(
        titles={k: v[0] for k, v in master.items()},
        master={k: _tidy(v[1]) for k, v in master.items()},
        key={k: _tidy(v[1]) for k, v in key.items()},
        k01=strip_keys(k01_full),
        k02=strip_keys(k02_full),
        k01_key=f"{note}\n\n{k01_full.strip()}",
        k02_key=f"{note}\n\n{k02_full.strip()}",
        e03_packet=docx_text(suite / "Student" / "E03_Student_Packet.docx"),
    )


def _packet_line(packet: str, starts: str) -> str:
    return next((ln.strip() for ln in packet.splitlines() if ln.strip().startswith(starts)), "")


def _section(packet: str, heading: str, stop: tuple[str, ...]) -> list[str]:
    lines, capture = [], False
    for ln in packet.splitlines():
        s = ln.strip()
        if s == heading:
            capture = True
            continue
        if capture and s in stop:
            break
        if capture and s:
            lines.append(s)
    return lines


def e03_templates(content: SuiteContent) -> list[dict]:
    """Investigator and analyst workspaces built from the E03 student packet text and its response grids."""
    p = content.e03_packet
    stops = (
        "Shared tasks — all students",
        "Investigator pathway",
        "Intelligence analyst pathway",
        "Submission and handoff",
        "Student response grids",
    )
    shared = _section(p, "Shared tasks — all students", stops)
    inv = _section(p, "Investigator pathway", stops)
    ana = _section(p, "Intelligence analyst pathway", stops)
    submission = _section(p, "Submission and handoff", stops)
    goal = _packet_line(p, "Prioritize time-sensitive records")
    records = _packet_line(p, "H-IDP-01")

    def instructions(path_tasks: list[str], label: str) -> str:
        return "\n".join(
            [
                goal,
                "",
                f"Release / source records: {records}",
                "",
                "Shared tasks — all students:",
                *[f"• {t}" for t in shared],
                "",
                f"{label}:",
                *[f"• {t}" for t in path_tasks],
                "",
                "Submission and handoff:",
                *submission,
            ]
        )

    prioritization = {
        "key": "evidence_prioritization",
        "kind": "table",
        "label": "1. Evidence prioritization",
        "prompt": shared[0] + " " + shared[1] if len(shared) > 1 else "",
        "columns": [
            {"key": "source_id", "label": "Source ID"},
            {
                "key": "record_kind",
                "label": "Raw record / alert / victim interpretation / external lead",
                "options": ["Raw record", "Alert", "Victim interpretation", "External lead"],
            },
            {"key": "question", "label": "Question", "wide": True},
            {"key": "volatility", "label": "Volatility"},
            {"key": "preservation", "label": "Preservation / acquisition", "wide": True},
            {"key": "legal_review", "label": "Legal / examiner review"},
        ],
    }
    alternate = {
        "key": "alternate_explanation",
        "kind": "text",
        "label": "Alternate explanation",
        "prompt": shared[2] if len(shared) > 2 else "",
    }
    decision = {
        "key": "priority_decision",
        "kind": "table",
        "label": "Priority decision",
        "prompt": "",
        "columns": [
            {"key": "action", "label": "Action", "wide": True},
            {"key": "rationale", "label": "Rationale", "wide": True},
            {"key": "owner", "label": "Owner"},
            {"key": "approval_gap", "label": "Approval / gap"},
        ],
    }
    reflection = [
        {
            "key": "reflection_statement",
            "kind": "text",
            "label": "Individual reflection — defensible statement",
            "prompt": "One statement I can defend from the source.",
        },
        {
            "key": "reflection_gap",
            "kind": "text",
            "label": "Individual reflection — gap or alternate explanation",
            "prompt": "One consequential gap or alternate explanation.",
        },
        {
            "key": "reflection_action",
            "kind": "text",
            "label": "Individual reflection — action and owner",
            "prompt": "One action/referral and responsible owner.",
        },
    ]
    inv_sections = [
        prioritization,
        {
            "key": "acquisition_matrix",
            "kind": "table",
            "label": "2. Preservation / acquisition matrix",
            "prompt": inv[0] if inv else "",
            "columns": [
                {"key": "source_id", "label": "Source ID"},
                {"key": "custodian", "label": "Custodian"},
                {"key": "relevance", "label": "Relevance", "wide": True},
                {"key": "dependencies", "label": "Counsel / examiner dependencies"},
                {"key": "integrity", "label": "Integrity / chain record"},
                {"key": "next_owner", "label": "Next owner"},
            ],
        },
        {
            "key": "top_priorities",
            "kind": "text",
            "label": "3. Two highest priorities",
            "prompt": inv[1] if len(inv) > 1 else "",
        },
        {**alternate, "label": "4. " + alternate["label"]},
        {**decision, "label": "5. " + decision["label"]},
        *reflection,
    ]
    ana_sections = [
        prioritization,
        {
            "key": "correlation_ledger",
            "kind": "table",
            "label": "2. Analyst correlation ledger",
            "prompt": ana[0] if ana else "",
            "columns": [
                {"key": "source_id", "label": "Source ID"},
                {"key": "timestamp", "label": "Timestamp (normalized)"},
                {"key": "indicator", "label": "Indicator"},
                {"key": "interpretation", "label": "Interpretation", "wide": True},
                {"key": "competing_explanation", "label": "Competing explanation", "wide": True},
                {"key": "missing_fields", "label": "Missing fields"},
            ],
        },
        {
            "key": "theft_test",
            "kind": "text",
            "label": "3. Records that could test theft",
            "prompt": ana[1] if len(ana) > 1 else "",
        },
        {**alternate, "label": "4. " + alternate["label"]},
        {**decision, "label": "5. " + decision["label"]},
        *reflection,
    ]
    return [
        {
            "code": "E03-P02-INV",
            "pathway": "investigator",
            "title": "E03 Evidence preservation and acquisition triage — Investigator",
            "product_name": "Preservation / acquisition matrix (P02)",
            "instructions": instructions(inv, "Investigator pathway"),
            "sections": inv_sections,
        },
        {
            "code": "E03-P02-ANA",
            "pathway": "analyst",
            "title": "E03 Evidence preservation and acquisition triage — Intelligence Analyst",
            "product_name": "Event / selector ledger (P02)",
            "instructions": instructions(ana, "Intelligence analyst pathway"),
            "sections": ana_sections,
        },
    ]


def case_spec(records: dict[str, Record], suite: Path = SUITE_DIR) -> dict:
    readme = (suite / "README.md").read_text(encoding="utf-8")

    def readme_section(name: str) -> str:
        part = readme.split(f"## {name}", 1)[1] if f"## {name}" in readme else ""
        return part.split("\n## ", 1)[0].strip()

    return {
        "code": CASE_CODE,
        "title": "Case HARBORLINE — Northbank Regional Medical",
        "victim_organization": "Northbank Regional Medical (NRM, fictional)",
        "summary": records["H-INT-01"].observation,
        "fictional_disclaimer": readme_section("Case constraints"),
        "instructor_overview": readme_section("Delivery rule"),
    }


def release_plan(content: SuiteContent) -> list[dict]:
    """Release-plan items: per exercise a student packet, its evidence batch(es) and an answer key; plus the
    workbook, the v0.5 staged packet blocks, and the K01/K02 development knowledge checks."""
    items: list[dict] = [
        {
            "code": "PKT-WORKBOOK",
            "sequence": 5,
            "item_type": "document",
            "title": "Student workbook (v0.3)",
            "trigger_type": "manual",
            "document_code": "HBL3-WORKBOOK",
            "instructor_notes": "Assignment workbook / response forms (faculty plan: student archive).",
        }
    ]
    for n, (ex, module, batches) in enumerate(EXERCISES, start=1):
        base = n * 100
        title = content.titles.get(ex, ex)
        packet = {
            "code": f"PKT-{ex}",
            "sequence": base,
            "item_type": "document",
            "title": f"{ex} student packet — {title}",
            "document_code": f"PKT-{ex}",
            "trigger_type": "manual",
        }
        if module:
            packet.update(
                trigger_type="lesson_gate", trigger_module_code=module, trigger_lesson_state="taught"
            )
        items.append(packet)
        for b, batch in enumerate(batches):
            suffix = "" if len(batches) == 1 else chr(ord("A") + b)
            items.append(
                {
                    "code": f"EVI-{ex}{suffix}",
                    "sequence": base + 10 + b,
                    "item_type": "evidence_inject",
                    "title": f"{ex} records: {', '.join(batch)}",
                    "trigger_type": "manual",
                    "inject_code": f"INJ-{ex}{suffix}",
                    "instructor_notes": "Instructor-controlled release (E03 packet: “Your instructor controls when new "
                    "evidence is released.”). See the answer key for the exercise's release checklist.",
                }
            )
        key_text = content.master.get(ex, "")
        if content.key.get(ex):
            key_text += "\n\n— Annotated instructor key —\n\n" + content.key[ex]
        items.append(
            {
                "code": f"AK-{ex}",
                "sequence": base + 50,
                "item_type": "answer_key",
                "audience": "staff",
                "title": f"{ex} instructor master and key",
                "trigger_type": "manual",
                "answer_for_code": None,
                "body": key_text or "(not found in source)",
            }
        )
    for kc, day, time_, instr, body, key in (
        ("K01", "Tue", "16:15", "K01", content.k01, content.k01_key),
        ("K02", "Fri", "11:15", "K02", content.k02, content.k02_key),
    ):
        items.append(
            {
                "code": f"CH-{kc}",
                "sequence": 1200 + len(items),
                "item_type": "challenge",
                "scored": True,
                "instrument_code": instr,
                "title": f"Knowledge check {kc} (development items)",
                "trigger_type": "scheduled",
                "trigger_day": day,
                "trigger_time": time_,
                "body": body,
                "instructor_notes": "Development items from PACT_Development_Knowledge_Checks_v0.3: not the "
                "approved secure exam. Scored release stays blocked until assessment authorization.",
            }
        )
        items.append(
            {
                "code": f"AK-{kc}",
                "sequence": 1200 + len(items),
                "item_type": "answer_key",
                "audience": "staff",
                "title": f"Knowledge check {kc} — instructor key",
                "trigger_type": "manual",
                "answer_for_code": f"CH-{kc}",
                "body": key,
            }
        )
    # v0.5 staged packet blocks (already imported separately), opened at lesson stages.
    for code, block, module, state in [
        ("DOC-MON-START", "Mon start", "M01", "released"),
        ("DOC-TUE-EARLY", "Tue early", "M04", "released"),
        ("DOC-TUE-DISCOVERY", "Tue after discovery", "M04", "taught"),
        ("DOC-TUE-LATE", "Tue late", "M05", "taught"),
        ("DOC-WED-AM", "Wed am", "M06", "released"),
        ("DOC-WED-PM", "Wed PM after approval", "M06", "taught"),
        ("DOC-THU", "Thu", "M08", "released"),
        ("DOC-FRI", "Fri", "M10", "released"),
    ]:
        items.append(
            {
                "code": code,
                "sequence": 2000 + len(items),
                "item_type": "document_block",
                "title": f"v0.5 staged packets — {block}",
                "trigger_type": "lesson_gate",
                "trigger_module_code": module,
                "trigger_lesson_state": state,
                "document_block": block,
            }
        )
    return items


def inject_specs(content: SuiteContent) -> list[dict]:
    specs = []
    for n, (ex, _module, batches) in enumerate(EXERCISES, start=1):
        for b, batch in enumerate(batches):
            suffix = "" if len(batches) == 1 else chr(ord("A") + b)
            specs.append(
                {
                    "code": f"INJ-{ex}{suffix}",
                    "sequence": n * 10 + b,
                    "records": batch,
                    "title": f"{ex} — {content.titles.get(ex, ex)}" + (f" (part {suffix})" if suffix else ""),
                    "student_briefing": f"Records released for {ex}: {', '.join(batch)}.",
                    "instructor_notes": _packet_line(
                        content.master.get(ex, ""), "Only release current record(s)"
                    ),
                }
            )
    return specs
