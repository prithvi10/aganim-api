import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from src.shared.db.database import get_db, Base

# Use in-memory SQLite for testing
TEST_DATABASE_URL = "sqlite:///:memory:"

@pytest.fixture
def test_engine():
    engine = create_engine(TEST_DATABASE_URL, connect_args={"check_same_thread": False})
    Base.metadata.create_all(bind=engine)
    yield engine
    Base.metadata.drop_all(bind=engine)
    engine.dispose()

@pytest.fixture
def test_db(test_engine):
    TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=test_engine)
    db = TestingSessionLocal()
    try:
        yield db
    finally:
        db.close()

def test_database_connection(test_db):
    """Test that we can connect to the database and execute a query."""
    result = test_db.execute(text("SELECT 1"))
    assert result.scalar() == 1

def test_get_db_dependency():
    """Test the get_db generator dependency."""
    gen = get_db()
    db = next(gen)
    assert db is not None
    # Just verify it has a close method, actual connection test is above
    assert hasattr(db, "close")
    
    # Cleanup
    try:
        next(gen)
    except StopIteration:
        pass

