"""CLI: python -m app.curriculum_import [workbook.xlsx]"""

import sys
from pathlib import Path

from app.config import REPO_ROOT, get_settings
from app.curriculum_import.importer import import_workbook
from app.db import get_engine, make_sessionmaker

REPORT = REPO_ROOT / "docs" / "reports" / "curriculum_import_reconciliation.md"


def main() -> None:
    source = Path(sys.argv[1]) if len(sys.argv) > 1 else get_settings().curriculum_source
    with make_sessionmaker(get_engine())() as db:
        run = import_workbook(db, source, REPORT)
        db.commit()
        print(
            f"Import {run.outcome}: course_version_id={run.course_version_id} sha256={run.source_sha256[:12]}"
        )
        print(f"Summary: {run.summary}")
        print(f"Report: {REPORT}")


if __name__ == "__main__":
    main()
