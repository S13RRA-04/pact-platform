"""Deterministic import of the PACT curriculum control workbook.

Rules:
- Source text is stored verbatim (``source_row``) along with the parsed fields.
- Every relationship is stored as stated *by each sheet*; nothing is merged or corrected.
- Disagreements between sheets are recorded as ``ImportIssue`` rows and written to a Markdown
  reconciliation report. Re-importing an identical file (same SHA-256) is a no-op.
"""

from __future__ import annotations

import hashlib
import re
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import openpyxl
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import (
    ActionItem,
    AssessmentInstrument,
    Course,
    CourseVersion,
    CurriculumLink,
    Exercise,
    ImportIssue,
    ImportRun,
    Module,
    Objective,
    QAGate,
    ScheduleBlock,
    Task,
)

COURSE_CODE = "PACT"
COURSE_TITLE = "PACT Cybercrime Investigation and Cyber Intelligence Analysis Program"
DAYS = {"Mon": 0, "Tue": 1, "Wed": 2, "Thu": 3, "Fri": 4}
PATHWAY_MAP = {
    "common": "common",
    "investigator": "investigator",
    "analyst": "analyst",
    "integrated": "integrated",
}
CODE_RE = re.compile(r"\b([A-Z]{1,2}\d{2})\b")
TASK_RE = re.compile(r"\bT-[CIAJ]\d{2}\b")

# Canonical link types: (entity -> objective) etc. ``from_code`` is never the objective except for tasks.
MODULE_OBJECTIVE = "module_objective"
EXERCISE_OBJECTIVE = "exercise_objective"
INSTRUMENT_OBJECTIVE = "instrument_objective"
EXERCISE_INSTRUMENT = "exercise_instrument"
BLOCK_OBJECTIVE = "schedule_block_objective"
OBJECTIVE_TASK = "objective_task"


def codes(text: Any, prefix: str | None = None) -> list[str]:
    if text is None:
        return []
    found = CODE_RE.findall(str(text))
    if prefix:
        found = [c for c in found if c.startswith(prefix)]
    return sorted(dict.fromkeys(found))


def is_objective(code: str) -> bool:
    return code[0] in "CIAJ" and len(code) == 3


def clean(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


@dataclass
class Sheet:
    name: str
    header: list[str]
    rows: list[tuple[int, dict[str, Any]]]  # (excel row number, {header: value})


@dataclass
class ParsedWorkbook:
    sha256: str
    filename: str
    document_status: str
    control_metrics: dict[str, Any]
    sheets: dict[str, Sheet]
    links: list[dict[str, Any]] = field(default_factory=list)


def _read_sheet(ws: Any, first_header: str) -> Sheet:
    header: list[str] | None = None
    rows: list[tuple[int, dict[str, Any]]] = []
    for idx, raw in enumerate(ws.iter_rows(values_only=True), start=1):
        values = list(raw)
        if header is None:
            if values and clean(values[0]) == first_header:
                header = [clean(v) or f"col{i}" for i, v in enumerate(values)]
            continue
        if not any(v is not None and str(v).strip() for v in values):
            continue
        rows.append((idx, {h: values[i] if i < len(values) else None for i, h in enumerate(header)}))
    if header is None:
        raise ValueError(f"Sheet {ws.title!r}: header row starting with {first_header!r} not found")
    return Sheet(ws.title, header, rows)


SHEET_HEADERS = {
    "Objectives": "Objective",
    "Task Register": "Task ID",
    "Modules": "Module",
    "POI Schedule": "Day",
    "Assessments": "ID",
    "Traceability": "Objective",
    "QA Gates": "ID",
    "Action Register": "ID",
    "Change Log": "Version",
}


def parse_workbook(path: Path) -> ParsedWorkbook:
    data = path.read_bytes()
    sha = hashlib.sha256(data).hexdigest()
    wb = openpyxl.load_workbook(path, data_only=True, read_only=True)
    missing = [s for s in [*SHEET_HEADERS, "START HERE"] if s not in wb.sheetnames]
    if missing:
        raise ValueError(f"Workbook missing required sheets: {missing}")

    start = wb["START HERE"]
    status = ""
    metrics: dict[str, Any] = {}
    for raw in start.iter_rows(values_only=True):
        vals = list(raw) + [None] * 5
        if clean(vals[0]) == "DOCUMENT STATUS":
            status = clean(vals[1]) or ""
        if clean(vals[3]) and vals[4] is not None and clean(vals[3]) != "CONTROL METRIC":
            metrics[clean(vals[3]) or ""] = vals[4]

    sheets = {name: _read_sheet(wb[name], hdr) for name, hdr in SHEET_HEADERS.items()}
    return ParsedWorkbook(sha, path.name, status, metrics, sheets)


# ---------------------------------------------------------------------------------------------
def _derive_links(pw: ParsedWorkbook) -> list[dict[str, Any]]:
    links: list[dict[str, Any]] = []

    def add(sheet: str, link_type: str, frm: str, to: str, row: int, **attrs: Any) -> None:
        links.append(
            {
                "source_sheet": sheet,
                "link_type": link_type,
                "from_code": frm,
                "to_code": to,
                "source_row_ref": f"{sheet}!R{row}",
                "attributes": attrs,
            }
        )

    for row_no, r in pw.sheets["Objectives"].rows:
        obj = clean(r["Objective"])
        if not obj:
            continue
        for m in codes(r.get("Module(s)"), "M"):
            add("Objectives", MODULE_OBJECTIVE, m, obj, row_no)
        for e in codes(r.get("Exercise(s)"), "E"):
            add("Objectives", EXERCISE_OBJECTIVE, e, obj, row_no)
        for p in codes(r.get("Assessment(s)")):
            if p[0] in "PK":
                add("Objectives", INSTRUMENT_OBJECTIVE, p, obj, row_no)
        for t in TASK_RE.findall(str(r.get("Task ref") or "")):
            add("Objectives", OBJECTIVE_TASK, obj, t, row_no)

    for row_no, r in pw.sheets["Modules"].rows:
        mod = clean(r["Module"])
        for o in codes(r.get("Objectives")):
            if is_objective(o):
                add("Modules", MODULE_OBJECTIVE, mod or "", o, row_no)

    for row_no, r in pw.sheets["POI Schedule"].rows:
        ref = clean(r.get("ID"))
        if not ref or ref in ("—", "-"):
            continue
        objs = [o for o in codes(r.get("Objectives")) if is_objective(o)]
        btype = clean(r.get("Type")) or ""
        for o in objs:
            if ref.startswith("M"):
                add("POI Schedule", MODULE_OBJECTIVE, ref, o, row_no)
            elif ref.startswith("E"):
                add("POI Schedule", EXERCISE_OBJECTIVE, ref, o, row_no, block_type=btype)
            else:
                add("POI Schedule", BLOCK_OBJECTIVE, ref, o, row_no, block_type=btype)
        if ref.startswith("E"):
            for p in codes(r.get("Scored?")):
                if p[0] in "PK":
                    add("POI Schedule", EXERCISE_INSTRUMENT, ref, p, row_no)

    for row_no, r in pw.sheets["Assessments"].rows:
        inst = clean(r["ID"])
        for o in codes(r.get("Objectives evaluated")):
            if is_objective(o):
                add("Assessments", INSTRUMENT_OBJECTIVE, inst or "", o, row_no)

    for row_no, r in pw.sheets["Traceability"].rows:
        obj = clean(r["Objective"])
        if not obj:
            continue
        for p in codes(r.get("Assessment")):
            add(
                "Traceability",
                INSTRUMENT_OBJECTIVE,
                p,
                obj,
                row_no,
                scored_criterion=clean(r.get("Scored criterion")),
                status=clean(r.get("Status")),
                owner=clean(r.get("Owner")),
            )
        for m in codes(r.get("Module(s)"), "M"):
            add("Traceability", MODULE_OBJECTIVE, m, obj, row_no)
        for e in codes(r.get("Practice"), "E"):
            add("Traceability", EXERCISE_OBJECTIVE, e, obj, row_no)

    # De-duplicate (Traceability repeats module/practice columns on multiple rows) deterministically.
    seen: dict[tuple[str, str, str, str], dict[str, Any]] = {}
    for link in links:
        key = (link["source_sheet"], link["link_type"], link["from_code"], link["to_code"])
        seen.setdefault(key, link)
    return [seen[k] for k in sorted(seen)]


# ---------------------------------------------------------------------------------------------
@dataclass
class Issue:
    severity: str
    category: str
    subject: str
    detail: str
    sources: dict[str, Any] = field(default_factory=dict)


def reconcile(pw: ParsedWorkbook, links: list[dict[str, Any]]) -> list[Issue]:
    issues: list[Issue] = []
    by: dict[tuple[str, str], dict[str, set[str]]] = defaultdict(lambda: defaultdict(set))
    for link in links:
        by[(link["link_type"], link["source_sheet"])][link["from_code"]].add(link["to_code"])

    objectives = sorted(clean(r["Objective"]) or "" for _, r in pw.sheets["Objectives"].rows)
    modules = sorted(clean(r["Module"]) or "" for _, r in pw.sheets["Modules"].rows)
    instruments = sorted(clean(r["ID"]) or "" for _, r in pw.sheets["Assessments"].rows)
    poi_refs = {clean(r.get("ID")) for _, r in pw.sheets["POI Schedule"].rows}

    def compare(
        link_type: str,
        sheets: list[str],
        entities: list[str],
        category: str,
        partial_sheets: tuple[str, ...] = (),
    ) -> None:
        for ent in entities:
            per_sheet = {s: sorted(by[(link_type, s)].get(ent, set())) for s in sheets}
            considered = {s: v for s, v in per_sheet.items() if not (s in partial_sheets and not v)}
            distinct = {tuple(v) for v in considered.values()}
            if len(distinct) > 1:
                parts = "; ".join(f"{s}: {', '.join(v) or '(none)'}" for s, v in per_sheet.items())
                issues.append(
                    Issue(
                        "conflict",
                        category,
                        ent,
                        f"{ent} objective links differ between sheets — {parts}. "
                        "Preserved as stated per sheet; not reconciled.",
                        per_sheet,
                    )
                )

    compare(
        MODULE_OBJECTIVE,
        ["Modules", "Objectives", "POI Schedule", "Traceability"],
        modules,
        "module_objective_mismatch",
        partial_sheets=("POI Schedule",),
    )
    compare(
        INSTRUMENT_OBJECTIVE,
        ["Assessments", "Objectives", "Traceability"],
        instruments,
        "instrument_objective_mismatch",
    )
    exercises = sorted({lk["from_code"] for lk in links if lk["link_type"] == EXERCISE_OBJECTIVE})
    compare(
        EXERCISE_OBJECTIVE,
        ["POI Schedule", "Objectives", "Traceability"],
        exercises,
        "exercise_objective_mismatch",
    )

    for m in modules:
        if m not in poi_refs:
            issues.append(
                Issue(
                    "warning",
                    "module_not_scheduled",
                    m,
                    f"{m} appears on the Modules sheet but has no block in the POI Schedule.",
                    {"Modules": m},
                )
            )
    for _, r in pw.sheets["POI Schedule"].rows:
        ref = clean(r.get("ID")) or ""
        btype = clean(r.get("Type")) or ""
        if ref.startswith("E") and btype != "Exercise":
            issues.append(
                Issue(
                    "warning",
                    "exercise_type_ambiguity",
                    ref,
                    f"{ref} is coded as an exercise ID but its POI block type is '{btype}'.",
                    {"POI Schedule": {"type": btype, "title": clean(r.get("Block / activity"))}},
                )
            )
        scored = clean(r.get("Scored?")) or ""
        for p in codes(scored):
            if p[0] in "PK" and p not in instruments:
                issues.append(
                    Issue("error", "unknown_instrument", p, f"POI row {ref} references unknown {p}.")
                )
    for inst in instruments:
        stated = [
            o
            for s in ("Assessments", "Objectives", "Traceability")
            for o in by[(INSTRUMENT_OBJECTIVE, s)].get(inst, set())
        ]
        if not stated:
            issues.append(Issue("error", "instrument_without_objectives", inst, f"{inst} has no objectives."))
    for obj in objectives:
        if not any(
            obj in v
            for s in ("Assessments", "Objectives", "Traceability")
            for v in by[(INSTRUMENT_OBJECTIVE, s)].values()
        ):
            issues.append(
                Issue("error", "objective_not_evaluated", obj, f"{obj} has no evaluation instrument.")
            )
    all_objective_links = {lk["to_code"] for lk in links if is_objective(lk["to_code"])}
    for code in sorted(all_objective_links - set(objectives)):
        issues.append(
            Issue("error", "unknown_objective", code, f"Referenced objective {code} is not defined.")
        )

    # Control metrics stated on START HERE versus parsed counts.
    pathways = defaultdict(int)
    for _, r in pw.sheets["Objectives"].rows:
        pathways[(clean(r["Pathway"]) or "").lower()] += 1
    expected = {
        "Proposed objectives": len(objectives),
        "Investigator-specific": pathways["investigator"],
        "Analyst-specific": pathways["analyst"],
        "Common + integrated": pathways["common"] + pathways["integrated"],
        "Program modules": len(modules),
        "Assessment instruments": len(instruments),
        "Validation items open": sum(
            1 for _, r in pw.sheets["QA Gates"].rows if (clean(r.get("Status")) or "") != "Complete"
        ),
    }
    for metric, parsed in expected.items():
        stated = pw.control_metrics.get(metric)
        if stated is not None and int(stated) != parsed:
            issues.append(
                Issue(
                    "warning",
                    "control_metric_mismatch",
                    metric,
                    f"START HERE states {metric} = {stated}; parsed value is {parsed}.",
                    {"stated": stated, "parsed": parsed},
                )
            )

    issues.append(
        Issue(
            "info",
            "validation_status",
            "ALL",
            "All objectives are 'Proposed' and all tasks 'Not validated'. Imported as provisional; "
            "no task validation, cut score, or approval is implied.",
            {
                "objective_statuses": sorted(
                    {clean(r.get("Validation")) or "" for _, r in pw.sheets["Objectives"].rows}
                ),
                "task_statuses": sorted(
                    {clean(r.get("Status")) or "" for _, r in pw.sheets["Task Register"].rows}
                ),
            },
        )
    )
    traceability_tbd = sum(
        1 for _, r in pw.sheets["Traceability"].rows if "TBD" in (clean(r.get("Scored criterion")) or "")
    )
    if traceability_tbd:
        issues.append(
            Issue(
                "warning",
                "criteria_undefined",
                "Traceability",
                f"{traceability_tbd} objective–assessment linkages have 'Individual criterion TBD'. "
                "Rubric criteria cannot be imported; P02 development criteria are provisional.",
                {"count": traceability_tbd},
            )
        )
    order = {"error": 0, "conflict": 1, "warning": 2, "info": 3}
    issues.sort(key=lambda i: (order[i.severity], i.category, i.subject))
    return issues


# ---------------------------------------------------------------------------------------------
def _pathway(value: Any) -> str:
    return PATHWAY_MAP.get((clean(value) or "").lower(), "common")


def _jsonable(row: dict[str, Any]) -> dict[str, Any]:
    return {k: (None if v is None else str(v)) for k, v in row.items()}


def import_workbook(db: Session, path: Path, report_path: Path | None = None) -> ImportRun:
    pw = parse_workbook(path)
    course = db.scalar(select(Course).where(Course.code == COURSE_CODE))
    if course is None:
        course = Course(code=COURSE_CODE, title=COURSE_TITLE)
        db.add(course)
        db.flush()

    existing = db.scalar(
        select(CourseVersion).where(
            CourseVersion.course_id == course.id, CourseVersion.source_sha256 == pw.sha256
        )
    )
    links = _derive_links(pw)
    issues = reconcile(pw, links)
    if existing is not None:
        run = ImportRun(
            source_filename=pw.filename,
            source_sha256=pw.sha256,
            outcome="unchanged",
            course_version_id=existing.id,
            summary={"note": "identical source already imported"},
        )
        db.add(run)
        db.flush()
        return run

    version_label = "0.1"
    for _, r in pw.sheets["Change Log"].rows:
        version_label = clean(r["Version"]) or version_label
    cv = CourseVersion(
        course_id=course.id,
        version_label=version_label,
        source_filename=pw.filename,
        source_sha256=pw.sha256,
        source_document_status=pw.document_status,
        status="provisional",
        locked=True,
    )
    db.add(cv)
    db.flush()

    for _, r in pw.sheets["Task Register"].rows:
        db.add(
            Task(
                course_version_id=cv.id,
                code=clean(r["Task ID"]),
                pathway=_pathway(r["Pathway"]),
                statement=clean(r["Work task (provisional)"]) or "",
                task_source=clean(r.get("Task source")),
                validation_status=clean(r.get("Status")) or "Unknown",
                source_row=_jsonable(r),
            )
        )
    for _, r in pw.sheets["Objectives"].rows:
        tasks = TASK_RE.findall(str(r.get("Task ref") or ""))
        db.add(
            Objective(
                course_version_id=cv.id,
                code=clean(r["Objective"]),
                pathway=_pathway(r["Pathway"]),
                task_code=tasks[0] if tasks else None,
                observable_performance=clean(r["Observable performance"]) or "",
                conditions=clean(r.get("Given / conditions")),
                acceptable_evidence=clean(r.get("Acceptable evidence")),
                reference_alignment=clean(r.get("Reference alignment")),
                validation_status=clean(r.get("Validation")) or "Unknown",
                source_row=_jsonable(r),
            )
        )
    for seq, (_, r) in enumerate(pw.sheets["Modules"].rows, start=1):
        db.add(
            Module(
                course_version_id=cv.id,
                code=clean(r["Module"]),
                sequence=seq,
                title=clean(r["Module title"]) or "",
                teaching_mode=clean(r.get("Teaching mode")),
                objectives_text=clean(r.get("Objectives")),
                instructional_content=clean(r.get("Instructional content")),
                required_output=clean(r.get("Required output")),
                source_row=_jsonable(r),
            )
        )
    for seq, (_, r) in enumerate(pw.sheets["POI Schedule"].rows, start=1):
        ref = clean(r.get("ID"))
        ref = None if ref in (None, "—", "-") else ref
        day = clean(r["Day"]) or ""
        block = ScheduleBlock(
            course_version_id=cv.id,
            sequence=seq,
            day=day,
            day_index=DAYS.get(day, -1),
            start_time=clean(r["Start"]) or "",
            end_time=clean(r["End"]) or "",
            block_type=clean(r["Type"]) or "",
            ref_code=ref,
            title=clean(r["Block / activity"]) or "",
            format=clean(r.get("Format")),
            audience=clean(r.get("Audience")),
            objectives_text=clean(r.get("Objectives")),
            scored_text=clean(r.get("Scored?")),
            note=clean(r.get("Implementation note")),
        )
        db.add(block)
        if ref and ref.startswith("E"):
            db.add(
                Exercise(
                    course_version_id=cv.id,
                    code=ref,
                    title=block.title,
                    format=block.format,
                    audience=block.audience,
                    day=day,
                    source_block_type=block.block_type,
                    note=block.note,
                )
            )
    for _, r in pw.sheets["Assessments"].rows:
        db.add(
            AssessmentInstrument(
                course_version_id=cv.id,
                code=clean(r["ID"]),
                name=clean(r["Instrument"]) or "",
                mode=clean(r.get("Mode")),
                day=clean(r.get("Day")),
                student_evidence=clean(r.get("Student-produced evidence")),
                scoring_method=clean(r.get("Scoring method")),
                approval_standard=clean(r.get("Approval / standard")),
                observations=clean(r.get("Observations")),
                authorization_status="not_authorized",
            )
        )
    for _, r in pw.sheets["QA Gates"].rows:
        db.add(
            QAGate(
                course_version_id=cv.id,
                code=clean(r["ID"]),
                fleta_ref=clean(r.get("FLETA ref")),
                control_area=clean(r.get("Control area")) or "",
                required_work=clean(r.get("Required work")),
                accountable_role=clean(r.get("Accountable role")),
                status=clean(r.get("Status")) or "",
                evidence_artifact=clean(r.get("Evidence artifact")),
            )
        )
    for _, r in pw.sheets["Action Register"].rows:
        db.add(
            ActionItem(
                course_version_id=cv.id,
                code=clean(r["ID"]),
                priority=clean(r.get("Priority")),
                action=clean(r.get("Action")) or "",
                owner=clean(r.get("Owner")),
                gate=clean(r.get("Gate")),
                status=clean(r.get("Status")) or "",
            )
        )
    for link in links:
        db.add(CurriculumLink(course_version_id=cv.id, **link))

    counts = {
        "objectives": len(pw.sheets["Objectives"].rows),
        "tasks": len(pw.sheets["Task Register"].rows),
        "modules": len(pw.sheets["Modules"].rows),
        "schedule_blocks": len(pw.sheets["POI Schedule"].rows),
        "instruments": len(pw.sheets["Assessments"].rows),
        "qa_gates": len(pw.sheets["QA Gates"].rows),
        "action_items": len(pw.sheets["Action Register"].rows),
        "links": len(links),
        "issues": {
            s: sum(1 for i in issues if i.severity == s) for s in ("error", "conflict", "warning", "info")
        },
    }
    run = ImportRun(
        source_filename=pw.filename,
        source_sha256=pw.sha256,
        outcome="imported",
        course_version_id=cv.id,
        summary=counts,
    )
    db.add(run)
    db.flush()
    for i in issues:
        db.add(
            ImportIssue(
                import_run_id=run.id,
                severity=i.severity,
                category=i.category,
                subject=i.subject,
                detail=i.detail,
                sources=i.sources,
            )
        )
    db.flush()
    if report_path is not None:
        write_report(report_path, pw, counts, issues)
    return run


def write_report(path: Path, pw: ParsedWorkbook, counts: dict[str, Any], issues: list[Issue]) -> None:
    lines = [
        "# Curriculum Import Reconciliation Report",
        "",
        "_Generated deterministically by `python -m app.curriculum_import`. Do not edit by hand._",
        "",
        f"- **Source file:** `{pw.filename}`",
        f"- **SHA-256:** `{pw.sha256}`",
        f"- **Source document status:** {pw.document_status}",
        "- **Imported status:** provisional (course version locked; not approved for delivery)",
        "",
        "## Counts",
        "",
        "| Item | Count |",
        "|---|---|",
    ]
    for k, v in counts.items():
        if k != "issues":
            lines.append(f"| {k} | {v} |")
    lines += [
        "",
        "## Issues",
        "",
        "Relationships are stored per source sheet (`curriculum_links.source_sheet`). "
        "Conflicts below are **unresolved** and require curriculum-owner decision; "
        "the importer does not choose a winning sheet.",
        "",
        "| # | Severity | Category | Subject | Detail |",
        "|---|---|---|---|---|",
    ]
    for n, i in enumerate(issues, start=1):
        lines.append(f"| {n} | {i.severity} | {i.category} | {i.subject} | {i.detail.replace('|', '/')} |")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
