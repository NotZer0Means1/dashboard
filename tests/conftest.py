import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.config import get_settings
from app.database import Base
from app.image_storage import get_image_storage
from app.storage import get_storage


@pytest.fixture(scope="session", autouse=True)
def dummy_aws_credentials():
    """Pin fake credentials for the whole session. Without this, boto3 falls back
    to the developer's real profile chain - which makes the suite depend on local
    AWS config and, worse, lets a mistake reach a real bucket."""
    import os

    os.environ.setdefault("AWS_ACCESS_KEY_ID", "testing")
    os.environ.setdefault("AWS_SECRET_ACCESS_KEY", "testing")
    os.environ.setdefault("AWS_SESSION_TOKEN", "testing")
    os.environ.setdefault("AWS_DEFAULT_REGION", "eu-central-1")


@pytest.fixture(autouse=True)
def reset_caches():
    """Settings and the storage factories are lru_cached, so a test that changes
    an env var would otherwise leak into every later test. Clearing on both sides
    of the yield means a failing test can't poison the ones after it."""
    for cached in (get_settings, get_storage, get_image_storage):
        cached.cache_clear()
    yield
    for cached in (get_settings, get_storage, get_image_storage):
        cached.cache_clear()


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()
