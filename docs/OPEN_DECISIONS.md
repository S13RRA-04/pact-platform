# Open Decisions and Source Gaps

## Missing authoritative sources

- `PACT_LMS_Execution_Blueprint_v1.md` was not supplied.
- `PACT_LMS_Build_Backlog_v1.xlsx` was not supplied.
- The requested filenames include `(1)` suffixes, while the supplied curriculum files do not. The available files were used without changing their content.

## Approval-dependent decisions

- P02 rubric criteria are provisional development placeholders; cut scores, weighting, and mastery rules remain unconfigured.
- Imported objective-to-assessment relationships are preserved even where source sheets differ. See `docs/reports/curriculum_import_reconciliation.md`.
- M04 explanatory lesson content requires content/SME approval.
- M01-M03 and M05-M10 now have provenance-only authoring shells derived from imported metadata. They
  contain no approved teaching content and require authoritative lesson plans, curriculum-editor work,
  SME review, and content approval before production visibility.
- Enterprise identity, operational deployment, retention policy, permitted exports, and accreditation claims remain outside this prototype.

No student is automatically marked proficient from attendance, completion, quiz percentage, submission, or team performance.
