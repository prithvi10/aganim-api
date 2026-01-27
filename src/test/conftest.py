import os

# Ensure tests have deterministic defaults for required env vars before imports.
os.environ.setdefault("DATABASE_URL", "sqlite:///./test.db")
os.environ.setdefault("SHOPIFY_API_KEY", "test-shopify-key")
os.environ.setdefault("SHOPIFY_API_SECRET", "test-shopify-secret")
os.environ.setdefault("OPENAI_API_KEY", "test-openai-key")


def pytest_configure():
    """
    Keep to preserve existing pytest hook usage (env defaults are set above).
    """
    return None


