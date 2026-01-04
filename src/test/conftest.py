import os


def pytest_configure():
    """
    Ensure backend tests do not depend on a local Postgres instance.
    Many IDE test runners invoke `pytest` without custom env vars, which would
    otherwise fall back to DATABASE_URL=postgresql://... and fail with
    connection refused.
    """
    os.environ.setdefault("DATABASE_URL", "sqlite:///./test.db")


