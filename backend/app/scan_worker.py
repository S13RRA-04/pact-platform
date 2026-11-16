import time

from app.config import get_settings
from app.db import get_engine, make_sessionmaker
from app.services.background_jobs import process_scan_job


def run() -> None:
    settings = get_settings()
    sessions = make_sessionmaker(get_engine(settings.database_url))
    while True:
        with sessions() as db:
            processed = process_scan_job(db, settings)
        time.sleep(1 if processed else 10)


if __name__ == "__main__":
    run()
