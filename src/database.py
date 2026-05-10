from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker, Session

from config import load_config
from models import Base

_url: str | None = None
_engine = None
_SessionFactory = None


def configure(url: str):
    """Override the database URL for tests. Resets cached engine and session factory."""
    global _url, _engine, _SessionFactory
    _url = url
    _engine = None
    _SessionFactory = None


def get_engine():
    global _engine
    if _engine is None:
        url = _url or load_config()["database"]["url"]
        _engine = create_engine(url, pool_pre_ping=True, pool_recycle=3600, pool_size=8, max_overflow=4)
    return _engine


def get_session_factory() -> sessionmaker:
    global _SessionFactory
    if _SessionFactory is None:
        _SessionFactory = sessionmaker(bind=get_engine(), expire_on_commit=False)
    return _SessionFactory


def get_session() -> Session:
    factory = get_session_factory()
    return factory()


def init_db():
    engine = get_engine()
    Base.metadata.create_all(engine)
    with engine.connect() as conn:
        conn.execute(text("SELECT 1"))
    print("Database initialized.")
