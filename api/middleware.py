"""
API Rate Limiting and Middleware
"""
import ipaddress
import time
from typing import Callable, Optional
from fastapi import Request, HTTPException, status
from fastapi.responses import JSONResponse
import redis
import structlog

from api.config import get_settings
from observability.instrumentation import (
    bind_request_context,
    clear_request_context,
    capture_exception,
    generate_correlation_id,
    observe_request,
    record_api_error,
    traced_operation,
)

logger = structlog.get_logger(__name__)


def _get_real_client_ip(request: Request) -> str:
    """
    Extract the real client IP from X-Forwarded-For when the direct peer
    is a known trusted proxy.  Falls back to request.client.host otherwise.
    """
    peer = request.client.host if request.client else "unknown"

    forwarded = request.headers.get("X-Forwarded-For")
    if not forwarded:
        return peer

    settings = get_settings()
    try:
        peer_ip = ipaddress.ip_address(peer)
    except ValueError:
        return peer

    trusted = any(
        peer_ip in ipaddress.ip_network(cidr, strict=False)
        for cidr in settings.TRUSTED_PROXIES
    )
    if not trusted:
        return peer

    # The leftmost address in X-Forwarded-For is the original client.
    client_ip = forwarded.split(",")[0].strip()
    try:
        ipaddress.ip_address(client_ip)
        return client_ip
    except ValueError:
        return peer


class RateLimiter:
    """Token bucket rate limiter using Redis"""

    # Lua script: atomically increment the counter and set TTL on first write.
    # Redis executes Lua scripts as a single atomic operation, so there is no
    # window between INCR and EXPIRE where the key can be left without a TTL.
    _INCR_EXPIRE_SCRIPT = """
local current = redis.call('INCR', KEYS[1])
if current == 1 then
    redis.call('EXPIRE', KEYS[1], ARGV[1])
end
return current
"""

    def __init__(self, redis_url: str = "redis://localhost:6379/0"):
        self.redis = redis.from_url(redis_url, decode_responses=True)
        self.requests = 100  # requests
        self.window = 60  # seconds
        self._script = self.redis.register_script(self._INCR_EXPIRE_SCRIPT)

    def is_allowed(self, key: str) -> bool:
        """Check if request is allowed"""
        try:
            current = int(self._script(keys=[key], args=[self.window]))
            return current <= self.requests
        except Exception as e:
            logger.error("Rate limiter error", error=str(e))
            # Fail open - allow request if Redis unavailable
            return True
    
    def get_retry_after(self, key: str) -> int:
        """Get seconds until next request allowed"""
        try:
            ttl = self.redis.ttl(key)
            return ttl if ttl > 0 else self.window
        except:
            return self.window


async def rate_limit_middleware(request: Request, call_next: Callable):
    """Rate limiting middleware"""
    
    # Skip rate limiting for health checks
    if request.url.path in ["/api/v1/health", "/api/v1/health/ready", "/api/v1/health/live"]:
        return await call_next(request)
    
    # Get real client IP (supports trusted proxies and X-Forwarded-For)
    client_ip = _get_real_client_ip(request)
    user_id = request.headers.get("X-User-Id", client_ip)
    
    rate_limiter = RateLimiter()
    rate_limit_key = f"ratelimit:{user_id}:{int(time.time() // 60)}"
    
    if not rate_limiter.is_allowed(rate_limit_key):
        logger.warning(
            "Rate limit exceeded",
            user_id=user_id,
            ip=client_ip
        )
        return JSONResponse(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            content={
                "error_code": "RATE_LIMIT_EXCEEDED",
                "message": f"Rate limit exceeded. Max {rate_limiter.requests} requests per {rate_limiter.window} seconds",
                "retry_after": rate_limiter.get_retry_after(rate_limit_key)
            },
            headers={"Retry-After": str(rate_limiter.get_retry_after(rate_limit_key))}
        )
    
    response = await call_next(request)
    response.headers["X-RateLimit-Limit"] = str(rate_limiter.requests)
    try:
        current_count = int(rate_limiter.redis.get(rate_limit_key) or 0)
    except Exception:
        current_count = 0
    response.headers["X-RateLimit-Remaining"] = str(max(0, rate_limiter.requests - current_count))
    
    return response


async def add_correlation_id_middleware(request: Request, call_next: Callable):
    """Add correlation ID to all requests"""
    
    correlation_id = request.headers.get("X-Correlation-Id")
    if not correlation_id:
        correlation_id = generate_correlation_id()
    
    request.state.correlation_id = correlation_id
    request.state.request_id = correlation_id
    request.state.user_id = request.headers.get("X-User-Id") or request.headers.get("Authorization")
    
    try:
        response = await call_next(request)
        response.headers["X-Correlation-Id"] = correlation_id
        response.headers["X-Request-Id"] = correlation_id
        return response
    finally:
        pass


async def error_handling_middleware(request: Request, call_next: Callable):
    """Global error handling middleware"""
    
    try:
        response = await call_next(request)
        return response
    except HTTPException:
        raise
    except Exception as e:
        logger.error(
            "Unhandled error",
            path=request.url.path,
            method=request.method,
            error=str(e)
        )
        record_api_error(request.url.path, e)
        capture_exception(e, path=request.url.path, method=request.method)
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={
                "error_code": "INTERNAL_SERVER_ERROR",
                "message": "An internal error occurred"
            }
        )


async def logging_middleware(request: Request, call_next: Callable):
    """Log all requests and responses"""
    
    start_time = time.time()
    endpoint = request.url.path
    request_id = getattr(request.state, "request_id", request.headers.get("X-Correlation-Id") or generate_correlation_id())
    user_id = getattr(request.state, "user_id", request.headers.get("X-User-Id"))

    bind_request_context(request_id=request_id, user_id=user_id)

    with traced_operation(
        f"http {request.method} {endpoint}",
        {
            "http.method": request.method,
            "http.target": endpoint,
            "request.id": request_id,
            "user.id": user_id or "anonymous",
        },
    ):
        try:
            response = await call_next(request)
        except Exception as exc:
            duration = time.time() - start_time
            observe_request(endpoint, request.method, 500, duration)
            logger.error(
                "http_request_failed",
                method=request.method,
                path=endpoint,
                status_code=500,
                duration_ms=round(duration * 1000, 2),
                request_id=request_id,
                user_id=user_id,
                error=str(exc),
            )
            raise
        finally:
            clear_request_context()

    process_time = time.time() - start_time
    observe_request(endpoint, request.method, response.status_code, process_time)

    logger.info(
        "http_request_completed",
        method=request.method,
        path=endpoint,
        status_code=response.status_code,
        duration_ms=round(process_time * 1000, 2),
        request_id=request_id,
        user_id=user_id,
    )

    response.headers["X-Process-Time"] = str(process_time)
    response.headers["X-Request-Id"] = request_id
    return response
