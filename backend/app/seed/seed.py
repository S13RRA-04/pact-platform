"""Synthetic seed data. Refuses to run outside development/test environments."""

from __future__ import annotations

from datetime import date
from pathlib import Path

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.config import Settings
from app.curriculum_import.importer import import_workbook
from app.models import (
    ApprovalRequest,
    AssessmentInstrument,
    Base,
    Cohort,
    CohortMembership,
    CourseVersion,
    Exercise,
    Lesson,
    LessonRelease,
    Module,
    RubricCriterion,
    Squad,
    SquadMember,
    User,
    UserRole,
)
from app.seed import m04_content as m04
from app.seed.curriculum_drafts import lesson_shell
from app.seed.harborline_install import DEV_SQUAD_TRACKS, install_harborline

EMAIL_DOMAIN = "pact-training.example"

# username, display name, persona label, global roles, [(cohort_code, role, pathway, squad)]
PERSONAS: list[tuple[str, str, str, list[str], list[tuple[str, str, str | None, str | None]]]] = [
    (
        "inv.brooks",
        "Taylor Brooks",
        "Student — Investigator",
        [],
        [("PACT-DEMO-01", "student", "investigator", "Alpha")],
    ),
    (
        "ana.ellis",
        "Morgan Ellis",
        "Student — Intelligence Analyst",
        [],
        [("PACT-DEMO-01", "student", "analyst", "Alpha")],
    ),
    (
        "inv.patel",
        "Drew Patel",
        "Student — Investigator",
        [],
        [("PACT-DEMO-01", "student", "investigator", "Bravo")],
    ),
    (
        "ana.okoro",
        "Jules Okoro",
        "Student — Intelligence Analyst",
        [],
        [("PACT-DEMO-01", "student", "analyst", "Bravo")],
    ),
    ("instr.lin", "Casey Lin", "Instructor", [], [("PACT-DEMO-01", "instructor", None, None)]),
    ("eval.shah", "Riley Shah", "Evaluator", [], [("PACT-DEMO-01", "evaluator", None, None)]),
    ("curr.ortega", "Sam Ortega", "Curriculum Editor", ["curriculum_editor"], []),
    ("appr.whitfield", "Dana Whitfield", "Content Approver", ["content_approver"], []),
    ("admin.novak", "Jamie Novak", "Program Administrator", ["program_admin"], []),
    ("secops.kim", "Avery Kim", "Security/Operations Administrator", ["secops_admin"], []),
    (
        "inv.harper",
        "Quinn Harper",
        "Student — Investigator (Cohort 02)",
        [],
        [("PACT-DEMO-02", "student", "investigator", "Alpha")],
    ),
    (
        "instr.reyes",
        "Robin Reyes",
        "Instructor (Cohort 02)",
        [],
        [("PACT-DEMO-02", "instructor", None, None)],
    ),
]

COHORTS = [
    ("PACT-DEMO-01", "PACT Synthetic Pilot Cohort 01", date(2026, 10, 26), date(2026, 10, 30)),
    ("PACT-DEMO-02", "PACT Synthetic Comparison Cohort 02", date(2026, 11, 30), date(2026, 12, 4)),
]
COHORT_INSTRUCTOR = {"PACT-DEMO-01": "instr.lin", "PACT-DEMO-02": "instr.reyes"}


def _guard(settings: Settings) -> None:
    if settings.env not in ("development", "test"):
        raise RuntimeError("Seeding synthetic data is only permitted in development or test environments")


def reset(db: Session) -> None:
    """Truncate every application table (TRUNCATE bypasses the append-only row triggers by design)."""
    tables = ", ".join(t.name for t in Base.metadata.sorted_tables)
    db.execute(text(f"TRUNCATE {tables} RESTART IDENTITY CASCADE"))
    db.commit()


def seed(db: Session, settings: Settings, workbook: Path, report_path: Path | None = None) -> None:
    _guard(settings)
    if db.scalar(select(User).limit(1)) is not None:
        # Add newly introduced draft authoring shells to an existing synthetic development database.
        # This is intentionally additive: learner work and existing curriculum records are untouched.
        current = db.scalar(select(CourseVersion).order_by(CourseVersion.id.desc()).limit(1))
        if current is not None:
            for draft_module in db.scalars(
                select(Module)
                .where(Module.course_version_id == current.id, Module.code != "M04")
                .order_by(Module.sequence)
            ):
                has_lesson = db.scalar(select(Lesson.id).where(Lesson.module_id == draft_module.id).limit(1))
                if has_lesson is None:
                    db.add(lesson_shell(draft_module))
            db.commit()
        return

    run = import_workbook(db, workbook, report_path)
    cv_id = run.course_version_id
    assert cv_id is not None

    # --- People, cohorts, squads -----------------------------------------------------------
    cohorts: dict[str, Cohort] = {}
    for code, name, start, end in COHORTS:
        cohorts[code] = Cohort(
            code=code,
            name=name,
            course_version_id=cv_id,
            start_date=start,
            end_date=end,
            timezone="America/Chicago",
        )
        db.add(cohorts[code])
    db.flush()

    squads: dict[tuple[str, str], Squad] = {}
    users: dict[str, User] = {}
    for username, display, label, roles, memberships in PERSONAS:
        user = User(
            username=username,
            display_name=display,
            email=f"{username}@{EMAIL_DOMAIN}",
            is_synthetic=True,
            is_dev_persona=True,
            persona_label=label,
        )
        user.roles = [UserRole(role=r) for r in roles]
        db.add(user)
        db.flush()
        users[username] = user
        for cohort_code, role, pathway, squad_name in memberships:
            cohort = cohorts[cohort_code]
            db.add(CohortMembership(cohort_id=cohort.id, user_id=user.id, role=role, pathway=pathway))
            if squad_name:
                key = (cohort_code, squad_name)
                if key not in squads:
                    case_track, site_team = DEV_SQUAD_TRACKS.get(squad_name, (None, None))
                    squads[key] = Squad(
                        cohort_id=cohort.id, name=squad_name, case_track=case_track, site_team=site_team
                    )
                    db.add(squads[key])
                    db.flush()
                db.add(SquadMember(squad_id=squads[key].id, user_id=user.id))
    db.flush()

    # --- M04 provisional lesson ------------------------------------------------------------
    module = db.scalar(select(Module).where(Module.course_version_id == cv_id, Module.code == "M04"))
    assert module is not None
    m04_lesson = Lesson(
        module_id=module.id,
        code=m04.M04_LESSON["code"],
        sequence=1,
        title=m04.M04_LESSON["title"],
        duration_minutes=m04.M04_LESSON["duration_minutes"],
        sections=m04.M04_LESSON["sections"],
        approval_status="draft",
        provenance_note=m04.LESSON_PROVENANCE,
    )
    db.add(m04_lesson)
    db.flush()

    # --- Provenance-only authoring shells --------------------------------------------------
    # These remain draft and are visible only in development/test. They are not approved lessons.
    for draft_module in db.scalars(
        select(Module)
        .where(Module.course_version_id == cv_id, Module.code != "M04")
        .order_by(Module.sequence)
    ):
        db.add(lesson_shell(draft_module))

    # --- P02 development rubric criteria ---------------------------------------------------
    p02 = db.scalar(
        select(AssessmentInstrument).where(
            AssessmentInstrument.course_version_id == cv_id, AssessmentInstrument.code == "P02"
        )
    )
    e03 = db.scalar(select(Exercise).where(Exercise.course_version_id == cv_id, Exercise.code == "E03"))
    assert p02 is not None and e03 is not None
    for seq, (code, title, desc) in enumerate(m04.P02_CRITERIA, start=1):
        db.add(
            RubricCriterion(
                instrument_id=p02.id,
                code=code,
                sequence=seq,
                pathway="common",
                title=title,
                description=desc,
                approval_status="draft",
                source_note=m04.RUBRIC_SOURCE,
            )
        )

    for code, cohort in cohorts.items():
        instructor = users[COHORT_INSTRUCTOR[code]]
        db.add(LessonRelease(lesson_id=m04_lesson.id, cohort_id=cohort.id, released_by_id=instructor.id))
    db.flush()

    # --- Operation HARBORLINE (v0.5 staged packets) -------------------------------------------
    install_harborline(
        db, activate=[(cohort, users[COHORT_INSTRUCTOR[code]].id) for code, cohort in cohorts.items()]
    )

    # --- Pending approvals (separate workflows) --------------------------------------------
    editor = users["curr.ortega"]
    db.add(
        ApprovalRequest(
            workflow="assessment_authorization",
            entity_type="assessment_instrument",
            entity_id=p02.id,
            entity_code="P02",
            summary="Authorize P02 rubric for scored use. Blocked: criteria are development "
            "placeholders; standard setting (Q12) not performed.",
            requested_by_id=editor.id,
        )
    )
    db.commit()


def main() -> None:
    import argparse

    from app.config import REPO_ROOT, get_settings
    from app.db import get_engine, make_sessionmaker

    parser = argparse.ArgumentParser(description="Seed synthetic PACT development data")
    parser.add_argument("--reset", action="store_true", help="truncate all tables first")
    parser.add_argument(
        "--harborline",
        action="store_true",
        help="install HARBORLINE v0.5 into an existing database and move cohorts off retired versions",
    )
    args = parser.parse_args()
    settings = get_settings()
    _guard(settings)
    with make_sessionmaker(get_engine())() as db:
        if args.harborline:
            print(install_harborline(db, switch_existing=True))
            return
        if args.reset:
            reset(db)
        seed(
            db,
            settings,
            settings.curriculum_source,
            REPO_ROOT / "docs" / "reports" / "curriculum_import_reconciliation.md",
        )
        print("Seed complete:", db.scalar(text("SELECT count(*) FROM users")), "synthetic users")


if __name__ == "__main__":
    main()
