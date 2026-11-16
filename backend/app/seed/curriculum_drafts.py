"""Provenance-only lesson authoring shells for modules without supplied lesson plans.

These records are intentionally draft content. They reorganize imported workbook metadata but do not
add instructional claims, exercises, legal guidance, thresholds, or approval decisions.
"""

from __future__ import annotations

from app.models import Lesson, Module


def lesson_shell(module: Module) -> Lesson:
    source_items = [
        value.strip()
        for value in (module.instructional_content, module.required_output)
        if value and value.strip()
    ]
    sections: list[dict[str, object]] = [
        {
            "kind": "callout",
            "heading": "Authoring status",
            "body": (
                "Draft authoring shell only. An approved lesson plan, instructor guide, learner materials, "
                "and content-review decision have not been supplied. Do not use this shell for delivery."
            ),
        }
    ]
    if source_items:
        sections.append(
            {
                "kind": "list",
                "heading": "Imported curriculum source text",
                "items": source_items,
            }
        )
    sections.append(
        {
            "kind": "callout",
            "heading": "Required authoring work",
            "body": (
                "A curriculum editor must add source-grounded instruction and activities; an authorized "
                "content approver must review the resulting version before production visibility."
            ),
        }
    )
    return Lesson(
        module_id=module.id,
        code=f"{module.code}-L1",
        sequence=1,
        title=f"{module.title} — authoring shell",
        duration_minutes=None,
        sections=sections,
        approval_status="draft",
        provenance_note=(
            f"Structure derived only from imported curriculum metadata for {module.code}. "
            "No authoritative lesson plan was supplied; content and approval remain unresolved."
        ),
    )
