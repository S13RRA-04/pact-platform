# PACT Initial Milestone Implementation Plan

## Adopted architecture

- Modular monolith with a Next.js/React frontend and FastAPI API.
- PostgreSQL persistence through SQLAlchemy, with Alembic migrations.
- Backend-enforced session identity, cohort roles, pathway scoping, content visibility, and immutable submissions.
- Replaceable development identity provider; it is mounted only in development/test.
- Curriculum import retains source text and links, with a reconciliation report.

## Initial vertical slice

1. Import the supplied curriculum matrix and preserve M01-M10, E01-E10, P01-P05, K01-K02, and objective identifiers.
2. Seed the provisional M04 lesson, E03/P02 pathway-specific templates, demo cohort, personas, and fictional GLASS HARBOR evidence.
3. Support released-evidence viewing, draft persistence, immutable individual submission, staff review, provisional feedback, and inject release auditing.
4. Verify denial behavior for wrong pathway, unreleased evidence, evaluator material, and cross-cohort access.

## Source-to-work mapping

The execution blueprint and backlog workbook named in the request are not present. Therefore no authoritative backlog ticket IDs or acceptance-criteria mapping can be recorded. The implemented work is tracked by capability until those sources are supplied.
