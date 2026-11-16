import time

from app.config import get_settings
from app.db import get_engine, make_sessionmaker
from app.services.background_jobs import build_notification_digests


def run() -> None:
    settings = get_settings()
    sessions = make_sessionmaker(get_engine(settings.database_url))
    while True:
        with sessions() as db:
            build_notification_digests(db)
        time.sleep(300)


if __name__ == "__main__":
    run()
