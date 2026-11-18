"""Operation HARBORLINE — the platform's scenario, built from the HARBORLINE v0.5 scenario delivery.

Nothing here is authored curriculum: every record, briefing, task, faculty note and answer key is read from
the delivery's own files at install time (paths below), so the platform shows exactly what the course
materials say. The few labels this module adds (item codes, inject titles, provenance notes) say where the
content came from and are not instructional content.

Sources (relative to the repository, under "pact curriculum/"):
  PACT_HARBORLINE_v0.5_Student_Staged_Packets.zip
    Student/DayN/NN_*.docx      → one staged packet per release; each packet's record table becomes evidence
  PACT_HARBORLINE_v0.5_Instructor_Master.zip
    Instructor/PACT_HARBORLINE_Instructor_Scenario_Master_v0.5.docx → day-by-day faculty keys, record cautions
    Instructor/Release_Register_v0.5.csv                            → release gate and faculty restriction
    Instructor/New_Source_ID_Continuity_Register_v0.5.csv           → "do not overstate" note per record
  PACT_Instructor_Exercise_Master_v0.3/ (reference only under v0.5)
    Student/Case_Records/Day*/                     → raw lines of the locked H- records (same IDs and times)
    Instructor/PACT_Development_Knowledge_Checks_v0.3.docx → K01/K02 development items

Squad tracks: the v0.5 packets are addressed to one squad ("MONDAY / SQUAD A") or one search-site team
(records S-418-*, S-R12-*, S-C14-*). Those packets and their records are released on the matching track
("case:A", "site:418") so only that squad sees them (instructor master, Gate 1 and the Wednesday returns).
"""

from __future__ import annotations

import csv
import io
import re
import xml.etree.ElementTree as ET  # Element type only; parsing uses defusedxml
import zipfile
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path, PurePosixPath

from defusedxml import ElementTree as SafeET

from app.config import REPO_ROOT
from app.curriculum_import.exercise_suite import docx_text

CURRICULUM_DIR = REPO_ROOT / "pact curriculum"
SUITE_DIR = CURRICULUM_DIR / "PACT_Instructor_Exercise_Master_v0.3"  # v0.3 reference suite
STUDENT_ZIP = CURRICULUM_DIR / "PACT_HARBORLINE_v0.5_Student_Staged_Packets.zip"
INSTRUCTOR_ZIP = CURRICULUM_DIR / "PACT_HARBORLINE_v0.5_Instructor_Master.zip"
MASTER_MEMBER = "Instructor/PACT_HARBORLINE_Instructor_Scenario_Master_v0.5.docx"
CASE_CODE = "HARBORLINE"
SCENARIO_VERSION = "0.5"
# Packet 01: "Initial report received 26 October 2026"; packet record times omit the year ("24 Oct 22:14:07Z").
SCENARIO_YEAR = 2026

W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
RECORD_ID = re.compile(r"^[A-Z]{1,5}(?:-[A-Z0-9]+)+$")
TS_V05 = re.compile(r"\b(\d{1,2}) Oct (\d{2}):(\d{2})(?::(\d{2}))?Z")
TS_V03 = re.compile(r"(\d{4}-\d{2}-\d{2})[ T](\d{2}:\d{2}:\d{2})Z")
PACKET_HEADINGS = {
    "Situation",
    "Records in your initial packet",
    "Situation and new information",
    "New case records",
}
OPTIONAL_LAB = ["H-LAB-01", "H-LAB-02", "H-LAB-03"]
OPTIONAL_LAB_NOTE_START = "Retain H-LAB-01/02/03"


# --- docx reading ---------------------------------------------------------------------------------------
def _para(p: ET.Element) -> str:
    return "".join(n.text or "" for n in p.iter(W + "t"))


def docx_blocks(data: bytes) -> list[str | list[str]]:
    """Body of a .docx in order: a paragraph is a string, a table row is a list of cell texts."""
    body = SafeET.fromstring(zipfile.ZipFile(io.BytesIO(data)).read("word/document.xml")).find(W + "body")
    out: list[str | list[str]] = []
    for el in body if body is not None else []:
        if el.tag == W + "p":
            text = _para(el).strip()
            if text:
                out.append(text)
        elif el.tag == W + "tbl":
            for tr in el.iter(W + "tr"):
                out.append(
                    [" ".join(_para(p) for p in tc.iter(W + "p")).strip() for tc in tr.findall(W + "tc")]
                )
    return out


def _lines(blocks: list[str | list[str]]) -> list[str]:
    return [b if isinstance(b, str) else " | ".join(b) for b in blocks]


def _title(text: str) -> str:
    """'THE ALERT BEFORE ROUNDS' → 'The Alert Before Rounds' (packet titles are set in capitals)."""
    return text.title() if text.isupper() else text


# --- v0.3 locked records (raw lines for H- records) --------------------------------------------------------
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
    """The v0.3 case records. v0.5 keeps these H- records locked (same IDs, times and wording)."""
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
                match = TS_V03.search(rec.observation)
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


# --- v0.5 packets -----------------------------------------------------------------------------------------
@dataclass
class Packet:
    number: int
    filename: str
    day: str  # "Day1".."Day5"
    header: str  # e.g. "MONDAY / SQUAD A / CASE A-26-101"
    title: str  # e.g. "The Alert Before Rounds"
    briefing: str
    rows: list[tuple[list[str], str, str]]  # (record ids, what it says, what it does not establish)
    lines: list[str]
    track: str | None = None
    gate: str = ""
    recipients: str = ""
    restriction: str = ""

    @property
    def code(self) -> str:
        return f"{self.number:02d}"

    @property
    def document_code(self) -> str:
        return f"HBL-{self.code}"  # code given by the curriculum archive importer

    def section(self, heading: str, stops: tuple[str, ...]) -> list[str]:
        out, capture = [], False
        for ln in self.lines:
            if ln == heading:
                capture = True
                continue
            if capture and ln in stops:
                break
            if capture:
                out.append(ln)
        return out


def _parse_packet(name: str, data: bytes) -> Packet:
    path = PurePosixPath(name)
    blocks = docx_blocks(data)
    paras = [b for b in blocks if isinstance(b, str)]
    header, title = paras[0], paras[1]
    briefing: list[str] = []
    rows: list[tuple[list[str], str, str]] = []
    seen_table = False
    for b in blocks[2:]:
        if isinstance(b, list):
            seen_table = True
            ids = [i.strip() for i in b[0].split(" / ")] if b else []
            if len(b) == 3 and ids and all(RECORD_ID.match(i) for i in ids):
                rows.append((ids, b[1], b[2]))
        elif not seen_table and b not in PACKET_HEADINGS:
            briefing.append(b)
    packet = Packet(
        number=int(path.name[:2]),
        filename=path.name,
        day=path.parent.name,
        header=header,
        title=_title(title),
        briefing="\n\n".join(briefing),
        rows=rows,
        lines=_lines(blocks),
    )
    squad = re.search(r"/ SQUAD ([A-D]) /", header)
    sites = {ids[0].split("-")[1] for ids, _, _ in rows if ids[0].startswith("S-")}
    if squad:
        packet.track = f"case:{squad.group(1)}"
    elif rows and all(ids[0].startswith("S-") for ids, _, _ in rows) and len(sites) == 1:
        packet.track = f"site:{sites.pop()}"
    return packet


def load_packets(student_zip: Path = STUDENT_ZIP, instructor_zip: Path = INSTRUCTOR_ZIP) -> list[Packet]:
    with zipfile.ZipFile(student_zip) as z:
        packets = [
            _parse_packet(n, z.read(n))
            for n in sorted(z.namelist())
            if n.startswith("Student/") and n.endswith(".docx")
        ]
    register = _release_register(instructor_zip)
    for p in packets:
        gate = register.get(p.number)
        if gate:
            p.gate, p.recipients, p.restriction = gate
    return packets


def _release_register(instructor_zip: Path) -> dict[int, tuple[str, str, str]]:
    """{packet number: (release gate, recipients, critical faculty restriction)} from Release_Register_v0.5."""
    with zipfile.ZipFile(instructor_zip) as z:
        text = z.read("Instructor/Release_Register_v0.5.csv").decode("utf-8-sig")
    out = {}
    for row in csv.DictReader(io.StringIO(text)):
        m = re.search(r"(\d{2})(?:\s*[–-]\s*(\d{2}))?", row["Student packet"])
        if not m:
            continue
        first, last = int(m.group(1)), int(m.group(2) or m.group(1))
        for n in range(first, last + 1):
            out[n] = (row["Release gate"], row["Recipients"], row["Critical faculty restriction"])
    return out


def _continuity_register(instructor_zip: Path) -> dict[str, str]:
    with zipfile.ZipFile(instructor_zip) as z:
        text = z.read("Instructor/New_Source_ID_Continuity_Register_v0.5.csv").decode("utf-8-sig")
    return {r["Record ID"]: r["Do not overstate"] for r in csv.DictReader(io.StringIO(text))}


# --- instructor master ------------------------------------------------------------------------------------
@dataclass
class Master:
    lines: list[str]

    @property
    def one_paragraph(self) -> str:
        return self.after("The case in one paragraph")

    def after(self, heading: str) -> str:
        i = self.lines.index(heading)
        return self.lines[i + 1]

    def between(self, start_prefix: str, end_prefix: str | None) -> str:
        start = next(i for i, ln in enumerate(self.lines) if ln.startswith(start_prefix))
        end = (
            next(i for i, ln in enumerate(self.lines) if i > start and ln.startswith(end_prefix))
            if end_prefix
            else len(self.lines)
        )
        return "\n".join(self.lines[start:end])

    def record_rows(self, code: str) -> list[str]:
        """Faculty table rows about a record (its caution / training issue / consequence column)."""
        out = []
        for ln in self.lines:
            first = ln.split(" | ", 1)[0]
            if " | " in ln and re.search(rf"(^|[\s/]){re.escape(code)}(\s|$|/|\()", first):
                out.append(ln)
        return out

    def line_starting(self, prefix: str) -> str:
        return next((ln for ln in self.lines if prefix in ln), "")


def load_master(instructor_zip: Path = INSTRUCTOR_ZIP) -> Master:
    with zipfile.ZipFile(instructor_zip) as z:
        return Master(_lines(docx_blocks(z.read(MASTER_MEMBER))))


# Faculty answer keys: the instructor master split at its own day headings.
KEY_SECTIONS = [
    (
        "AK-OVERVIEW",
        "Faculty overview — the case, five-act structure and foundational cases",
        "INSTRUCTOR MASTER",
        "ACT I",
    ),
    ("AK-MON", "Monday faculty key (Act I)", "ACT I", "ACT II"),
    ("AK-TUE", "Tuesday faculty key (Act II)", "ACT II", "ACT III"),
    ("AK-WED", "Wednesday faculty key (Act III, warrants and search returns)", "ACT III", "ACT IV"),
    ("AK-THU", "Thursday faculty key (Act IV, foreign records and attribution)", "ACT IV", "ACT V"),
    (
        "AK-FRI",
        "Friday faculty key (Act V, simulated grand jury)",
        "ACT V",
        "Role-specific required products",
    ),
    (
        "AK-GATES",
        "Role products, evidence gates, pitfalls and required approvals",
        "Role-specific required products",
        None,
    ),
]


# --- K01/K02 (v0.3 development knowledge checks) -------------------------------------------------------------
@dataclass
class KnowledgeChecks:
    k01: str
    k02: str
    k01_key: str
    k02_key: str


def load_knowledge_checks(suite: Path = SUITE_DIR) -> KnowledgeChecks:
    kc = docx_text(suite / "Instructor" / "PACT_Development_Knowledge_Checks_v0.3.docx")
    preamble, _, rest = kc.partition("\nK01\n")
    k01_full, _, k02_full = rest.partition("\nK02\n")
    note = next((ln for ln in preamble.splitlines() if ln.startswith("These questions")), "")

    def strip_keys(part: str) -> str:
        return "\n".join(ln for ln in part.splitlines() if not ln.startswith("INSTRUCTOR KEY")).strip()

    return KnowledgeChecks(
        k01=strip_keys(k01_full),
        k02=strip_keys(k02_full),
        k01_key=f"{note}\n\n{k01_full.strip()}",
        k02_key=f"{note}\n\n{k02_full.strip()}",
    )


# --- everything together -------------------------------------------------------------------------------------
@dataclass
class Scenario:
    packets: list[Packet]
    master: Master
    v03: dict[str, Record]
    continuity: dict[str, str]
    kc: KnowledgeChecks


def load_scenario() -> Scenario:
    for path in (STUDENT_ZIP, INSTRUCTOR_ZIP, SUITE_DIR):
        if not path.exists():
            raise RuntimeError(f"HARBORLINE v0.5 source not found: {path}")
    return Scenario(
        packets=load_packets(),
        master=load_master(),
        v03=load_records(),
        continuity=_continuity_register(INSTRUCTOR_ZIP),
        kc=load_knowledge_checks(),
    )


def _v05_timestamp(text: str) -> tuple[datetime | None, str]:
    m = TS_V05.search(text)
    if not m:
        return None, "Not recorded in source"
    day, hh, mm, ss = int(m.group(1)), int(m.group(2)), int(m.group(3)), int(m.group(4) or 0)
    when = datetime.fromisoformat(f"{SCENARIO_YEAR}-10-{day:02d}T{hh:02d}:{mm:02d}:{ss:02d}+00:00")
    return when, f"{m.group(0)} (UTC; first time in the record; year {SCENARIO_YEAR} from the case packets)"


def _instructor_notes(s: Scenario, code: str) -> str:
    notes = list(s.master.record_rows(code))
    if code in s.continuity:
        notes.append(f"Do not overstate (continuity register): {s.continuity[code]}")
    return "\n".join(notes)


def evidence_specs(s: Scenario) -> dict[str, list[dict]]:
    """{inject code: [evidence item spec]} — one evidence item per record ID, in packet order.

    H- records are the locked v0.3/v0.4 records (same IDs and times); they keep their own observation,
    limitation and raw source lines, which also splits rows that list two IDs ("H-EDR-01 / H-IAM-01").
    Every other record is the packet's own row: what the record says, and what it does not establish.
    """
    out: dict[str, list[dict]] = {}
    seen: set[str] = set()
    seq = 0
    for p in s.packets:
        for ids, says, limit in p.rows:
            if len(ids) > 1 and not all(i in s.v03 for i in ids):
                raise ValueError(f"Packet {p.filename}: combined row {ids} is not made of locked H- records")
            for code in ids:
                if code in seen:
                    continue
                seen.add(code)
                seq += 1
                out.setdefault(f"INJ-{p.code}", []).append(_spec(s, p, code, says, limit, seq))
    lab = []
    for code in OPTIONAL_LAB:
        if code in s.v03 and code not in seen:
            seq += 1
            lab.append(
                _v03_spec(s, s.v03[code], seq, "optional forensic follow-up exhibit (instructor master)")
            )
    if lab:
        out["INJ-LAB"] = lab
    return out


def _v03_spec(s: Scenario, rec: Record, seq: int, released_in: str) -> dict:
    content = rec.observation
    for name, lines in rec.raw:
        content += f"\n\nRaw record ({name}):\n{lines}"
    files = ", ".join(sorted({n for n, _ in rec.raw})) or "none"
    return {
        "code": rec.code,
        "sequence": seq,
        "title": rec.source_type,
        "source_type": rec.source_type,
        "observed_at": rec.timestamp,
        "observed_timezone": "UTC" if rec.timestamp else None,
        "observed_as_recorded": rec.as_recorded,
        "provenance": (
            f"Locked HARBORLINE record (unchanged since v0.4), released in v0.5 {released_in}. Source index: "
            f"{rec.day}_source_index.csv; raw record file(s): {files}. Collector, export method and custody "
            "chain are not stated in the source."
        ),
        "limitations": rec.limitation,
        "content": content,
        "instructor_notes": _instructor_notes(s, rec.code),
    }


def _spec(s: Scenario, p: Packet, code: str, says: str, limit: str, seq: int) -> dict:
    if code in s.v03:
        return _v03_spec(s, s.v03[code], seq, f"packet {p.filename}")
    when, as_recorded = _v05_timestamp(says)
    return {
        "code": code,
        "sequence": seq,
        "title": p.title,
        "source_type": "Record summary (student packet)",
        "observed_at": when,
        "observed_timezone": "UTC" if when else None,
        "observed_as_recorded": as_recorded,
        "provenance": (
            f"HARBORLINE v0.5 student packet {p.day}/{p.filename} ({p.header}). Record summary as written in "
            "the packet; the underlying source export is not supplied. Collector, export method and custody "
            "chain are not stated in the source."
        ),
        "limitations": limit,
        "content": says,
        "instructor_notes": _instructor_notes(s, code),
    }


def inject_specs(s: Scenario) -> list[dict]:
    specs = []
    evidence = evidence_specs(s)
    for p in s.packets:
        code = f"INJ-{p.code}"
        if code not in evidence:
            continue
        specs.append(
            {
                "code": code,
                "sequence": p.number,
                "title": f"{p.code} {p.title}",
                "student_briefing": "\n\n".join(x for x in (p.header, p.briefing) if x),
                "instructor_notes": _gate_note(p),
                "track": p.track,
                "evidence": evidence[code],
            }
        )
    if "INJ-LAB" in evidence:
        specs.append(
            {
                "code": "INJ-LAB",
                "sequence": 99,
                "title": "Optional forensic follow-up exhibits (H-LAB-01/02/03)",
                "student_briefing": f"Records released: {', '.join(e['code'] for e in evidence['INJ-LAB'])}.",
                "instructor_notes": s.master.line_starting(OPTIONAL_LAB_NOTE_START),
                "track": None,
                "evidence": evidence["INJ-LAB"],
            }
        )
    return specs


def _gate_note(p: Packet) -> str:
    if not p.gate:
        return ""
    return (
        f"Release gate (Release_Register_v0.5): {p.gate}. Recipients: {p.recipients}. "
        f"Critical faculty restriction: {p.restriction}."
    )


def case_spec(s: Scenario) -> dict:
    with zipfile.ZipFile(INSTRUCTOR_ZIP) as z:
        readme = z.read("README.md").decode("utf-8")
    first = next(ln for ln in readme.splitlines() if ln.startswith("**"))
    last = next(ln for ln in reversed(readme.splitlines()) if ln.strip())
    return {
        "code": CASE_CODE,
        "title": "Operation HARBORLINE",
        # Students must not learn about the other squads' cases from the dossier header (Gate 1), so the
        # student-facing summary only says where their own material appears.
        "victim_organization": "Assigned per squad (fictional organizations)",
        "summary": "Your squad's case packets and records appear here as your instructor releases them.",
        "fictional_disclaimer": f"{first.strip('*')}\n\n{last}",
        "instructor_overview": s.master.one_paragraph,
    }


def release_plan(s: Scenario) -> list[dict]:
    """Per packet: the packet document (on its squad track) and, right after it, its records. Every gate is
    instructor-controlled (master: "Faculty-controlled evidence and decision gates"). Plus the faculty keys
    (staff only), the optional H-LAB exhibits, and the K01/K02 development knowledge checks."""
    items: list[dict] = []
    injects = {i["code"] for i in inject_specs(s)}
    for p in s.packets:
        base = p.number * 10
        items.append(
            {
                "code": f"PKT-{p.code}",
                "sequence": base,
                "item_type": "document",
                "title": f"{p.code} {p.title}",
                "document_code": p.document_code,
                "trigger_type": "manual",
                "track": p.track,
                "instructor_notes": _gate_note(p),
            }
        )
        if f"INJ-{p.code}" in injects:
            items.append(
                {
                    "code": f"EVI-{p.code}",
                    "sequence": base + 1,
                    "item_type": "evidence_inject",
                    "title": f"{p.code} records: " + ", ".join(i for ids, _, _ in p.rows for i in ids)[:180],
                    "inject_code": f"INJ-{p.code}",
                    "trigger_type": "after_item",
                    "trigger_after_code": f"PKT-{p.code}",
                    "instructor_notes": "Opens with its packet.",
                }
            )
    if "INJ-LAB" in injects:
        items.append(
            {
                "code": "EVI-LAB",
                "sequence": 145,
                "item_type": "evidence_inject",
                "title": "Optional forensic follow-up exhibits: H-LAB-01, H-LAB-02, H-LAB-03",
                "inject_code": "INJ-LAB",
                "trigger_type": "manual",
                "instructor_notes": s.master.line_starting(OPTIONAL_LAB_NOTE_START),
            }
        )
    for n, (code, title, start, end) in enumerate(KEY_SECTIONS):
        items.append(
            {
                "code": code,
                "sequence": 500 + n,
                "item_type": "answer_key",
                "audience": "staff",
                "title": title,
                "trigger_type": "manual",
                "body": s.master.between(start, end),
            }
        )
    for kc, day, time_, body, key in (
        ("K01", "Tue", "16:15", s.kc.k01, s.kc.k01_key),
        ("K02", "Fri", "11:15", s.kc.k02, s.kc.k02_key),
    ):
        items.append(
            {
                "code": f"CH-{kc}",
                "sequence": 600 + len(items),
                "item_type": "challenge",
                "scored": True,
                "instrument_code": kc,
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
                "sequence": 600 + len(items),
                "item_type": "answer_key",
                "audience": "staff",
                "title": f"Knowledge check {kc} — instructor key",
                "trigger_type": "manual",
                "answer_for_code": f"CH-{kc}",
                "body": key,
            }
        )
    return items


# --- E03/E04 P02 workspaces (from the packets' own tasks) -----------------------------------------------------
def p02_templates(s: Scenario) -> list[dict]:
    """Investigator and analyst P02 workspaces from packet 09 (the all-squad Tuesday directive whose turn-in is
    "E03/E04: P02 evidence") plus the analyst source ledger named in the Tuesday case supplements."""
    fusion = next(p for p in s.packets if p.number == 9)
    supplement = next(p for p in s.packets if p.number == 5)
    stops = ("Your assignment", "Restrictions and cautions", "Required handoff", "Turn-in")
    tasks = [re.sub(r"^\d+\.\s*", "", t) for t in fusion.section("Your assignment", stops)]
    restrictions = fusion.section("Restrictions and cautions", stops)
    handoff = fusion.section("Required handoff", stops)
    turn_in = fusion.section("Turn-in", stops)
    ledger_turn_in = supplement.section("Turn-in", stops)
    ledger_handoff = supplement.section("Required handoff", stops)
    if len(tasks) != 4 or not handoff:
        raise ValueError("Packet 09 layout changed: expected four assignment tasks and a required handoff")

    instructions = "\n".join(
        [
            f"{fusion.header} — {fusion.title}",
            "",
            fusion.briefing,
            "",
            "Your assignment:",
            *[f"{n}. {t}" for n, t in enumerate(tasks, start=1)],
            "",
            "Restrictions and cautions:",
            *[f"• {r}" for r in restrictions],
            "",
            "Required handoff:",
            *handoff,
            "",
            "Turn-in:",
            *turn_in,
        ]
    )
    brief = [
        {"key": f"brief_{k}", "kind": "text", "label": f"Joint brief — {label}", "prompt": handoff[0]}
        for k, label in (
            ("established", "Established"),
            ("assessed", "Assessed"),
            ("unknown", "Unknown"),
            ("next_action", "Next action"),
        )
    ]
    sections = [
        {"key": "coordinating_cell", "kind": "text", "label": "1. Coordinating cell", "prompt": tasks[0]},
        {
            "key": "correlation_chart",
            "kind": "table",
            "label": "2. Shared timeline and correlation chart",
            "prompt": tasks[1],
            "columns": [
                {"key": "source_id", "label": "Source ID"},
                {"key": "time", "label": "Time (UTC)"},
                {"key": "event", "label": "Event", "wide": True},
                {"key": "edge", "label": "Edge", "options": ["Corroborated", "Reported", "Inferred"]},
            ],
        },
        {
            "key": "preservation_plan",
            "kind": "table",
            "label": "3. Urgent preservation / collection plan",
            "prompt": tasks[2],
            "columns": [
                {"key": "source_id", "label": "Cross-case source"},
                {"key": "action", "label": "Preservation / collection", "wide": True},
                {"key": "owner", "label": "Owner"},
            ],
        },
        {
            "key": "reversible_fact",
            "kind": "text",
            "label": "4. A fact you would reverse",
            "prompt": tasks[3],
        },
        *brief,
    ]
    ledger = {
        "key": "source_ledger",
        "kind": "table",
        "label": "Analyst source ledger",
        "prompt": " ".join(ledger_turn_in + ledger_handoff),
        "columns": [
            {"key": "source_id", "label": "Source ID"},
            {"key": "source", "label": "Source", "wide": True},
            {"key": "confidence", "label": "Confidence"},
            {"key": "release_limitations", "label": "Release limitations", "wide": True},
        ],
    }
    return [
        {
            "code": "E03-P02-INV",
            "pathway": "investigator",
            "title": f"E03/E04 {fusion.title} — Investigator",
            "product_name": "P02 evidence (E03/E04)",
            "instructions": instructions,
            "sections": sections,
        },
        {
            "code": "E03-P02-ANA",
            "pathway": "analyst",
            "title": f"E03/E04 {fusion.title} — Intelligence Analyst",
            "product_name": "P02 evidence and analyst source ledger (E03/E04)",
            "instructions": instructions,
            "sections": [*sections, ledger],
        },
    ]
