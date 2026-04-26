import yaml
from pathlib import Path
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker, Session
from models import Base

_engine = None
_SessionFactory = None


def _load_config() -> dict:
    config_path = Path(__file__).parent / "config.yaml"
    with open(config_path) as f:
        return yaml.safe_load(f)


def get_engine():
    global _engine
    if _engine is None:
        config = _load_config()
        url = config["database"]["url"]
        _engine = create_engine(url, pool_pre_ping=True, pool_recycle=3600)
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
