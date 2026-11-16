from pathlib import Path

from app.curriculum_import.archives import import_curriculum_archives
from app.db import get_engine, make_sessionmaker

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("archives", type=Path, nargs="+")
    parser.add_argument("--course-version-id", type=int)
    args = parser.parse_args()
    with make_sessionmaker(get_engine())() as session:
        result = import_curriculum_archives(session, args.archives, args.course_version_id)
        print(f"Imported {result.imported}; deduplicated {result.deduplicated}")
