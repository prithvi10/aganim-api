from __future__ import annotations

import os
import httpx


def _env_true(name: str) -> bool:
    return str(os.getenv(name, "") or "").strip().lower() in ("1", "true", "yes", "y", "on")


def ssl_verify_for(*, insecure_env_vars: tuple[str, ...]) -> bool | object:
    """
    Returns an `httpx` `verify=` value:
    - False if any env var in insecure_env_vars is truthy (local dev only).
    - Else truststore SSLContext if available (corporate SSL interception friendly).
    - Else True (default CA bundle verification).
    """
    if any(_env_true(k) for k in insecure_env_vars):
        return False
    try:
        import truststore  # type: ignore

        return truststore.SSLContext(httpx.create_ssl_context().protocol)
    except Exception:
        return True


def ssl_verify_shopify() -> bool | object:
    return ssl_verify_for(insecure_env_vars=("SHOPIFY_INSECURE_SSL",))


def ssl_verify_serp() -> bool | object:
    # If Shopify insecure SSL is enabled for local dev, we also allow SerpAPI calls through.
    return ssl_verify_for(insecure_env_vars=("SERP_INSECURE_SSL", "SHOPIFY_INSECURE_SSL"))
