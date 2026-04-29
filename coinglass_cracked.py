"""
coinglass_cracked.py  —  CoinGlass Heatmap Scraper (fully decoded)
====================================================================
Decryption algorithm reverse-engineered from _app-71f6b040bd9900dd.js

ALGORITHM SUMMARY
─────────────────
Request:
  data_param = AES_ECB_PKCS7_encrypt(f"{unix_ts},{TOTP}", MASTER_KEY)
  cache_ts_v2 = str(int(time.time() * 1000))   ← millisecond timestamp
  obe = <session token from DevTools — only manual thing needed>

Response decryption (interceptor switch order: 1→4→2→3→0→6→5):
  case 1:  a  = ie(request_url)               → "/api/index/v2/liqHeatMap"
  case 4:  s  = Xt(response, a)               → btoa(cache_ts_v2)   [when v=0]
  case 2:  s  = s[:16]
  case 3:  s  = re(response.headers.user, s)  → AES→Hex→inflate→str
  case 0:  o  = re(response.data.data, s)     → same, gives JSON string
  case 6:  data = JSON.parse(o)

re(ciphertext_b64, key_str):
  raw   = AES_ECB_PKCS7_decrypt(ciphertext_b64, key_str[:16])
  hex_s = raw.hex()
  bytes = bytes.fromhex(hex_s)          # = raw (same thing)
  inf   = zlib_inflate(bytes)            # Gt.ZP.inflate in JS
  s     = fromCharCode(inf)              # UTF-8 decode
  return s.strip('"')

DEPENDENCIES
────────────
  pip install requests pycryptodome pyotp

MANUAL STEP (once every few days)
──────────────────────────────────
  DevTools → Network → liqHeatMap request → copy 'obe' header value
"""

import base64
import json
import logging
import random
import time
import zlib
from datetime import datetime, timezone
from pathlib import Path

import pyotp
import requests
from Crypto.Cipher import AES
from Crypto.Util.Padding import pad, unpad

# ── Logging ────────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger(__name__)

# ── Constants from JS source (stable until CoinGlass redeploys) ───────────────
_TOTP_SECRET  = "I65VU7K5ZQL7WB4E"
_MASTER_KEY   = "1f68efd73f8d4921acc0dead41dd39bc"
_BASE_URL     = "https://capi.coinglass.com"

# ── Your session token (only thing that needs manual refresh) ─────────────────
OBE = "s_8bb44c18ba9d4dc78081d4e5bf1068c6"   # e.g. "s_3394cdaa6172457cbc313517ff4db0e2"

OUTPUT_DIR = Path("output")
OUTPUT_DIR.mkdir(exist_ok=True)


# ── Global Rate Limiter ────────────────────────────────────────────────────────
class RateLimiter:
    """Enforces minimum interval between API calls to different endpoints."""
    def __init__(self, min_interval_seconds: float = 6.0):
        self.min_interval = min_interval_seconds
        self.last_request_time = 0.0

    def wait(self):
        """Block until min_interval has passed since last call."""
        elapsed = time.time() - self.last_request_time
        if elapsed < self.min_interval:
            sleep_time = self.min_interval - elapsed
            log.debug(f"Rate limiter: sleeping {sleep_time:.1f}s")
            time.sleep(sleep_time)
        self.last_request_time = time.time()

global_limiter = RateLimiter(min_interval_seconds=6.0)


# ══════════════════════════════════════════════════════════════════════════════
#  CRYPTO PRIMITIVES  (matching JS CryptoJS + pako exactly)
# ══════════════════════════════════════════════════════════════════════════════

def _aes_ecb_encrypt(plaintext: str, key: str) -> str:
    """AES-ECB-PKCS7 encrypt. Returns base64 string."""
    k = key.encode("utf-8")
    c = AES.new(k, AES.MODE_ECB)
    return base64.b64encode(c.encrypt(pad(plaintext.encode(), 16))).decode()


def _aes_ecb_decrypt_raw(ciphertext_b64: str, key_str: str) -> bytes:
    """
    AES-ECB-PKCS7 decrypt.
    Matches: CryptoJS.AES.decrypt(ct, enc.Utf8.parse(key), {ECB, PKCS7})
    Returns raw plaintext bytes (PKCS7-unpadded).
    """
    k   = key_str.encode("utf-8")[:16]   # enc.Utf8.parse → bytes, AES-128
    raw = base64.b64decode(ciphertext_b64)
    c   = AES.new(k, AES.MODE_ECB)
    dec = c.decrypt(raw)
    try:
        dec = unpad(dec, 16)
    except Exception:
        pass
    return dec


def _inflate(data: bytes) -> bytes:
    """
    Zlib inflate — matches Gt.ZP.inflate() in JS (pako library).
    Tries zlib format first, then raw deflate.
    """
    for wbits in [15, -15, 47]:
        try:
            return zlib.decompress(data, wbits)
        except Exception:
            continue
    raise ValueError(f"Could not inflate {len(data)} bytes")


def _from_char_code(data: bytes) -> str:
    """
    Matches JS: String.fromCharCode.apply(null, inflated) + decodeURIComponent(escape(s))
    Essentially: interpret raw bytes as Latin-1, then URI-decode to UTF-8.
    """
    # JS's escape() + decodeURIComponent() on raw bytes = UTF-8 decode
    return data.decode("utf-8", errors="replace")


def re_fn(ciphertext_b64: str, key_str: str, retries: int = 2) -> str | None:
    """
    Replicates the JS re(t, e) function with retry logic for transient failures.
      1. AES-ECB-PKCS7 decrypt
      2. .toString(enc.Hex)  →  hex string
      3. ne(): hex → bytes → inflate → fromCharCode → decodeURIComponent
      4. strip leading/trailing quotes

    Retries on transient errors (zlib decompression failures).
    """
    for attempt in range(1, retries + 1):
        try:
            raw_bytes = _aes_ecb_decrypt_raw(ciphertext_b64, key_str)
            inflated  = _inflate(raw_bytes)
            result    = _from_char_code(inflated)
            return result.strip('"').strip("'")
        except ValueError as e:
            if attempt < retries:
                log.debug(f"re_fn transient error (attempt {attempt}/{retries}): {e}")
                time.sleep(0.5 * attempt)
                continue
            log.error(f"re_fn failed after {retries} retries: {e}")
            return None
        except Exception as e:
            log.error(f"re_fn permanent error: {e}")
            return None
    return None


# ══════════════════════════════════════════════════════════════════════════════
#  REQUEST GENERATION
# ══════════════════════════════════════════════════════════════════════════════

def _generate_data_param() -> str:
    """
    Replicates JS function a():
      t    = unix timestamp (seconds)
      code = TOTP(secret, t, step=30)
      payload = f"{t},{code}"
      return AES_ECB_encrypt(payload, MASTER_KEY)
    """
    t    = int(time.time())
    code = pyotp.TOTP(_TOTP_SECRET, interval=30).now()
    return _aes_ecb_encrypt(f"{t},{code}", _MASTER_KEY)


def _build_headers(cache_ts_v2: str) -> dict:
    return {
        "User-Agent":     "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Accept":         "application/json",
        "Accept-Language":"en-US,en;q=0.9",
        "Accept-Encoding":"gzip, deflate, br",
        "Origin":         "https://www.coinglass.com",
        "Referer":        "https://www.coinglass.com/",
        "Sec-Fetch-Dest": "empty",
        "Sec-Fetch-Mode": "cors",
        "Sec-Fetch-Site": "same-site",
        "cache-ts-v2":    cache_ts_v2,   # ← KEY: used in decryption derivation
        "encryption":     "true",
        "language":       "en",
        "obe":            OBE,
    }


# ══════════════════════════════════════════════════════════════════════════════
#  RESPONSE DECRYPTION  (interceptor switch order: 1→4→2→3→0→6→5)
# ══════════════════════════════════════════════════════════════════════════════

def decrypt_response(
    encrypted_data: str,
    user_header:    str,
    cache_ts_v2:    str,
    v_header:       str = "0",
    endpoint:       str = "",
) -> dict | None:
    """
    Full response decryption pipeline:

    v=0: case 4: s = btoa(cache_ts_v2)
    v=1: case 4: s = btoa(api_endpoint_path)

    case 2: s = s[:16]
    case 3: s = re(user_header, s)   → zlib-inflated intermediate key
    case 0: o = re(encrypted_data, s) → zlib-inflated JSON string
    case 6: return JSON.parse(o)
    """
    # Case 4: Xt(response, a) — different seed depending on v_header
    if v_header == "1":
        s = base64.b64encode(endpoint.encode()).decode()
    else:
        s = base64.b64encode(cache_ts_v2.encode()).decode()

    # Case 2: s = s.substring(0, 16)
    s = s[:16]

    log.debug(f"  intermediate key seed: {repr(s)}")

    # Case 3: s = re(user_header, s)
    intermediate = re_fn(user_header, s)
    if intermediate is None:
        log.error("  Case 3 failed: could not decrypt user_header")
        return None

    log.debug(f"  intermediate key: {repr(intermediate[:20])}")

    # Case 0: o = re(encrypted_data, s)  where s is now the intermediate
    # Note: re() uses key_str[:16] internally
    final_key = intermediate[:16]
    plaintext = re_fn(encrypted_data, final_key)

    if plaintext is None:
        log.error("  Case 0 failed: could not decrypt response data")
        return None

    # Case 6: JSON.parse(o)
    try:
        return json.loads(plaintext)
    except json.JSONDecodeError as e:
        log.error(f"  JSON parse failed: {e}")
        log.error(f"  Plaintext preview: {repr(plaintext[:100])}")
        return None


# ══════════════════════════════════════════════════════════════════════════════
#  CORE FETCH
# ══════════════════════════════════════════════════════════════════════════════

def fetch_heatmap(
    symbol:   str = "Binance_BTCUSDT",
    interval: int = 5,
    limit:    int = 288,
    retries:  int = 3,
) -> dict | None:
    """
    Fetch and decrypt the liquidation heatmap.

    Interval × Limit reference:
      interval=5,    limit=288  → 24h  (5min candles)
      interval=15,   limit=288  → 3d
      interval=60,   limit=168  → 7d
      interval=240,  limit=90   → 15d
      interval=1440, limit=30   → 30d
    """
    for attempt in range(1, retries + 1):
        try:
            data_param   = _generate_data_param()
            cache_ts_v2  = str(int(time.time() * 1000))  # ← record NOW, used in decryption
            headers      = _build_headers(cache_ts_v2)
            params       = {
                "merge":    "true",
                "symbol":   symbol,
                "interval": interval,
                "limit":    limit,
                "data":     data_param,
            }

            log.info(f"[Attempt {attempt}] {symbol} | {interval}min × {limit}")

            r = requests.get(
                _BASE_URL + "/api/index/v2/liqHeatMap",
                headers=headers,
                params=params,
                timeout=20,
            )

            log.info(f"  Status: {r.status_code} | v={r.headers.get('v','?')} | enc={r.headers.get('encryption','?')}")

            if r.status_code == 401:
                log.error("❌ 401 — obe token expired. Recapture from DevTools.")
                return None
            if r.status_code == 403:
                log.error("❌ 403 Forbidden.")
                return None
            if r.status_code == 429:
                wait_time = 30 * (2 ** (attempt - 1)) + random.uniform(0, 10)
                log.warning(f"⚠️  Rate limited. Waiting {wait_time:.1f}s...")
                time.sleep(wait_time)
                continue

            r.raise_for_status()

            body = r.json()
            is_encrypted = r.headers.get("encryption", "").lower() == "true"
            user_header  = r.headers.get("user", "")
            v_header     = r.headers.get("v", "0")

            if not is_encrypted:
                log.info("  Response is unencrypted.")
                return body

            encrypted_data = body.get("data", "")
            if not isinstance(encrypted_data, str):
                log.info("  data field is not a string — already decrypted.")
                return body

            log.info("  Decrypting...")
            result = decrypt_response(
                encrypted_data, user_header, cache_ts_v2, v_header,
                endpoint="/api/index/v2/liqHeatMap"
            )

            if result:
                log.info("  ✅ Decrypted successfully.")
                return {"code": body.get("code"), "msg": body.get("msg"), "data": result}

            # Save debug info if decryption fails
            ts = int(time.time())
            debug_path = OUTPUT_DIR / f"debug_raw_{ts}.json"
            with open(debug_path, "w") as f:
                json.dump({
                    "raw_wrapper": body,
                    "user_header": user_header,
                    "v_header":    v_header,
                    "data_param":  data_param,
                    "cache_ts_v2": cache_ts_v2,    # ← now saved for debugging
                }, f, indent=2)
            log.error(f"  Decryption failed. Debug saved → {debug_path}")
            return None

        except requests.exceptions.RequestException as e:
            log.error(f"  Request error: {e}")
            time.sleep(attempt * 3)

    return None


def _handle_response(r, cache_ts_v2, endpoint):
    r.raise_for_status()
    body        = r.json()
    user_header = r.headers.get("user", "")
    v_header    = r.headers.get("v", "0")
    is_enc      = r.headers.get("encryption", "").lower() == "true"

    if not is_enc or not isinstance(body.get("data"), str):
        return body

    return decrypt_response(body["data"], user_header, cache_ts_v2, v_header, endpoint)


def fetch_oi_expiry(symbol="BTC", ex="Deribit", type="Delivery", subtype="ALL", currency="USD", retries=3):
    endpoint = "/api/option/v2/chart"
    for attempt in range(1, retries + 1):
        try:
            cache_ts_v2 = str(int(time.time() * 1000))
            headers = _build_headers(cache_ts_v2)
            params = {"symbol": symbol, "ex": ex, "type": type, "subtype": subtype, "currency": currency}

            log.info(f"[Attempt {attempt}] {endpoint} | {symbol} {type}")

            r = requests.get(_BASE_URL + endpoint, headers=headers, params=params, timeout=20)
            log.info(f"  Status: {r.status_code} | v={r.headers.get('v','?')} | enc={r.headers.get('encryption','?')}")

            if r.status_code == 401:
                log.error("❌ 401 — obe token expired. Recapture from DevTools.")
                return None
            if r.status_code == 403:
                log.error("❌ 403 Forbidden.")
                return None
            if r.status_code == 429:
                wait_time = 30 * (2 ** (attempt - 1)) + random.uniform(0, 10)
                log.warning(f"⚠️  Rate limited. Waiting {wait_time:.1f}s...")
                time.sleep(wait_time)
                continue

            r.raise_for_status()
            result = _handle_response(r, cache_ts_v2, endpoint)
            if result:
                log.info("  ✅ Decrypted successfully.")
                return result
            log.error("  Decryption failed.")
            return None

        except requests.exceptions.RequestException as e:
            log.error(f"  Request error: {e}")
            time.sleep(attempt * 3)

    return None


def fetch_options_oi(symbol="BTC", timeType=0, currency="USD", retries=3):
    endpoint = "/api/option/oi/history"
    for attempt in range(1, retries + 1):
        try:
            cache_ts_v2 = str(int(time.time() * 1000))
            headers = _build_headers(cache_ts_v2)
            params = {"symbol": symbol, "timeType": timeType, "currency": currency}

            log.info(f"[Attempt {attempt}] {endpoint} | {symbol} timeType={timeType}")

            r = requests.get(_BASE_URL + endpoint, headers=headers, params=params, timeout=20)
            log.info(f"  Status: {r.status_code} | v={r.headers.get('v','?')} | enc={r.headers.get('encryption','?')}")

            if r.status_code == 401:
                log.error("❌ 401 — obe token expired. Recapture from DevTools.")
                return None
            if r.status_code == 403:
                log.error("❌ 403 Forbidden.")
                return None
            if r.status_code == 429:
                wait_time = 30 * (2 ** (attempt - 1)) + random.uniform(0, 10)
                log.warning(f"⚠️  Rate limited. Waiting {wait_time:.1f}s...")
                time.sleep(wait_time)
                continue

            r.raise_for_status()
            result = _handle_response(r, cache_ts_v2, endpoint)
            if result:
                log.info("  ✅ Decrypted successfully.")
                return result
            log.error("  Decryption failed.")
            return None

        except requests.exceptions.RequestException as e:
            log.error(f"  Request error: {e}")
            time.sleep(attempt * 3)

    return None


def fetch_options_vs_futures(retries=3):
    endpoint = "/api/index/optionVsFuturesByOi"
    for attempt in range(1, retries + 1):
        try:
            cache_ts_v2 = str(int(time.time() * 1000))
            headers = _build_headers(cache_ts_v2)

            log.info(f"[Attempt {attempt}] {endpoint}")

            r = requests.get(_BASE_URL + endpoint, headers=headers, timeout=20)
            log.info(f"  Status: {r.status_code} | v={r.headers.get('v','?')} | enc={r.headers.get('encryption','?')}")

            if r.status_code == 401:
                log.error("❌ 401 — obe token expired. Recapture from DevTools.")
                return None
            if r.status_code == 403:
                log.error("❌ 403 Forbidden.")
                return None
            if r.status_code == 429:
                wait_time = 30 * (2 ** (attempt - 1)) + random.uniform(0, 10)
                log.warning(f"⚠️  Rate limited. Waiting {wait_time:.1f}s...")
                time.sleep(wait_time)
                continue

            r.raise_for_status()
            result = _handle_response(r, cache_ts_v2, endpoint)
            if result:
                log.info("  ✅ Decrypted successfully.")
                return result
            log.error("  Decryption failed.")
            return None

        except requests.exceptions.RequestException as e:
            log.error(f"  Request error: {e}")
            time.sleep(attempt * 3)

    return None


def fetch_options_greeks(symbol="BTC", ex="Deribit", time_param="", retries=3):
    endpoint = "/api/option/index/chart"
    for attempt in range(1, retries + 1):
        try:
            cache_ts_v2 = str(int(time.time() * 1000))
            headers = _build_headers(cache_ts_v2)
            params = {"symbol": symbol, "ex": ex, "time": time_param}

            log.info(f"[Attempt {attempt}] {endpoint} | {symbol} {ex}")

            r = requests.get(_BASE_URL + endpoint, headers=headers, params=params, timeout=20)
            log.info(f"  Status: {r.status_code} | v={r.headers.get('v','?')} | enc={r.headers.get('encryption','?')}")

            if r.status_code == 401:
                log.error("❌ 401 — obe token expired. Recapture from DevTools.")
                return None
            if r.status_code == 403:
                log.error("❌ 403 Forbidden.")
                return None
            if r.status_code == 429:
                wait_time = 30 * (2 ** (attempt - 1)) + random.uniform(0, 10)
                log.warning(f"⚠️  Rate limited. Waiting {wait_time:.1f}s...")
                time.sleep(wait_time)
                continue

            r.raise_for_status()
            result = _handle_response(r, cache_ts_v2, endpoint)
            if result:
                log.info("  ✅ Decrypted successfully.")
                return result
            log.error("  Decryption failed.")
            return None

        except requests.exceptions.RequestException as e:
            log.error(f"  Request error: {e}")
            time.sleep(attempt * 3)

    return None


def fetch_max_pain(symbol="BTC", ex="Deribit", retries=3):
    endpoint = "/api/option/strike_pain"
    for attempt in range(1, retries + 1):
        try:
            cache_ts_v2 = str(int(time.time() * 1000))
            headers = _build_headers(cache_ts_v2)
            params = {"symbol": symbol, "ex": ex}

            log.info(f"[Attempt {attempt}] {endpoint} | {symbol} {ex}")

            r = requests.get(_BASE_URL + endpoint, headers=headers, params=params, timeout=20)
            log.info(f"  Status: {r.status_code} | v={r.headers.get('v','?')} | enc={r.headers.get('encryption','?')}")

            if r.status_code == 401:
                log.error("❌ 401 — obe token expired. Recapture from DevTools.")
                return None
            if r.status_code == 403:
                log.error("❌ 403 Forbidden.")
                return None
            if r.status_code == 429:
                wait_time = 30 * (2 ** (attempt - 1)) + random.uniform(0, 10)
                log.warning(f"⚠️  Rate limited. Waiting {wait_time:.1f}s...")
                time.sleep(wait_time)
                continue

            r.raise_for_status()
            result = _handle_response(r, cache_ts_v2, endpoint)
            if result:
                log.info("  ✅ Decrypted successfully.")
                return result
            log.error("  Decryption failed.")
            return None

        except requests.exceptions.RequestException as e:
            log.error(f"  Request error: {e}")
            time.sleep(attempt * 3)

    return None


def fetch_option_delivery_volume(symbol="BTC", ex="Deribit", subtype="ALL", currency="USD", retries=3):
    endpoint = "/api/option/v2/chart"
    for attempt in range(1, retries + 1):
        try:
            cache_ts_v2 = str(int(time.time() * 1000))
            headers = _build_headers(cache_ts_v2)
            params = {
                "symbol": symbol,
                "ex": ex,
                "type": "Delivery",
                "subtype": subtype,
                "currency": currency,
            }

            log.info(f"[Attempt {attempt}] {endpoint} | {symbol} Delivery")

            r = requests.get(_BASE_URL + endpoint, headers=headers, params=params, timeout=20)
            log.info(f"  Status: {r.status_code} | v={r.headers.get('v','?')} | enc={r.headers.get('encryption','?')}")

            if r.status_code == 401:
                log.error("❌ 401 — obe token expired. Recapture from DevTools.")
                return None
            if r.status_code == 403:
                log.error("❌ 403 Forbidden.")
                return None
            if r.status_code == 429:
                wait_time = 30 * (2 ** (attempt - 1)) + random.uniform(0, 10)
                log.warning(f"⚠️  Rate limited. Waiting {wait_time:.1f}s...")
                time.sleep(wait_time)
                continue

            r.raise_for_status()
            result = _handle_response(r, cache_ts_v2, endpoint)
            if result:
                log.info("  ✅ Decrypted successfully.")
                return result
            log.error("  Decryption failed.")
            return None

        except requests.exceptions.RequestException as e:
            log.error(f"  Request error: {e}")
            time.sleep(attempt * 3)

    return None


def fetch_liq_heatmap_binance(symbol="Binance_BTCUSDT", interval=5, limit=288, retries=3):
    endpoint = "/api/index/v2/liqHeatMap"
    for attempt in range(1, retries + 1):
        try:
            cache_ts_v2 = str(int(time.time() * 1000))
            headers = _build_headers(cache_ts_v2)
            params = {
                "merge": "true",
                "symbol": symbol,
                "interval": interval,
                "limit": limit,
            }

            log.info(f"[Attempt {attempt}] {endpoint} | {symbol} {interval}min")

            r = requests.get(_BASE_URL + endpoint, headers=headers, params=params, timeout=20)
            log.info(f"  Status: {r.status_code} | v={r.headers.get('v','?')} | enc={r.headers.get('encryption','?')}")

            if r.status_code == 401:
                log.error("❌ 401 — obe token expired. Recapture from DevTools.")
                return None
            if r.status_code == 403:
                log.error("❌ 403 Forbidden.")
                return None
            if r.status_code == 429:
                wait_time = 30 * (2 ** (attempt - 1)) + random.uniform(0, 10)
                log.warning(f"⚠️  Rate limited. Waiting {wait_time:.1f}s...")
                time.sleep(wait_time)
                continue

            r.raise_for_status()
            result = _handle_response(r, cache_ts_v2, endpoint)
            if result:
                log.info("  ✅ Decrypted successfully.")
                return result
            log.error("  Decryption failed.")
            return None

        except requests.exceptions.RequestException as e:
            log.error(f"  Request error: {e}")
            time.sleep(attempt * 3)

    return None


def fetch_liq_map_exchange(symbol="BTC", interval=1, limit=1500, retries=3):
    endpoint = "/api/index/2/exLiqMap"
    for attempt in range(1, retries + 1):
        try:
            cache_ts_v2 = str(int(time.time() * 1000))
            headers = _build_headers(cache_ts_v2)
            params = {
                "merge": "true",
                "symbol": symbol,
                "interval": interval,
                "limit": limit,
            }

            log.info(f"[Attempt {attempt}] {endpoint} | {symbol} {interval}min")

            r = requests.get(_BASE_URL + endpoint, headers=headers, params=params, timeout=20)
            log.info(f"  Status: {r.status_code} | v={r.headers.get('v','?')} | enc={r.headers.get('encryption','?')}")

            if r.status_code == 401:
                log.error("❌ 401 — obe token expired. Recapture from DevTools.")
                return None
            if r.status_code == 403:
                log.error("❌ 403 Forbidden.")
                return None
            if r.status_code == 429:
                wait_time = 30 * (2 ** (attempt - 1)) + random.uniform(0, 10)
                log.warning(f"⚠️  Rate limited. Waiting {wait_time:.1f}s...")
                time.sleep(wait_time)
                continue

            r.raise_for_status()
            result = _handle_response(r, cache_ts_v2, endpoint)
            if result:
                log.info("  ✅ Decrypted successfully.")
                return result
            log.error("  Decryption failed.")
            return None

        except requests.exceptions.RequestException as e:
            log.error(f"  Request error: {e}")
            time.sleep(attempt * 3)

    return None


def fetch_liq_count_heatmap(type_param="openInterest", time_param="30d", retries=3):
    endpoint = "/api/futures/liquidation/count/heatmap"
    for attempt in range(1, retries + 1):
        try:
            cache_ts_v2 = str(int(time.time() * 1000))
            headers = _build_headers(cache_ts_v2)
            params = {
                "type": type_param,
                "time": time_param,
            }

            log.info(f"[Attempt {attempt}] {endpoint} | {type_param} {time_param}")

            r = requests.get(_BASE_URL + endpoint, headers=headers, params=params, timeout=20)
            log.info(f"  Status: {r.status_code} | v={r.headers.get('v','?')} | enc={r.headers.get('encryption','?')}")

            if r.status_code == 401:
                log.error("❌ 401 — obe token expired. Recapture from DevTools.")
                return None
            if r.status_code == 403:
                log.error("❌ 403 Forbidden.")
                return None
            if r.status_code == 429:
                wait_time = 30 * (2 ** (attempt - 1)) + random.uniform(0, 10)
                log.warning(f"⚠️  Rate limited. Waiting {wait_time:.1f}s...")
                time.sleep(wait_time)
                continue

            r.raise_for_status()
            result = _handle_response(r, cache_ts_v2, endpoint)
            if result:
                log.info("  ✅ Decrypted successfully.")
                return result
            log.error("  Decryption failed.")
            return None

        except requests.exceptions.RequestException as e:
            log.error(f"  Request error: {e}")
            time.sleep(attempt * 3)

    return None


def fetch_hyperliquid_liq_map(symbol="BTC", retries=3):
    endpoint = "/api/hyperliquid/topPosition/liqMap"
    for attempt in range(1, retries + 1):
        try:
            cache_ts_v2 = str(int(time.time() * 1000))
            headers = _build_headers(cache_ts_v2)
            params = {"symbol": symbol}

            log.info(f"[Attempt {attempt}] {endpoint} | {symbol}")

            r = requests.get(_BASE_URL + endpoint, headers=headers, params=params, timeout=20)
            log.info(f"  Status: {r.status_code} | v={r.headers.get('v','?')} | enc={r.headers.get('encryption','?')}")

            if r.status_code == 401:
                log.error("❌ 401 — obe token expired. Recapture from DevTools.")
                return None
            if r.status_code == 403:
                log.error("❌ 403 Forbidden.")
                return None
            if r.status_code == 429:
                wait_time = 30 * (2 ** (attempt - 1)) + random.uniform(0, 10)
                log.warning(f"⚠️  Rate limited. Waiting {wait_time:.1f}s...")
                time.sleep(wait_time)
                continue

            r.raise_for_status()
            result = _handle_response(r, cache_ts_v2, endpoint)
            if result:
                log.info("  ✅ Decrypted successfully.")
                return result
            log.error("  Decryption failed.")
            return None

        except requests.exceptions.RequestException as e:
            log.error(f"  Request error: {e}")
            time.sleep(attempt * 3)

    return None


def fetch_hyperliquid_trader_ratio(interval="day", coin="all", retries=3):
    endpoint = "/api/hyperliquid/position/user/count"
    for attempt in range(1, retries + 1):
        try:
            cache_ts_v2 = str(int(time.time() * 1000))
            headers = _build_headers(cache_ts_v2)
            params = {
                "interval": interval,
                "coin": coin,
            }

            log.info(f"[Attempt {attempt}] {endpoint} | {interval} {coin}")

            r = requests.get(_BASE_URL + endpoint, headers=headers, params=params, timeout=20)
            log.info(f"  Status: {r.status_code} | v={r.headers.get('v','?')} | enc={r.headers.get('encryption','?')}")

            if r.status_code == 401:
                log.error("❌ 401 — obe token expired. Recapture from DevTools.")
                return None
            if r.status_code == 403:
                log.error("❌ 403 Forbidden.")
                return None
            if r.status_code == 429:
                wait_time = 30 * (2 ** (attempt - 1)) + random.uniform(0, 10)
                log.warning(f"⚠️  Rate limited. Waiting {wait_time:.1f}s...")
                time.sleep(wait_time)
                continue

            r.raise_for_status()
            result = _handle_response(r, cache_ts_v2, endpoint)
            if result:
                log.info("  ✅ Decrypted successfully.")
                return result
            log.error("  Decryption failed.")
            return None

        except requests.exceptions.RequestException as e:
            log.error(f"  Request error: {e}")
            time.sleep(attempt * 3)

    return None


def fetch_oi_statistics(symbol="BTC", retries=3):
    endpoint = "/api/openInterest/statistics"
    for attempt in range(1, retries + 1):
        try:
            cache_ts_v2 = str(int(time.time() * 1000))
            headers = _build_headers(cache_ts_v2)
            params = {"symbol": symbol}

            log.info(f"[Attempt {attempt}] {endpoint} | {symbol}")

            r = requests.get(_BASE_URL + endpoint, headers=headers, params=params, timeout=20)
            log.info(f"  Status: {r.status_code} | v={r.headers.get('v','?')} | enc={r.headers.get('encryption','?')}")

            if r.status_code == 401:
                log.error("❌ 401 — obe token expired. Recapture from DevTools.")
                return None
            if r.status_code == 403:
                log.error("❌ 403 Forbidden.")
                return None
            if r.status_code == 429:
                wait_time = 30 * (2 ** (attempt - 1)) + random.uniform(0, 10)
                log.warning(f"⚠️  Rate limited. Waiting {wait_time:.1f}s...")
                time.sleep(wait_time)
                continue

            r.raise_for_status()
            result = _handle_response(r, cache_ts_v2, endpoint)
            if result:
                log.info("  ✅ Decrypted successfully.")
                return result
            log.error("  Decryption failed.")
            return None

        except requests.exceptions.RequestException as e:
            log.error(f"  Request error: {e}")
            time.sleep(attempt * 3)

    return None


def fetch_oi_statistics_altcoin(filter="BTC,ETH", retries=3):
    endpoint = "/api/openInterest/statistics"
    for attempt in range(1, retries + 1):
        try:
            cache_ts_v2 = str(int(time.time() * 1000))
            headers = _build_headers(cache_ts_v2)
            params = {"filter": filter}

            log.info(f"[Attempt {attempt}] {endpoint} | altcoin filter={filter}")

            r = requests.get(_BASE_URL + endpoint, headers=headers, params=params, timeout=20)
            log.info(f"  Status: {r.status_code} | v={r.headers.get('v','?')} | enc={r.headers.get('encryption','?')}")

            if r.status_code == 401:
                log.error("❌ 401 — obe token expired. Recapture from DevTools.")
                return None
            if r.status_code == 403:
                log.error("❌ 403 Forbidden.")
                return None
            if r.status_code == 429:
                wait_time = 30 * (2 ** (attempt - 1)) + random.uniform(0, 10)
                log.warning(f"⚠️  Rate limited. Waiting {wait_time:.1f}s...")
                time.sleep(wait_time)
                continue

            r.raise_for_status()
            result = _handle_response(r, cache_ts_v2, endpoint)
            if result:
                log.info("  ✅ Decrypted successfully.")
                return result
            log.error("  Decryption failed.")
            return None

        except requests.exceptions.RequestException as e:
            log.error(f"  Request error: {e}")
            time.sleep(attempt * 3)

    return None


def fetch_oi_chart_v3(symbol="BTC", timeType=0, exchangeName="", currency="USD", type=0, retries=3):
    endpoint = "/api/openInterest/v3/chart"
    for attempt in range(1, retries + 1):
        try:
            cache_ts_v2 = str(int(time.time() * 1000))
            headers = _build_headers(cache_ts_v2)
            params = {
                "symbol": symbol,
                "timeType": timeType,
                "exchangeName": exchangeName,
                "currency": currency,
                "type": type,
            }

            log.info(f"[Attempt {attempt}] {endpoint} | {symbol} timeType={timeType}")

            r = requests.get(_BASE_URL + endpoint, headers=headers, params=params, timeout=20)
            log.info(f"  Status: {r.status_code} | v={r.headers.get('v','?')} | enc={r.headers.get('encryption','?')}")

            if r.status_code == 401:
                log.error("❌ 401 — obe token expired. Recapture from DevTools.")
                return None
            if r.status_code == 403:
                log.error("❌ 403 Forbidden.")
                return None
            if r.status_code == 429:
                wait_time = 30 * (2 ** (attempt - 1)) + random.uniform(0, 10)
                log.warning(f"⚠️  Rate limited. Waiting {wait_time:.1f}s...")
                time.sleep(wait_time)
                continue

            r.raise_for_status()
            result = _handle_response(r, cache_ts_v2, endpoint)
            if result:
                log.info("  ✅ Decrypted successfully.")
                return result
            log.error("  Decryption failed.")
            return None

        except requests.exceptions.RequestException as e:
            log.error(f"  Request error: {e}")
            time.sleep(attempt * 3)

    return None


def fetch_oi_info(symbol="BTC", retries=3):
    endpoint = "/api/openInterest/info"
    for attempt in range(1, retries + 1):
        try:
            cache_ts_v2 = str(int(time.time() * 1000))
            headers = _build_headers(cache_ts_v2)
            params = {"symbol": symbol}

            log.info(f"[Attempt {attempt}] {endpoint} | {symbol}")

            r = requests.get(_BASE_URL + endpoint, headers=headers, params=params, timeout=20)
            log.info(f"  Status: {r.status_code} | v={r.headers.get('v','?')} | enc={r.headers.get('encryption','?')}")

            if r.status_code == 401:
                log.error("❌ 401 — obe token expired. Recapture from DevTools.")
                return None
            if r.status_code == 403:
                log.error("❌ 403 Forbidden.")
                return None
            if r.status_code == 429:
                wait_time = 30 * (2 ** (attempt - 1)) + random.uniform(0, 10)
                log.warning(f"⚠️  Rate limited. Waiting {wait_time:.1f}s...")
                time.sleep(wait_time)
                continue

            r.raise_for_status()
            result = _handle_response(r, cache_ts_v2, endpoint)
            if result:
                log.info("  ✅ Decrypted successfully.")
                return result
            log.error("  Decryption failed.")
            return None

        except requests.exceptions.RequestException as e:
            log.error(f"  Request error: {e}")
            time.sleep(attempt * 3)

    return None


def fetch_volume_chart(symbol="", type=0, timeType=0, retries=3):
    endpoint = "/api/futures/vol/chart"
    for attempt in range(1, retries + 1):
        try:
            cache_ts_v2 = str(int(time.time() * 1000))
            headers = _build_headers(cache_ts_v2)
            params = {
                "symbol": symbol,
                "type": type,
                "timeType": timeType,
            }

            log.info(f"[Attempt {attempt}] {endpoint} | type={type} timeType={timeType}")

            r = requests.get(_BASE_URL + endpoint, headers=headers, params=params, timeout=20)
            log.info(f"  Status: {r.status_code} | v={r.headers.get('v','?')} | enc={r.headers.get('encryption','?')}")

            if r.status_code == 401:
                log.error("❌ 401 — obe token expired. Recapture from DevTools.")
                return None
            if r.status_code == 403:
                log.error("❌ 403 Forbidden.")
                return None
            if r.status_code == 429:
                wait_time = 30 * (2 ** (attempt - 1)) + random.uniform(0, 10)
                log.warning(f"⚠️  Rate limited. Waiting {wait_time:.1f}s...")
                time.sleep(wait_time)
                continue

            r.raise_for_status()
            result = _handle_response(r, cache_ts_v2, endpoint)
            if result:
                log.info("  ✅ Decrypted successfully.")
                return result
            log.error("  Decryption failed.")
            return None

        except requests.exceptions.RequestException as e:
            log.error(f"  Request error: {e}")
            time.sleep(attempt * 3)

    return None


def fetch_orderbook_liquidity(symbol="Binance_BTCUSDT#1#hundredth_depth", interval="15m", minLimit=False, limit=300, retries=3):
    endpoint = "/api/v2/kline"
    for attempt in range(1, retries + 1):
        try:
            cache_ts_v2 = str(int(time.time() * 1000))
            headers = _build_headers(cache_ts_v2)
            params = {
                "symbol": symbol,
                "interval": interval,
                "minLimit": str(minLimit).lower(),
                "limit": limit,
            }

            log.info(f"[Attempt {attempt}] {endpoint} | {symbol} {interval}")

            r = requests.get(_BASE_URL + endpoint, headers=headers, params=params, timeout=20)
            log.info(f"  Status: {r.status_code} | v={r.headers.get('v','?')} | enc={r.headers.get('encryption','?')}")

            if r.status_code == 401:
                log.error("❌ 401 — obe token expired. Recapture from DevTools.")
                return None
            if r.status_code == 403:
                log.error("❌ 403 Forbidden.")
                return None
            if r.status_code == 429:
                wait_time = 30 * (2 ** (attempt - 1)) + random.uniform(0, 10)
                log.warning(f"⚠️  Rate limited. Waiting {wait_time:.1f}s...")
                time.sleep(wait_time)
                continue

            r.raise_for_status()
            result = _handle_response(r, cache_ts_v2, endpoint)
            if result:
                log.info("  ✅ Decrypted successfully.")
                return result
            log.error("  Decryption failed.")
            return None

        except requests.exceptions.RequestException as e:
            log.error(f"  Request error: {e}")
            time.sleep(attempt * 3)

    return None


def fetch_kline_premium_index(symbol="Binance_BTCUSDT#premium_index", interval="m1", minLimit=False, limit=300, retries=3):
    endpoint = "/api/kline"
    for attempt in range(1, retries + 1):
        try:
            cache_ts_v2 = str(int(time.time() * 1000))
            headers = _build_headers(cache_ts_v2)
            params = {
                "symbol": symbol,
                "interval": interval,
                "minLimit": str(minLimit).lower(),
                "limit": limit,
            }

            log.info(f"[Attempt {attempt}] {endpoint} (Binance premium) | {symbol}")

            r = requests.get(_BASE_URL + endpoint, headers=headers, params=params, timeout=20)
            log.info(f"  Status: {r.status_code} | v={r.headers.get('v','?')} | enc={r.headers.get('encryption','?')}")

            if r.status_code == 401:
                log.error("❌ 401 — obe token expired. Recapture from DevTools.")
                return None
            if r.status_code == 403:
                log.error("❌ 403 Forbidden.")
                return None
            if r.status_code == 429:
                wait_time = 30 * (2 ** (attempt - 1)) + random.uniform(0, 10)
                log.warning(f"⚠️  Rate limited. Waiting {wait_time:.1f}s...")
                time.sleep(wait_time)
                continue

            r.raise_for_status()
            result = _handle_response(r, cache_ts_v2, endpoint)
            if result:
                log.info("  ✅ Decrypted successfully.")
                return result
            log.error("  Decryption failed.")
            return None

        except requests.exceptions.RequestException as e:
            log.error(f"  Request error: {e}")
            time.sleep(attempt * 3)

    return None


def fetch_kline_coinbase_premium(symbol="Binance_BTCUSDT#coinbase_premium_index", interval="m30", limit=300, retries=3):
    endpoint = "/api/kline"
    for attempt in range(1, retries + 1):
        try:
            cache_ts_v2 = str(int(time.time() * 1000))
            headers = _build_headers(cache_ts_v2)
            params = {
                "symbol": symbol,
                "interval": interval,
                "limit": limit,
            }

            log.info(f"[Attempt {attempt}] {endpoint} (Coinbase premium) | {symbol}")

            r = requests.get(_BASE_URL + endpoint, headers=headers, params=params, timeout=20)
            log.info(f"  Status: {r.status_code} | v={r.headers.get('v','?')} | enc={r.headers.get('encryption','?')}")

            if r.status_code == 401:
                log.error("❌ 401 — obe token expired. Recapture from DevTools.")
                return None
            if r.status_code == 403:
                log.error("❌ 403 Forbidden.")
                return None
            if r.status_code == 429:
                wait_time = 30 * (2 ** (attempt - 1)) + random.uniform(0, 10)
                log.warning(f"⚠️  Rate limited. Waiting {wait_time:.1f}s...")
                time.sleep(wait_time)
                continue

            r.raise_for_status()
            result = _handle_response(r, cache_ts_v2, endpoint)
            if result:
                log.info("  ✅ Decrypted successfully.")
                return result
            log.error("  Decryption failed.")
            return None

        except requests.exceptions.RequestException as e:
            log.error(f"  Request error: {e}")
            time.sleep(attempt * 3)

    return None


def fetch_btc_dominance(retries=3):
    endpoint = "/api/escape/index/bitcoinDominance"
    for attempt in range(1, retries + 1):
        try:
            cache_ts_v2 = str(int(time.time() * 1000))
            headers = _build_headers(cache_ts_v2)

            log.info(f"[Attempt {attempt}] {endpoint}")

            r = requests.get(_BASE_URL + endpoint, headers=headers, timeout=20)
            log.info(f"  Status: {r.status_code} | v={r.headers.get('v','?')} | enc={r.headers.get('encryption','?')}")

            if r.status_code == 401:
                log.error("❌ 401 — obe token expired. Recapture from DevTools.")
                return None
            if r.status_code == 403:
                log.error("❌ 403 Forbidden.")
                return None
            if r.status_code == 429:
                wait_time = 30 * (2 ** (attempt - 1)) + random.uniform(0, 10)
                log.warning(f"⚠️  Rate limited. Waiting {wait_time:.1f}s...")
                time.sleep(wait_time)
                continue

            r.raise_for_status()
            result = _handle_response(r, cache_ts_v2, endpoint)
            if result:
                log.info("  ✅ Decrypted successfully.")
                return result
            log.error("  Decryption failed.")
            return None

        except requests.exceptions.RequestException as e:
            log.error(f"  Request error: {e}")
            time.sleep(attempt * 3)

    return None


def fetch_funding_rate_history(symbol="BTC", type_param="U", interval="h8", retries=3):
    endpoint = "/api/fundingRate/v2/history/chart"
    for attempt in range(1, retries + 1):
        try:
            cache_ts_v2 = str(int(time.time() * 1000))
            headers = _build_headers(cache_ts_v2)
            params = {
                "symbol": symbol,
                "type": type_param,
                "interval": interval,
            }

            log.info(f"[Attempt {attempt}] {endpoint} | {symbol} {interval}")

            r = requests.get(_BASE_URL + endpoint, headers=headers, params=params, timeout=20)
            log.info(f"  Status: {r.status_code} | v={r.headers.get('v','?')} | enc={r.headers.get('encryption','?')}")

            if r.status_code == 401:
                log.error("❌ 401 — obe token expired. Recapture from DevTools.")
                return None
            if r.status_code == 403:
                log.error("❌ 403 Forbidden.")
                return None
            if r.status_code == 429:
                wait_time = 30 * (2 ** (attempt - 1)) + random.uniform(0, 10)
                log.warning(f"⚠️  Rate limited. Waiting {wait_time:.1f}s...")
                time.sleep(wait_time)
                continue

            r.raise_for_status()
            result = _handle_response(r, cache_ts_v2, endpoint)
            if result:
                log.info("  ✅ Decrypted successfully.")
                return result
            log.error("  Decryption failed.")
            return None

        except requests.exceptions.RequestException as e:
            log.error(f"  Request error: {e}")
            time.sleep(attempt * 3)

    return None


def fetch_insurance_fund(ex="Binance", symbol="BTCUSDT", retries=3):
    endpoint = "/api/futures/insuranceFundBalance/history"
    for attempt in range(1, retries + 1):
        try:
            cache_ts_v2 = str(int(time.time() * 1000))
            headers = _build_headers(cache_ts_v2)
            params = {
                "ex": ex,
                "symbol": symbol,
            }

            log.info(f"[Attempt {attempt}] {endpoint} | {ex} {symbol}")

            r = requests.get(_BASE_URL + endpoint, headers=headers, params=params, timeout=20)
            log.info(f"  Status: {r.status_code} | v={r.headers.get('v','?')} | enc={r.headers.get('encryption','?')}")

            if r.status_code == 401:
                log.error("❌ 401 — obe token expired. Recapture from DevTools.")
                return None
            if r.status_code == 403:
                log.error("❌ 403 Forbidden.")
                return None
            if r.status_code == 429:
                wait_time = 30 * (2 ** (attempt - 1)) + random.uniform(0, 10)
                log.warning(f"⚠️  Rate limited. Waiting {wait_time:.1f}s...")
                time.sleep(wait_time)
                continue

            r.raise_for_status()
            result = _handle_response(r, cache_ts_v2, endpoint)
            if result:
                log.info("  ✅ Decrypted successfully.")
                return result
            log.error("  Decryption failed.")
            return None

        except requests.exceptions.RequestException as e:
            log.error(f"  Request error: {e}")
            time.sleep(attempt * 3)

    return None


def fetch_kline_margin_rate(symbol="Binance_USDT#margin", interval="h1", minLimit=False, limit=300, retries=3):
    endpoint = "/api/kline"
    for attempt in range(1, retries + 1):
        try:
            cache_ts_v2 = str(int(time.time() * 1000))
            headers = _build_headers(cache_ts_v2)
            params = {
                "symbol": symbol,
                "interval": interval,
                "minLimit": str(minLimit).lower(),
                "limit": limit,
            }

            log.info(f"[Attempt {attempt}] {endpoint} (Binance margin) | {symbol}")

            r = requests.get(_BASE_URL + endpoint, headers=headers, params=params, timeout=20)
            log.info(f"  Status: {r.status_code} | v={r.headers.get('v','?')} | enc={r.headers.get('encryption','?')}")

            if r.status_code == 401:
                log.error("❌ 401 — obe token expired. Recapture from DevTools.")
                return None
            if r.status_code == 403:
                log.error("❌ 403 Forbidden.")
                return None
            if r.status_code == 429:
                wait_time = 30 * (2 ** (attempt - 1)) + random.uniform(0, 10)
                log.warning(f"⚠️  Rate limited. Waiting {wait_time:.1f}s...")
                time.sleep(wait_time)
                continue

            r.raise_for_status()
            result = _handle_response(r, cache_ts_v2, endpoint)
            if result:
                log.info("  ✅ Decrypted successfully.")
                return result
            log.error("  Decryption failed.")
            return None

        except requests.exceptions.RequestException as e:
            log.error(f"  Request error: {e}")
            time.sleep(attempt * 3)

    return None


def fetch_liquidation_events(slug="pro-futures-liquidation-events", lang="en", retries=3):
    endpoint = "/api/strapi/page"
    for attempt in range(1, retries + 1):
        try:
            cache_ts_v2 = str(int(time.time() * 1000))
            headers = _build_headers(cache_ts_v2)
            params = {
                "slug": slug,
                "lang": lang,
            }

            log.info(f"[Attempt {attempt}] {endpoint} | {slug}")

            r = requests.get(_BASE_URL + endpoint, headers=headers, params=params, timeout=20)
            log.info(f"  Status: {r.status_code}")

            if r.status_code == 401:
                log.error("❌ 401 — obe token expired. Recapture from DevTools.")
                return None
            if r.status_code == 403:
                log.error("❌ 403 Forbidden.")
                return None
            if r.status_code == 429:
                wait_time = 30 * (2 ** (attempt - 1)) + random.uniform(0, 10)
                log.warning(f"⚠️  Rate limited. Waiting {wait_time:.1f}s...")
                time.sleep(wait_time)
                continue

            r.raise_for_status()
            body = r.json()
            log.info("  ✅ Fetched successfully.")
            return body

        except requests.exceptions.RequestException as e:
            log.error(f"  Request error: {e}")
            time.sleep(attempt * 3)

    return None


def fetch_bitmex_funding_rate(slug="pro-futures-BitmexFundingRate", lang="en", retries=3):
    endpoint = "/api/strapi/page"
    for attempt in range(1, retries + 1):
        try:
            cache_ts_v2 = str(int(time.time() * 1000))
            headers = _build_headers(cache_ts_v2)
            params = {
                "slug": slug,
                "lang": lang,
            }

            log.info(f"[Attempt {attempt}] {endpoint} | {slug}")

            r = requests.get(_BASE_URL + endpoint, headers=headers, params=params, timeout=20)
            log.info(f"  Status: {r.status_code}")

            if r.status_code == 401:
                log.error("❌ 401 — obe token expired. Recapture from DevTools.")
                return None
            if r.status_code == 403:
                log.error("❌ 403 Forbidden.")
                return None
            if r.status_code == 429:
                wait_time = 30 * (2 ** (attempt - 1)) + random.uniform(0, 10)
                log.warning(f"⚠️  Rate limited. Waiting {wait_time:.1f}s...")
                time.sleep(wait_time)
                continue

            r.raise_for_status()
            body = r.json()
            log.info("  ✅ Fetched successfully.")
            return body

        except requests.exceptions.RequestException as e:
            log.error(f"  Request error: {e}")
            time.sleep(attempt * 3)

    return None


# ══════════════════════════════════════════════════════════════════════════════
#  PARSER
# ══════════════════════════════════════════════════════════════════════════════

def parse_heatmap(raw: dict) -> list[dict] | None:
    inner = raw.get("data", raw)
    if isinstance(inner, dict) and "data" in inner:
        inner = inner["data"]

    price_list = inner.get("y") or inner.get("priceList") or []
    time_list  = inner.get("x") or inner.get("timeList")  or []
    matrix     = inner.get("data") or inner.get("dataMap") or []

    if not price_list or not time_list or not matrix:
        log.warning(f"Unexpected structure. Keys: {list(inner.keys())}")
        return None

    log.info(f"  {len(price_list)} price levels × {len(time_list)} time points")

    records = []
    if isinstance(matrix, list):
        for pi, row in enumerate(matrix):
            if pi >= len(price_list) or not isinstance(row, list):
                continue
            price = price_list[pi]
            for ti, vol in enumerate(row):
                if vol and vol > 0 and ti < len(time_list):
                    ts = time_list[ti]
                    records.append({
                        "price":    price,
                        "timestamp":ts,
                        "datetime": datetime.fromtimestamp(ts/1000, tz=timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
                        "volume":   vol,
                    })
    elif isinstance(matrix, dict):
        for price_str, volumes in matrix.items():
            price = float(price_str)
            for i, vol in enumerate(volumes):
                if vol and vol > 0 and i < len(time_list):
                    ts = time_list[i]
                    records.append({
                        "price":    price,
                        "timestamp":ts,
                        "datetime": datetime.fromtimestamp(ts/1000, tz=timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
                        "volume":   vol,
                    })
    return records


def save_json(data, name):
    p = OUTPUT_DIR / name
    with open(p, "w") as f:
        json.dump(data, f, indent=2)
    log.info(f"💾 {p}")

def save_csv(records, name):
    if not records: return
    p = OUTPUT_DIR / name
    keys = list(records[0].keys())
    with open(p, "w") as f:
        f.write(",".join(keys) + "\n")
        for row in records:
            f.write(",".join(str(row.get(k,"")) for k in keys) + "\n")
    log.info(f"💾 {p}")


# ══════════════════════════════════════════════════════════════════════════════
#  MAIN
# ══════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    log.info("=" * 60)
    log.info("  CoinGlass Heatmap Scraper — Fully Decoded")
    log.info("=" * 60)

    if "PASTE" in OBE:
        log.error("❌ Set your OBE token at the top of this file.")
        log.error("   DevTools → Network → liqHeatMap → Request Headers → obe")
        exit(1)

    ts  = datetime.now().strftime("%Y%m%d_%H%M%S")
    raw = fetch_heatmap("Binance_BTCUSDT", interval=5, limit=288)

    if raw:
        save_json(raw, f"raw_BTC_{ts}.json")
        records = parse_heatmap(raw)
        if records:
            save_csv(records, f"BTC_heatmap_{ts}.csv")
            prices  = [r["price"]  for r in records]
            volumes = [r["volume"] for r in records]
            log.info(f"\n📈 Price range : ${min(prices):,.0f} – ${max(prices):,.0f}")
            log.info(f"   Total volume: {sum(volumes):,.2f}")
            log.info(f"   Peak volume : {max(volumes):,.2f}")
            log.info(f"   Records     : {len(records)}")
        log.info("\n✅ Done. Check output/")
    else:
        log.error("\n❌ Failed — check output/ for debug_raw_*.json")

    log.info("\n── OI Expiry ──")
    global_limiter.wait()
    data = fetch_oi_expiry()
    if data: save_json(data, f"oi_expiry_{ts}.json")

    log.info("\n── Options OI ──")
    global_limiter.wait()
    data = fetch_options_oi()
    if data: save_json(data, f"options_oi_{ts}.json")

    log.info("\n── Options vs Futures ──")
    global_limiter.wait()
    data = fetch_options_vs_futures()
    if data: save_json(data, f"options_vs_futures_{ts}.json")

    log.info("\n── Options Greeks ──")
    global_limiter.wait()
    data = fetch_options_greeks()
    if data: save_json(data, f"options_greeks_{ts}.json")

    log.info("\n── Max Pain ──")
    global_limiter.wait()
    data = fetch_max_pain()
    if data: save_json(data, f"max_pain_{ts}.json")

    log.info("\n── Option Delivery Volume ──")
    global_limiter.wait()
    data = fetch_option_delivery_volume()
    if data: save_json(data, f"delivery_volume_{ts}.json")

    log.info("\n── Liquidation Heatmap (Binance) ──")
    global_limiter.wait()
    data = fetch_liq_heatmap_binance()
    if data: save_json(data, f"liq_heatmap_binance_{ts}.json")

    log.info("\n── Liquidation Map (Exchange) ──")
    global_limiter.wait()
    data = fetch_liq_map_exchange()
    if data: save_json(data, f"liq_map_exchange_{ts}.json")

    log.info("\n── Liquidation Count Heatmap ──")
    global_limiter.wait()
    data = fetch_liq_count_heatmap()
    if data: save_json(data, f"liq_count_heatmap_{ts}.json")

    log.info("\n── Hyperliquid Liquidation Map ──")
    global_limiter.wait()
    data = fetch_hyperliquid_liq_map()
    if data: save_json(data, f"hyperliq_liqmap_{ts}.json")

    log.info("\n── Hyperliquid Trader Ratio ──")
    global_limiter.wait()
    data = fetch_hyperliquid_trader_ratio()
    if data: save_json(data, f"hyperliq_ratio_{ts}.json")

    log.info("\n── OI Statistics ──")
    global_limiter.wait()
    data = fetch_oi_statistics()
    if data: save_json(data, f"oi_stats_{ts}.json")

    log.info("\n── OI Statistics (Altcoin) ──")
    global_limiter.wait()
    data = fetch_oi_statistics_altcoin()
    if data: save_json(data, f"oi_stats_altcoin_{ts}.json")

    log.info("\n── OI Chart v3 ──")
    global_limiter.wait()
    data = fetch_oi_chart_v3()
    if data: save_json(data, f"oi_chart_v3_{ts}.json")

    log.info("\n── OI Info ──")
    global_limiter.wait()
    data = fetch_oi_info()
    if data: save_json(data, f"oi_info_{ts}.json")

    log.info("\n── Volume Chart ──")
    global_limiter.wait()
    data = fetch_volume_chart()
    if data: save_json(data, f"vol_chart_{ts}.json")

    log.info("\n── Orderbook Liquidity ──")
    global_limiter.wait()
    data = fetch_orderbook_liquidity()
    if data: save_json(data, f"orderbook_liquidity_{ts}.json")

    log.info("\n── Kline Premium Index (Binance) ──")
    global_limiter.wait()
    data = fetch_kline_premium_index()
    if data: save_json(data, f"premium_index_{ts}.json")

    log.info("\n── Kline Coinbase Premium ──")
    global_limiter.wait()
    data = fetch_kline_coinbase_premium()
    if data: save_json(data, f"coinbase_premium_{ts}.json")

    log.info("\n── BTC Dominance ──")
    global_limiter.wait()
    data = fetch_btc_dominance()
    if data: save_json(data, f"btc_dominance_{ts}.json")

    log.info("\n── Funding Rate History ──")
    global_limiter.wait()
    data = fetch_funding_rate_history()
    if data: save_json(data, f"funding_rate_history_{ts}.json")

    log.info("\n── Insurance Fund ──")
    global_limiter.wait()
    data = fetch_insurance_fund()
    if data: save_json(data, f"insurance_fund_{ts}.json")

    log.info("\n── Kline Margin Rate (Binance) ──")
    global_limiter.wait()
    data = fetch_kline_margin_rate()
    if data: save_json(data, f"margin_rate_{ts}.json")

    log.info("\n── Liquidation Events (Strapi) ──")
    global_limiter.wait()
    data = fetch_liquidation_events()
    if data: save_json(data, f"liquidation_events_{ts}.json")

    log.info("\n── BitMEX Funding Rate (Strapi) ──")
    global_limiter.wait()
    data = fetch_bitmex_funding_rate()
    if data: save_json(data, f"bitmex_funding_rate_{ts}.json")

    log.info("\n── Output Dashboard ──")
    try:
        from build_output_dashboard import build_output_dashboard

        build_output_dashboard(OUTPUT_DIR)
        log.info("📊 Refreshed output/index.html and output/dashboard_data.js")
    except Exception as exc:
        log.warning(f"Dashboard build skipped: {exc}")
