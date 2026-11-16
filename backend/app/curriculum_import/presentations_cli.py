from pathlib import Path

from app.curriculum_import.presentations import import_presentations
from app.db import get_engine, make_sessionmaker

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("suite_dir", type=Path)
    parser.add_argument("--course-version-id", type=int)
    args = parser.parse_args()
    with make_sessionmaker(get_engine())() as session:
        print(f"Imported {import_presentations(session, args.suite_dir, args.course_version_id)} records")
