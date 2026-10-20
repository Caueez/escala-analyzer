"""JSON-only task transport; PostgreSQL is the source of job results."""

from celery import Celery
from kombu import Queue

from escala_analyzer.infrastructure.observability.logging import configure_logging
from escala_analyzer.settings import Settings

configure_logging()
settings = Settings()
celery_app = Celery(
    "escala", broker=settings.broker_url, include=["escala_analyzer.infrastructure.messaging.tasks"]
)
celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    task_ignore_result=True,
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    worker_prefetch_multiplier=1,
    control_queue_exclusive=True,
    event_queue_exclusive=True,
    worker_cancel_long_running_tasks_on_connection_loss=True,
    worker_max_tasks_per_child=10,
    task_soft_time_limit=150,
    task_time_limit=180,
    broker_connection_retry_on_startup=True,
    broker_transport_options={"confirm_publish": True},
    task_queues=(Queue("analysis", durable=True), Queue("optimization", durable=True)),
    task_default_delivery_mode="persistent",
    timezone="UTC",
    enable_utc=True,
)
