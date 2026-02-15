# Backward-compat shim — combines generic + Shopify config.
# Module-level variables are resolved dynamically via __getattr__.
import src.shared.config.configs as _generic
import src.ecommerce.config.shopify_config as _shopify

from src.shared.config.configs import *  # noqa: F401,F403
from src.ecommerce.config.shopify_config import *  # noqa: F401,F403


def __getattr__(name):
    # Check generic first, then Shopify-specific
    try:
        return getattr(_generic, name)
    except AttributeError:
        return getattr(_shopify, name)
