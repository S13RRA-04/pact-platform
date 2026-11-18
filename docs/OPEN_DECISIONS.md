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

## Operation HARBORLINE (v0.5) decisions for the curriculum owner

v0.5 is the canonical scenario (curriculum owner decision, 17 Nov 2026). v0.3 is retired and its exercise
suite is staff reference material only (Course Materials); nothing from v0.3 is released to students except
the locked H- records that v0.5 itself reuses.

- **Every gate is instructor-released.** Each staged packet (HBL-01–17) is a manual release-plan item and its
  records open with it. This follows the master's "Faculty-controlled evidence and decision gates" (e.g.
  packet 09 only after students identify the KMS overlap; packets 12–14 only after the simulated warrant
  ruling). If faculty want some gates automatic (for example Monday packets on M01 "released"), change the
  trigger in a new plan version.
- **Squad tracks.** Monday/Tuesday case packets (01–08) are released to one squad's case (A–D) and
  Wednesday search returns (12–14) to one site team (418 / R12 / C14), taken from the packet headers and
  record IDs. Instructors assign each squad a case and site team on the Squads screen. Students without a
  squad see only all-squad packets. Confirm: after HX-COORD-01 (packet 09), should squads see each other's
  case records, or keep sharing only through handoffs as now ("do not circulate other squads' details
  without instructor release")?
- **Record wording.** Non-H records are the packet's own row ("what the record says" / "what it does not
  establish"); the underlying source exports are not supplied in v0.5. The locked H- records keep their v0.3
  observation, limitation and raw lines (same IDs and times), which also splits rows that list two IDs
  (H-EDR-01 / H-IAM-01). Packet times omit the year; 2026 is taken from the case packets. Where a record has
  several times (X-C-02), the first is used for the timeline and labelled as such.
- **Records v0.5 does not release.** H-AI-01, H-FIN-02, H-FOR-01/02 and H-ATR-01 are not in any v0.5
  packet and are not in the scenario. H-LAB-01/02/03 are an optional manual release ("Retain H-LAB-01/02/03
  only as optional forensic follow-up exhibits after search").
- **P02 workspace.** E03/E04 P02 is built from packet 09's four tasks and joint brief (its turn-in is
  "E03/E04: P02 evidence"), plus the analyst source ledger named in the Tuesday supplements. Packets 01, 10,
  11 and 12–17 name other products (P01 intake brief, PC-NEXUS-1, WARRANT-1, SITE-A, P04, P05, GJ-GRID) that
  have no workspace yet; v0.5's README says E05/E06 and P04/P05 descriptions and rubric alignment still need
  updating before pilot delivery.
- **Faculty keys.** AK-OVERVIEW … AK-FRI and AK-GATES are the instructor master split at its own act
  headings (staff only). Counsel and SME review are required by the master before assessed delivery.
- **Development approvals.** Documents, injects and the release plan are approved by the synthetic Content
  Approver persona in development data only. They are not curriculum sign-off.
- **K01/K02.** The v0.3 development items remain as scored knowledge checks and stay blocked until the
  instruments are authorized for scored use; the source states they are "not the approved secure exam".
  Check whether they still fit the v0.5 storyline.
- **Slide decks.** Each module page links its Presentation Suite v0.2 deck. Decks are drafts (staff only)
  until approved; v0.5's README says the decks still need re-synchronising with the v0.5 storyline. Note:
  the deck importer marks decks "clean" without virus scanning (`scan_engine = trusted-admin-import`); route
  them through the scan queue before production.

No student is automatically marked proficient from attendance, completion, quiz percentage, submission, or team performance.
