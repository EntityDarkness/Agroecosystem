"""SQLite storage, versioned schema and request-scoped SQLAlchemy sessions."""
import os
import threading
from pathlib import Path

from sqlalchemy import create_engine, event, text
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from service.config import DATA_DIR


class Base(DeclarativeBase):
    pass


DATABASE_URL = os.environ.get("DATABASE_URL", f"sqlite:///{(DATA_DIR / 'agroecosystem.sqlite3').as_posix()}")
engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False, "timeout": 30} if DATABASE_URL.startswith("sqlite") else {})
SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)
initialized = False
init_lock = threading.Lock()


if engine.dialect.name == "sqlite":
    @event.listens_for(engine, "connect")
    def configure_sqlite(connection, _):
        connection.execute("PRAGMA foreign_keys=ON")
        # SQLite lower() only handles ASCII; this function also supports Russian.
        connection.create_function("casefold", 1, lambda value: str(value or "").casefold(), deterministic=True)


def init_database():
    global initialized
    with init_lock:
        if initialized:
            return
        from service import models  # noqa: F401
        from service.catalog_service import seed_catalog
        if engine.url.database and engine.dialect.name == "sqlite":
            Path(engine.url.database).parent.mkdir(parents=True, exist_ok=True)
        with engine.begin() as connection:
            connection.execute(text("CREATE TABLE IF NOT EXISTS schema_migrations (version INTEGER PRIMARY KEY)"))
            applied = set(connection.execute(text("SELECT version FROM schema_migrations")).scalars())
            if 1 not in applied:
                Base.metadata.create_all(connection)
                connection.execute(text("INSERT INTO schema_migrations(version) VALUES (1)"))
            if 2 not in applied:
                for index in models.QUERY_INDEXES:
                    index.create(connection, checkfirst=True)
                connection.execute(text("INSERT INTO schema_migrations(version) VALUES (2)"))
        with SessionLocal.begin() as session:
            seed_catalog(session)
            from service.catalog_service import seed_model_data
            seed_model_data(session)
        initialized = True


def get_db():
    init_database()
    with SessionLocal() as session:
        yield session
