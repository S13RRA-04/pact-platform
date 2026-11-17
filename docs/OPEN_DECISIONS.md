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

## Case HARBORLINE (v0.3) decisions for the curriculum owner

- **H-PXY-02 release point.** The record is in the Day 2 source index but in no exercise's "Only release
  current record(s)" checklist. It is released with E03 because the faculty release plan releases the
  "Day2 proxy" records on Tuesday morning. Confirm or move it.
- **v0.3 single case vs v0.5 four-case packets.** The evidence library, injects, E03 workspaces, exercise
  packets and K01/K02 items follow the v0.3 suite (one victim, Northbank Regional Medical). The release plan
  also carries the separately imported v0.5 staged packets (HBL-01–17: Cases A–D) as lesson-stage blocks.
  Decide whether v0.5 supersedes v0.3, and which one the evidence library should follow.
- **Evidence released per exercise, manually.** Each exercise's records are an instructor-released batch
  (E03 packet: "Your instructor controls when new evidence is released"). Packets open when the module's
  lesson is marked taught. Adjust timing in the release plan if faculty want otherwise.
- **Development approvals.** Suite documents, injects and the release plan are approved by the synthetic
  Content Approver persona in development data only. They are not curriculum sign-off.
- **K01/K02.** The v0.3 development items are imported as scored knowledge checks and stay blocked until the
  instruments are authorized for scored use; the source states they are "not the approved secure exam".
- **Slide decks.** Each module page links its Presentation Suite v0.2 deck. Decks are drafts (staff only)
  until approved. Note: the deck importer marks decks "clean" without virus scanning
  (`scan_engine = trusted-admin-import`); route them through the scan queue before production.

No student is automatically marked proficient from attendance, completion, quiz percentage, submission, or team performance.
