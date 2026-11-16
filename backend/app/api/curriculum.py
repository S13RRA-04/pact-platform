from __future__ import annotations

from collections import defaultdict
from datetime import date, timedelta

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import audit
from app.db import get_db
from app.models import (
    AssessmentInstrument,
    Cohort,
    CourseVersion,
    CurriculumLink,
    Exercise,
    Lesson,
    LessonProgress,
    Module,
    Objective,
    ScheduleBlock,
)
from app.schemas.common import (
    ExerciseOut,
    InstrumentOut,
    LessonOut,
    ModuleDetailOut,
    ModuleSummaryOut,
    ObjectiveOut,
    ScheduleBlockOut,
)
from app.security.authz import Principal, deny, get_principal, require_csrf_header
from app.services.lesson_delivery import visible_lesson_ids
from app.services.visibility import content_visible

router = APIRouter(prefix="/api/curriculum", tags=["curriculum"])


def course_version_for(db: Session, principal: Principal) -> CourseVersion:
    """Students/staff see their cohort's version; global roles see the latest imported version."""
    cohort_ids = sorted({m.cohort_id for m in principal.memberships})
    if cohort_ids:
        cohort = db.get(Cohort, cohort_ids[0])
        assert cohort is not None
        cv = db.get(CourseVersion, cohort.course_version_id)
    else:
        cv = db.scalar(select(CourseVersion).order_by(CourseVersion.id.desc()).limit(1))
    if cv is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No curriculum imported")
    return cv


def schedule_out(db: Session, cv_id: int, start: date | None) -> list[ScheduleBlockOut]:
    blocks = db.scalars(
        select(ScheduleBlock).where(ScheduleBlock.course_version_id == cv_id).order_by(ScheduleBlock.sequence)
    )
    out = []
    for b in blocks:
        item = ScheduleBlockOut.model_validate(b)
        if start is not None and b.day_index >= 0:
            item.date = start + timedelta(days=b.day_index)
        out.append(item)
    return out


def module_summaries(db: Session, cv_id: int) -> list[ModuleSummaryOut]:
    modules = db.scalars(
        select(Module).where(Module.course_version_id == cv_id).order_by(Module.sequence)
    ).all()
    links = db.scalars(
        select(CurriculumLink).where(
            CurriculumLink.course_version_id == cv_id,
            CurriculumLink.source_sheet == "Modules",
            CurriculumLink.link_type == "module_objective",
        )
    )
    by_module: dict[str, list[str]] = defaultdict(list)
    for lk in links:
        by_module[lk.from_code].append(lk.to_code)
    blocks = db.scalars(
        select(ScheduleBlock).where(
            ScheduleBlock.course_version_id == cv_id, ScheduleBlock.ref_code.is_not(None)
        )
    )
    sched: dict[str, list[str]] = defaultdict(list)
    for b in blocks:
        sched[b.ref_code or ""].append(f"{b.day} {b.start_time}–{b.end_time}")
    out = []
    for m in modules:
        lessons = [ls for ls in m.lessons if content_visible(ls.approval_status)]
        out.append(
            ModuleSummaryOut(
                code=m.code,
                sequence=m.sequence,
                title=m.title,
                teaching_mode=m.teaching_mode,
                required_output=m.required_output,
                objective_codes=sorted(by_module[m.code]),
                lesson_count=len(lessons),
                schedule=sched.get(m.code, []),
            )
        )
    return out


@router.get("/modules", response_model=list[ModuleSummaryOut])
def list_modules(
    principal: Principal = Depends(get_principal), db: Session = Depends(get_db)
) -> list[ModuleSummaryOut]:
    return module_summaries(db, course_version_for(db, principal).id)


@router.get("/modules/{code}", response_model=ModuleDetailOut)
def module_detail(
    code: str, principal: Principal = Depends(get_principal), db: Session = Depends(get_db)
) -> ModuleDetailOut:
    cv = course_version_for(db, principal)
    module = db.scalar(select(Module).where(Module.course_version_id == cv.id, Module.code == code))
    if module is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Module not found")
    links = list(
        db.scalars(
            select(CurriculumLink).where(
                CurriculumLink.course_version_id == cv.id,
                CurriculumLink.link_type == "module_objective",
                CurriculumLink.from_code == code,
            )
        )
    )
    by_sheet: dict[str, list[str]] = defaultdict(list)
    for lk in links:
        by_sheet[lk.source_sheet].append(lk.to_code)
    obj_codes = sorted(set(by_sheet.get("Modules", [])))
    objectives = db.scalars(
        select(Objective)
        .where(Objective.course_version_id == cv.id, Objective.code.in_(obj_codes))
        .order_by(Objective.code)
    )
    # Exercises scheduled with this module: from the POI sequence (blocks until the next module block).
    blocks = schedule_out(db, cv.id, None)
    ex_codes: list[str] = []
    in_module = False
    for b in blocks:
        if b.ref_code and b.ref_code.startswith("M"):
            in_module = b.ref_code == code
        elif in_module and b.ref_code and b.ref_code.startswith("E"):
            ex_codes.append(b.ref_code)
    exercises = list(
        db.scalars(
            select(Exercise).where(Exercise.course_version_id == cv.id, Exercise.code.in_(ex_codes or [""]))
        )
    )
    inst_codes = sorted(
        {
            lk.to_code
            for lk in db.scalars(
                select(CurriculumLink).where(
                    CurriculumLink.course_version_id == cv.id,
                    CurriculumLink.link_type == "exercise_instrument",
                    CurriculumLink.from_code.in_(ex_codes or [""]),
                )
            )
        }
    )
    instruments = list(
        db.scalars(
            select(AssessmentInstrument).where(
                AssessmentInstrument.course_version_id == cv.id,
                AssessmentInstrument.code.in_(inst_codes or [""]),
            )
        )
    )
    reviewed = {
        p.lesson_id for p in db.scalars(select(LessonProgress).where(LessonProgress.user_id == principal.id))
    }
    lessons = []
    student_memberships = principal.student_memberships()
    released_ids: set[int] | None = None
    if student_memberships:
        cohort_id = student_memberships[0].cohort_id
        released_ids = visible_lesson_ids(db, cohort_id)
    for ls in module.lessons:
        if content_visible(ls.approval_status) and (released_ids is None or ls.id in released_ids):
            lo = LessonOut.model_validate(ls)
            lo.reviewed = ls.id in reviewed
            lessons.append(lo)
    return ModuleDetailOut(
        code=module.code,
        title=module.title,
        teaching_mode=module.teaching_mode,
        instructional_content=module.instructional_content,
        required_output=module.required_output,
        objectives=[ObjectiveOut.model_validate(o) for o in objectives],
        objective_links_by_sheet={k: sorted(v) for k, v in sorted(by_sheet.items())},
        lessons=lessons,
        exercises=[ExerciseOut.model_validate(e) for e in exercises],
        instruments=[InstrumentOut.model_validate(i) for i in instruments],
        schedule=[b for b in blocks if b.ref_code == code or b.ref_code in ex_codes],
        course_version=cv.version_label,
        course_version_status=cv.status,
    )


@router.get("/objectives", response_model=list[ObjectiveOut])
def list_objectives(
    principal: Principal = Depends(get_principal), db: Session = Depends(get_db)
) -> list[Objective]:
    cv = course_version_for(db, principal)
    return list(
        db.scalars(select(Objective).where(Objective.course_version_id == cv.id).order_by(Objective.id))
    )


@router.post("/lessons/{lesson_id}/reviewed", status_code=204, dependencies=[Depends(require_csrf_header)])
def mark_reviewed(
    lesson_id: int, principal: Principal = Depends(get_principal), db: Session = Depends(get_db)
) -> None:
    """Records lesson review for progress display only. Never evidence of proficiency."""
    lesson = db.get(Lesson, lesson_id)
    memberships = principal.student_memberships()
    if lesson is None or not memberships or not content_visible(lesson.approval_status):
        raise deny(db, principal, action="lesson.mark_reviewed", entity_type="lesson", entity_id=lesson_id)
    cohort_id = memberships[0].cohort_id
    exists = db.scalar(
        select(LessonProgress).where(
            LessonProgress.lesson_id == lesson_id,
            LessonProgress.user_id == principal.id,
            LessonProgress.cohort_id == cohort_id,
        )
    )
    if exists is None:
        db.add(LessonProgress(lesson_id=lesson_id, user_id=principal.id, cohort_id=cohort_id))
        audit.record(
            db,
            actor_id=principal.id,
            action="lesson.reviewed",
            entity_type="lesson",
            entity_id=lesson_id,
            cohort_id=cohort_id,
        )
        db.commit()
