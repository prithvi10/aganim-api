"""
Ecommerce configuration re-export.

Re-exports everything from:
- ``src.shared.config.configs``  (generic AI / rate-limit settings)
- ``src.ecommerce.config.shopify_config``  (Shopify-specific settings)

so that ``from src.ecommerce.config.configs import X`` works for any config
variable, regardless of where it's canonically defined.
"""

from src.shared.config.configs import *          # noqa: F401,F403
from src.ecommerce.config.shopify_config import *  # noqa: F401,F403
