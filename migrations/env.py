from alembic import context

from escala_analyzer.infrastructure.database.connection import Database
from escala_analyzer.infrastructure.database.models import Base
from escala_analyzer.settings import Settings


def run() -> None:
    database = Database(Settings().database_url)
    try:
        with database.engine.connect() as connection:
            context.configure(
                connection=connection, target_metadata=Base.metadata, compare_type=True
            )
            with context.begin_transaction():
                context.run_migrations()
    finally:
        database.engine.dispose()


run()
