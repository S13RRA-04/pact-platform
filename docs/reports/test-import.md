# Curriculum Import Reconciliation Report

_Generated deterministically by `python -m app.curriculum_import`. Do not edit by hand._

- **Source file:** `PACT_Task_Objective_Assessment_Matrix_v0.1.xlsx`
- **SHA-256:** `d76f434d3fd3383fb43d2d94580ff5c6947aee4662b4ccbb858ea9a9473fbb1d`
- **Source document status:** Working design v0.1 — 2026-11-16; not an accredited or approved curriculum
- **Imported status:** provisional (course version locked; not approved for delivery)

## Counts

| Item | Count |
|---|---|
| objectives | 13 |
| tasks | 13 |
| modules | 10 |
| schedule_blocks | 45 |
| instruments | 7 |
| qa_gates | 20 |
| action_items | 12 |
| links | 282 |

## Issues

Relationships are stored per source sheet (`curriculum_links.source_sheet`). Conflicts below are **unresolved** and require curriculum-owner decision; the importer does not choose a winning sheet.

| # | Severity | Category | Subject | Detail |
|---|---|---|---|---|
| 1 | conflict | exercise_objective_mismatch | E04 | E04 objective links differ between sheets — POI Schedule: A02, C03, I02; Objectives: C03; Traceability: C03. Preserved as stated per sheet; not reconciled. |
| 2 | conflict | exercise_objective_mismatch | E05 | E05 objective links differ between sheets — POI Schedule: A02, C04, I03; Objectives: A02, C02, C04, I03; Traceability: A02, C02, C04, I03. Preserved as stated per sheet; not reconciled. |
| 3 | conflict | exercise_objective_mismatch | E08 | E08 objective links differ between sheets — POI Schedule: A03, I04, J01; Objectives: A03, C04, I04, J01; Traceability: A03, C04, I04, J01. Preserved as stated per sheet; not reconciled. |
| 4 | conflict | exercise_objective_mismatch | E10 | E10 objective links differ between sheets — POI Schedule: A04, I04, J01; Objectives: (none); Traceability: (none). Preserved as stated per sheet; not reconciled. |
| 5 | conflict | instrument_objective_mismatch | K02 | K02 objective links differ between sheets — Assessments: C01, C02, C03, C04; Objectives: (none); Traceability: (none). Preserved as stated per sheet; not reconciled. |
| 6 | conflict | instrument_objective_mismatch | P04 | P04 objective links differ between sheets — Assessments: A03, A04, C03, C04, I02, I04; Objectives: A03, C04, I02; Traceability: A03, C04, I02. Preserved as stated per sheet; not reconciled. |
| 7 | conflict | module_objective_mismatch | M02 | M02 objective links differ between sheets — Modules: A01, C03, I01, I02; Objectives: A01, C03, I01, I02; POI Schedule: C03, I02; Traceability: A01, C03, I01, I02. Preserved as stated per sheet; not reconciled. |
| 8 | conflict | module_objective_mismatch | M05 | M05 objective links differ between sheets — Modules: A02, C03, I02; Objectives: A02, C03, I02; POI Schedule: A02, C03; Traceability: A02, C03, I02. Preserved as stated per sheet; not reconciled. |
| 9 | conflict | module_objective_mismatch | M09 | M09 objective links differ between sheets — Modules: A03, A04, C04, I04; Objectives: A03, A04, C04, I04; POI Schedule: A03, C04, I04; Traceability: A03, A04, C04, I04. Preserved as stated per sheet; not reconciled. |
| 10 | warning | criteria_undefined | Traceability | 18 objective–assessment linkages have 'Individual criterion TBD'. Rubric criteria cannot be imported; P02 development criteria are provisional. |
| 11 | warning | exercise_type_ambiguity | E10 | E10 is coded as an exercise ID but its POI block type is 'Assessment'. |
| 12 | warning | module_not_scheduled | M07 | M07 appears on the Modules sheet but has no block in the POI Schedule. |
| 13 | warning | module_not_scheduled | M10 | M10 appears on the Modules sheet but has no block in the POI Schedule. |
| 14 | info | validation_status | ALL | All objectives are 'Proposed' and all tasks 'Not validated'. Imported as provisional; no task validation, cut score, or approval is implied. |
