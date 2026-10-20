from sqlalchemy.exc import OperationalError

from escala_analyzer.infrastructure.database.connection import Database
from escala_analyzer.settings import Settings

from .celery_app import celery_app
from .runner import JobRunner


@celery_app.task(
    name="escala.execute",
    autoretry_for=(OperationalError,),
    retry_backoff=True,
    retry_jitter=True,
    max_retries=3,
)
def execute_job(job_id: str) -> None:
    settings = Settings()
    database = Database(settings.database_url)
    try:
        JobRunner(database, settings).execute(job_id)
    finally:
        database.engine.dispose()
