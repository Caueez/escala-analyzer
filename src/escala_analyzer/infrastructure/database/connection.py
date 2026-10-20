"""One short-lived SQLAlchemy session per operation; no shared mutable session."""

from sqlalchemy import create_engine, event, text
from sqlalchemy.orm import sessionmaker


class Database:
    def __init__(self, url: str) -> None:
        options = {"check_same_thread": False} if url.startswith("sqlite") else {}
        self.engine = create_engine(url, pool_pre_ping=True, connect_args=options)
        if url.startswith("sqlite"):
            event.listen(self.engine, "connect", self._sqlite_foreign_keys)
        self.sessions = sessionmaker(self.engine, expire_on_commit=False)

    @staticmethod
    def _sqlite_foreign_keys(connection, record) -> None:
        connection.execute("PRAGMA foreign_keys=ON")

    def ready(self) -> bool:
        with self.engine.connect() as connection:
            connection.execute(text("SELECT 1"))
            return True
