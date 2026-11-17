"""Dedicated scheduled-release worker process with durable health metrics."""

from __future__ import annotations

import logging
import socket
import time
import uuid
from datetime import UTC, datetime

from sqlalchemy import func, select

from app.config import get_settings
from app.db import get_engine, make_sessionmaker
from app.models import LessonRelease, WorkerHeartbeat
from app.services.lesson_delivery import open_due_releases
from app.services.release_plan import process_due as process_due_plan_items

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("pact.scheduler")


def run() -> None:
    settings = get_settings()
    instance = f"{socket.gethostname()}-{uuid.uuid4().hex[:8]}"
    started = datetime.now(UTC)
    sessions = make_sessionmaker(get_engine(settings.database_url))
    while True:
        now = datetime.now(UTC)
        with sessions() as db:
            heartbeat = db.get(WorkerHeartbeat, "release-scheduler") or WorkerHeartbeat(
                worker_name="release-scheduler",
                instance_id=instance,
                last_started_at=started,
                last_heartbeat_at=now,
                processed_count=0,
                max_release_lag_seconds=0,
            )
            heartbeat.instance_id = instance
            heartbeat.last_heartbeat_at = now
            try:
                oldest = db.scalar(
                    select(func.min(LessonRelease.scheduled_for)).where(
                        LessonRelease.state == "scheduled", LessonRelease.scheduled_for <= now
                    )
                )
                processed = open_due_releases(db)
                processed += process_due_plan_items(db)
                db.commit()
                heartbeat.processed_count += processed
                heartbeat.last_success_at = now
                heartbeat.last_error = None
                heartbeat.max_release_lag_seconds = (
                    max(0, int((now - oldest).total_seconds())) if oldest else 0
                )
                log.info(
                    "release_scan processed=%s lag_seconds=%s", processed, heartbeat.max_release_lag_seconds
                )
            except Exception as exc:
                db.rollback()
                heartbeat.last_error = str(exc)[:2000]
                log.exception("release scan failed")
            db.merge(heartbeat)
            db.commit()
        time.sleep(settings.scheduler_interval_seconds)


if __name__ == "__main__":
    run()
