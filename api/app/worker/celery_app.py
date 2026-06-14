"""Celery application. Ingestion/embedding tasks and the Beat schedule are added
in later phases (1, 3, 8). Phase 0 only needs the app to boot against Redis so the
`worker` and `beat` compose services start cleanly.

Both `celery_app` and the `app` alias are exposed so `-A app.worker.celery_app`
(as used in docker-compose.yml) resolves the instance.
"""

from __future__ import annotations

from celery import Celery

from app.core.config import get_settings

_settings = get_settings()

celery_app = Celery(
    "eudi",
    broker=_settings.redis_url,
    backend=_settings.redis_url,
    include=["app.worker.tasks"],
)
celery_app.conf.update(
    task_track_started=True,
    timezone="UTC",
    broker_connection_retry_on_startup=True,
)

# Phase 8: polling cadences from .env (run-and-test + eudi-source-registry
# freshness policy). Feeds several times daily, scrape ~6h, crawl daily,
# git pull ~12h. The feeds task triggers targeted re-ingest on new tags.
celery_app.conf.beat_schedule = {
    "collect-feeds": {
        "task": "collect_and_parse_feeds",
        "schedule": _settings.poll_feeds_interval,
    },
    "collect-scrape": {
        "task": "collect_and_parse_scrape",
        "schedule": _settings.scrape_issues_interval,
    },
    "collect-crawl": {
        "task": "collect_and_parse_crawl",
        "schedule": _settings.crawl_docs_interval,
    },
    "collect-git": {
        "task": "collect_and_parse_git",
        "schedule": _settings.git_pull_interval,
    },
    # S2: refresh structured entity summaries daily (after the day's ingestion).
    "summarize-entities": {
        "task": "summarize_entities",
        "schedule": _settings.crawl_docs_interval,
    },
}

# Alias for Celery's app autodiscovery via `-A app.worker.celery_app`.
app = celery_app
