"""Roostoo mock-exchange REST client.

- HMAC-SHA256 signing over the key-sorted ``k=v&k=v`` parameter string
- Client-side rate limiting (token bucket) below the exchange's 30 calls/min
- Retries with exponential backoff on network errors / 5xx
- The exchange answers failures with HTTP 200 + ``Success: false``; callers get
  the parsed JSON and must check ``Success`` (see ``ok``)
- Every call is reported to an optional ``on_call`` hook for audit logging
"""
from __future__ import annotations

import hashlib
import hmac
import logging
import threading
import time
from collections import deque
from typing import Any, Callable, Optional

import requests

log = logging.getLogger(__name__)


def sign(params: dict, secret: str) -> str:
    query = "&".join(f"{k}={params[k]}" for k in sorted(params))
    return hmac.new(secret.encode(), query.encode(), hashlib.sha256).hexdigest()


def ok(resp: Optional[dict]) -> bool:
    return bool(resp) and bool(resp.get("Success"))


class RateLimiter:
    """Sliding-window limiter: at most ``max_calls`` per ``period`` seconds."""

    def __init__(self, max_calls: int, period: float = 60.0):
        self.max_calls = max_calls
        self.period = period
        self.calls: deque = deque()
        self.lock = threading.Lock()

    def acquire(self) -> None:
        with self.lock:
            while True:
                now = time.monotonic()
                while self.calls and now - self.calls[0] >= self.period:
                    self.calls.popleft()
                if len(self.calls) < self.max_calls:
                    self.calls.append(now)
                    return
                time.sleep(self.period - (now - self.calls[0]) + 0.05)


class RoostooClient:
    def __init__(
        self,
        api_key: str,
        api_secret: str,
        base_url: str = "https://mock-api.roostoo.com",
        max_calls_per_minute: int = 20,
        timeout: float = 10.0,
        max_retries: int = 3,
        on_call: Optional[Callable[[dict], None]] = None,
    ):
        self.api_key = api_key
        self.api_secret = api_secret
        self.base_url = base_url.rstrip("/")
        self.limiter = RateLimiter(max_calls_per_minute)
        self.timeout = timeout
        self.max_retries = max_retries
        self.on_call = on_call
        self.session = requests.Session()
        self.time_offset_ms = 0  # server_time - local_time

    # ------------------------------------------------------------------ core
    def _ts(self) -> str:
        return str(int(time.time() * 1000) + self.time_offset_ms)

    def _request(self, method: str, path: str, params: Optional[dict] = None,
                 signed: bool = False, timestamped: bool = True) -> Optional[dict]:
        params = {k: v for k, v in (params or {}).items() if v is not None}
        if timestamped:
            params["timestamp"] = self._ts()
        params = {k: str(v) for k, v in params.items()}
        headers = {}
        if signed:
            headers["RST-API-KEY"] = self.api_key
            headers["MSG-SIGNATURE"] = sign(params, self.api_secret)
        if method == "POST":
            headers["Content-Type"] = "application/x-www-form-urlencoded"

        url = self.base_url + path
        delay = 1.0
        for attempt in range(1, self.max_retries + 1):
            self.limiter.acquire()
            t0 = time.monotonic()
            status, data, error = None, None, None
            try:
                if method == "GET":
                    r = self.session.get(url, params=params, headers=headers, timeout=self.timeout)
                else:
                    r = self.session.post(url, data=params, headers=headers, timeout=self.timeout)
                status = r.status_code
                if status >= 500 or status == 429:
                    error = f"HTTP {status}"
                else:
                    try:
                        data = r.json()
                    except ValueError:
                        error = f"non-JSON response (HTTP {status}): {r.text[:200]}"
            except requests.RequestException as exc:
                error = f"{type(exc).__name__}: {exc}"
            latency = time.monotonic() - t0
            self._report(method, path, params, status, data, error, latency, attempt)
            if data is not None:
                return data
            if attempt < self.max_retries:
                log.warning("%s %s failed (%s); retry %d in %.1fs", method, path, error, attempt, delay)
                time.sleep(delay)
                delay *= 2
        log.error("%s %s failed after %d attempts", method, path, self.max_retries)
        return None

    def _report(self, method, path, params, status, data, error, latency, attempt):
        if not self.on_call:
            return
        safe_params = {k: v for k, v in params.items() if k != "timestamp"}
        try:
            self.on_call({
                "method": method, "path": path, "params": safe_params,
                "http_status": status, "success": bool(data is not None and data.get("Success", True)),
                "err_msg": (data or {}).get("ErrMsg") or error,
                "latency_ms": round(latency * 1000, 1), "attempt": attempt,
            })
        except Exception:  # audit logging must never break trading
            log.exception("on_call hook failed")

    # ------------------------------------------------------------ public data
    def server_time(self) -> Optional[dict]:
        return self._request("GET", "/v3/serverTime", timestamped=False)

    def sync_time(self) -> None:
        resp = self.server_time()
        if resp and "ServerTime" in resp:
            self.time_offset_ms = int(resp["ServerTime"]) - int(time.time() * 1000)

    def exchange_info(self) -> Optional[dict]:
        return self._request("GET", "/v3/exchangeInfo", timestamped=False)

    def ticker(self, pair: Optional[str] = None) -> Optional[dict]:
        return self._request("GET", "/v3/ticker", {"pair": pair})

    # ---------------------------------------------------------------- account
    def balance(self) -> Optional[dict]:
        return self._request("GET", "/v3/balance", signed=True)

    def pending_count(self) -> Optional[dict]:
        return self._request("GET", "/v3/pending_count", signed=True)

    # ----------------------------------------------------------------- orders
    def place_order(self, pair: str, side: str, quantity: str, order_type: str = "MARKET",
                    price: Optional[str] = None) -> Optional[dict]:
        params = {"pair": pair, "side": side.upper(), "type": order_type.upper(), "quantity": quantity}
        if order_type.upper() == "LIMIT":
            if price is None:
                raise ValueError("LIMIT order requires price")
            params["price"] = price
        return self._request("POST", "/v3/place_order", params, signed=True)

    def query_order(self, order_id: Optional[str] = None, pair: Optional[str] = None,
                    pending_only: Optional[bool] = None, limit: Optional[int] = None) -> Optional[dict]:
        params: dict[str, Any] = {}
        if order_id is not None:
            params["order_id"] = order_id
        else:
            params["pair"] = pair
            if pending_only is not None:
                params["pending_only"] = "TRUE" if pending_only else "FALSE"
            params["limit"] = limit
        return self._request("POST", "/v3/query_order", params, signed=True)

    def cancel_order(self, order_id: Optional[str] = None, pair: Optional[str] = None) -> Optional[dict]:
        params = {"order_id": order_id} if order_id is not None else {"pair": pair}
        return self._request("POST", "/v3/cancel_order", params, signed=True)

    # ----------------------------------------------------------------- shorts
    def short_open(self, pair: str, collateral: str) -> Optional[dict]:
        return self._request("POST", "/v6/short_open", {"pair": pair, "collateral": collateral}, signed=True)

    def short_close(self, pair: str, close_pct: Optional[str] = None) -> Optional[dict]:
        return self._request("POST", "/v6/short_close", {"pair": pair, "close_pct": close_pct}, signed=True)

    def short_positions(self) -> Optional[dict]:
        return self._request("GET", "/v6/short_positions", signed=True)
