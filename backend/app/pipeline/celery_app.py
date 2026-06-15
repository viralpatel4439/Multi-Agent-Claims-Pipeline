from celery import Celery
from app.config import get_settings

settings = get_settings()

celery_app = Celery(
    "claims_pipeline",
    broker=settings.celery_broker_url,
    backend=settings.celery_result_backend,
    include=["app.pipeline.orchestrator"],
)

celery_app.conf.update(
    # Serialisation
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],

    # Reliability
    task_acks_late=True,              # task not acked until it completes → survives worker crash
    task_reject_on_worker_lost=True,  # re-queue if the worker process is killed mid-task
    worker_prefetch_multiplier=1,     # one task per worker slot — prevents starvation
    task_track_started=True,

    # Timeouts (Ollama vision can take up to ~3 min on cold GPU)
    task_soft_time_limit=600,
    task_time_limit=720,              # hard kill after 12 min

    # Memory leak guard: recycle each worker process after 100 tasks
    worker_max_tasks_per_child=100,

    # Results
    result_expires=3600,

    # Named queue — all pipeline tasks go here.
    # Workers are started with --queues=pipeline so you can scale independently.
    task_default_queue="pipeline",
    task_routes={"tasks.run_full_pipeline": {"queue": "pipeline"}},

    worker_hijack_root_logger=False,
)

import logging
logging.basicConfig(level=logging.INFO)
