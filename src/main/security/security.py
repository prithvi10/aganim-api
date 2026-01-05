import os
import jwt  # pip install pyjwt
import hashlib
import hmac
import base64
from fastapi import Header, HTTPException, Request, Depends, Query
from dotenv import load_dotenv
from src.main.logging.logger import get_logger
from urllib.parse import urlencode

logger = get_logger(__name__)

# Load environment variables
load_dotenv()

# Configuration
SHOPIFY_API_SECRET = os.getenv("SHOPIFY_API_SECRET")
SHOPIFY_API_KEY = os.getenv("SHOPIFY_API_KEY")

# ---------------------------------------------------------
# 1. API Key Logic (For Billing/Quota Checks)
# ---------------------------------------------------------
def hash_api_key(api_key: str) -> str:
    """
    Hashes the API key using SHA-256.
    """
    return hashlib.sha256(api_key.encode()).hexdigest()

def get_api_key_hash(authorization: str = Header(...)):
    """
    Extracts the Bearer token (API Key) and returns its hash.
    This is used for the generation endpoint to check usage quota.
    """
    if not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Invalid authorization header format")
    
    token = authorization.split(" ")[1]
    return hash_api_key(token)

# ---------------------------------------------------------
# 2. Shopify JWT Logic (For App Identity/Setup)
# ---------------------------------------------------------
def verify_shopify_session(authorization: str = Header(...)):
    """
    Dependency to verify the Shopify Session Token (JWT).
    Usage: async def endpoint(shop: str = Depends(verify_shopify_session))
    
    Used for administrative requests, app setup, webhooks, etc.
    
    Returns:
        str: The shop domain (e.g., 'my-store.myshopify.com') if valid.
    """
    # 1. Sanity Check: Ensure secrets exist
    if not SHOPIFY_API_SECRET or not SHOPIFY_API_KEY:
        raise HTTPException(
            status_code=500, 
            detail="Server Misconfiguration: Missing Shopify API Credentials"
        )

    # 2. Parse the Header
    if not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Invalid authorization header format")
    
    token = authorization.split(" ")[1]

    # DEV BYPASS: Allow a specific magic token for local testing
    if token == "dev-token-123":
        return "dev-shop.myshopify.com"

    try:
        # 3. Decode & Verify the JWT
        # - We use the 'HS256' algorithm (standard for Shopify).
        # - We verify the signature using your App Secret.
        # - We verify the 'audience' matches your specific App API Key.
        payload = jwt.decode(
            token, 
            SHOPIFY_API_SECRET, 
            algorithms=["HS256"], 
            audience=SHOPIFY_API_KEY
        )

        # 4. Extract the Shop Domain
        dest = payload.get("dest")
        if not dest:
            raise HTTPException(status_code=401, detail="Invalid token payload: missing 'dest'")

        # Clean the URL to just the domain
        shop_domain = dest.replace("https://", "").replace("http://", "")
        
        return shop_domain

    except HTTPException:
        raise
    except jwt.ExpiredSignatureError:
        logger.warning("Token has expired")
        raise HTTPException(status_code=401, detail="Token has expired. Please refresh the page.")
    except jwt.InvalidTokenError as e:
        logger.warning(f"⚠️ Security Alert: Invalid Token Attempt: {e}")
        raise HTTPException(status_code=401, detail="Invalid Shopify Token")
    except Exception as e:
        logger.error(f"⚠️ Unknown Security Error: {e}")
        raise HTTPException(status_code=500, detail="Internal Authentication Error")

# ---------------------------------------------------------
# 3. Shopify Webhook Verification
# ---------------------------------------------------------
async def verify_webhook_signature(request: Request):
    """
    Verifies that the incoming webhook request is from Shopify.
    """
    if not SHOPIFY_API_SECRET:
        logger.error("Missing SHOPIFY_API_SECRET")
        raise HTTPException(status_code=500, detail="Server Configuration Error")

    debug_webhook = os.getenv("DEBUG_WEBHOOK_SIGNATURE") == "1"
    hmac_header = request.headers.get("X-Shopify-Hmac-Sha256")
    if not hmac_header:
        logger.warning("Missing X-Shopify-Hmac-Sha256 header")
        raise HTTPException(status_code=401, detail="Unauthorized")

    body = await request.body()
    
    # Calculate HMAC
    digest = hmac.new(
        SHOPIFY_API_SECRET.encode('utf-8'),
        body,
        hashlib.sha256
    ).digest()
    
    computed_hmac = base64.b64encode(digest).decode('utf-8')

    if not hmac.compare_digest(computed_hmac, hmac_header):
        if debug_webhook:
            logger.info(
                "[WebhookSigDebug] "
                f"received={hmac_header} computed={computed_hmac} "
                f"body_len={len(body)} content_type={request.headers.get('content-type')}"
            )
        logger.warning("Invalid webhook signature")
        raise HTTPException(status_code=401, detail="Unauthorized")
    
    return True

# ---------------------------------------------------------
# 4. Shopify OAuth Redirect Verification
# ---------------------------------------------------------
def verify_shopify_redirect(query_params: dict):
    """
    Verifies the HMAC signature for Shopify OAuth redirects.
    """
    if not SHOPIFY_API_SECRET:
        raise HTTPException(status_code=500, detail="Server Configuration Error: Missing Secret")

    received_hmac = query_params.get("hmac")
    if not received_hmac:
        raise HTTPException(status_code=400, detail="Missing HMAC parameter")

    # Remove hmac from params
    params_copy = query_params.copy()
    del params_copy["hmac"]
    
    # Sort and encode
    # Note: query_params might contain list values in some frameworks, but FastAPI's Request.query_params
    # is usually flat or we handle it as such. Shopify sends standard scalar params for OAuth.
    sorted_params = urlencode(sorted(params_copy.items()))
    
    # Calculate HMAC
    digest = hmac.new(
        SHOPIFY_API_SECRET.encode('utf-8'),
        sorted_params.encode('utf-8'),
        hashlib.sha256
    ).hexdigest()

    if not hmac.compare_digest(digest, received_hmac):
        logger.warning("Invalid OAuth redirect signature")
        raise HTTPException(status_code=400, detail="Invalid HMAC signature")
    
    return True

# ---------------------------------------------------------
# 5. Shopify App Proxy Verification
# ---------------------------------------------------------
async def verify_shopify_proxy_request(request: Request):
    """
    Verifies the signature for Shopify App Proxy requests.
    This function should be used as a FastAPI Dependency.
    """
    debug_proxy = os.getenv("DEBUG_PROXY_SIGNATURE") == "1"

    def _dbg(msg: str):
        if debug_proxy:
            logger.info(f"[ProxySigDebug] {msg}")

    _dbg(f"request.url={getattr(request, 'url', None)}")

    # 1. Access the query parameters
    query_params = dict(request.query_params)
    _dbg(f"query_params={query_params}")

    if not SHOPIFY_API_SECRET:
         raise HTTPException(status_code=500, detail="Server Configuration Error: Missing Secret")

    # 2. Extract and remove signature
    received_signature = query_params.get("signature")
    if not received_signature:
        raise HTTPException(status_code=400, detail="Missing signature parameter")
    _dbg(f"received_signature={received_signature}")

    params_for_hmac = query_params.copy()
    if "signature" in params_for_hmac:
        del params_for_hmac["signature"]
        
    # Shopify also removes 'action' and 'controller' parameters if present, 
    # but they are usually not present in the final proxy query string.
    # We rely on the core six: shop, path_prefix, timestamp, etc.

    # 3. Construct the canonical query string.
    #
    # Shopify App Proxy signatures are HMAC-SHA256 over the query string parameters
    # excluding `signature`. In practice, we may observe differences between:
    # - raw (percent-encoded) vs decoded values
    # - sorted vs original parameter order
    #
    # Shopify App Proxy signatures are computed by:
    # - removing `signature`
    # - sorting parameters lexicographically (by key, then value)
    # - concatenating as `k=v` pairs *with no separators*
    #
    # Shopify behavior can still vary in whether values are signed raw (percent-encoded)
    # or decoded + re-encoded. To avoid brittle failures, we verify against a small set
    # of equivalent canonicalization variants (all still require a valid HMAC under the secret).
    def _hmac_hex(message: str) -> str:
        return hmac.new(
            SHOPIFY_API_SECRET.encode("utf-8"),
            message.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()

    raw_qs = None
    try:
        raw_qs = request.scope.get("query_string")  # type: ignore[union-attr]
    except Exception:
        raw_qs = None

    raw_items: list[tuple[str, str]] = []
    if raw_qs:
        qs_str = raw_qs.decode("utf-8")
        _dbg(f"raw_query_string={qs_str}")
        for part in qs_str.split("&"):
            if not part:
                continue
            if "=" in part:
                k, v = part.split("=", 1)
            else:
                k, v = part, ""
            if k == "signature":
                continue
            raw_items.append((k, v))
        _dbg(f"raw_items_no_signature={raw_items}")
    else:
        _dbg("raw_query_string=<missing>")

    # Decoded fallback (also used by tests/mocks without `scope.query_string`)
    qp = request.query_params
    if hasattr(qp, "multi_items"):
        decoded_items = list(qp.multi_items())  # type: ignore[attr-defined]
    else:
        decoded_items = list(dict(qp).items())
    decoded_items = [(k, v) for (k, v) in decoded_items if k != "signature"]
    _dbg(f"decoded_items_no_signature={decoded_items}")

    candidates: list[str] = []
    if raw_items:
        # Variant A: raw values, sorted by key then value, concatenated with NO separators
        cand_a = "".join([f"{k}={v}" for (k, v) in sorted(raw_items, key=lambda kv: (kv[0], kv[1]))])
        candidates.append(cand_a)
        _dbg(f"cand[A]=raw_sorted: {cand_a}")
        # Variant B: raw values, original order, concatenated with NO separators
        cand_b = "".join([f"{k}={v}" for (k, v) in raw_items])
        candidates.append(cand_b)
        _dbg(f"cand[B]=raw_original_order: {cand_b}")
    # Variant C: decoded values, sorted by key then value, concatenated with NO separators
    cand_c = "".join([f"{k}={v}" for (k, v) in sorted(decoded_items, key=lambda kv: (kv[0], kv[1]))])
    candidates.append(cand_c)
    _dbg(f"cand[C]=decoded_sorted: {cand_c}")
    # Variant D: re-encode sorted decoded params via urlencode (adds '&'), then remove '&'
    # This re-encodes characters like "/" -> "%2F", which Shopify commonly signs.
    cand_d = urlencode(sorted(decoded_items, key=lambda kv: (kv[0], kv[1]))).replace("&", "")
    candidates.append(cand_d)
    _dbg(f"cand[D]=urlencode(decoded_sorted): {cand_d}")

    digests = [_hmac_hex(c) for c in candidates]
    for i, (c, d) in enumerate(zip(candidates, digests)):
        _dbg(f"digest[{i}]={d} for cand[{i}]={c}")
    ok = any(hmac.compare_digest(d, received_signature) for d in digests)
    if not ok:
        # Debugging without leaking secrets:
        # - safe to log the candidate strings (they're derived from request query params)
        # - safe to log calculated digests (request already contains the received signature)
        preview = candidates[0][:250] if candidates else ""
        msg = (
            f"Invalid App Proxy signature. Received: {received_signature}. "
            f"CandidatePreview: {preview}"
        )
        if debug_proxy:
            try:
                raw_present = bool(raw_qs)
                msg += f" | raw_qs_present={raw_present}"
                for i, (c, d) in enumerate(zip(candidates, digests)):
                    msg += f" | cand[{i}]={c} | digest[{i}]={d}"
            except Exception:
                pass
        logger.warning(msg)
        raise HTTPException(status_code=401, detail="Invalid signature")

    _dbg("signature_match=TRUE")
    # 6. Success: return the shop domain for use in the controller
    _dbg(f"shop_returned={query_params.get('shop')}")
    return query_params.get("shop")
