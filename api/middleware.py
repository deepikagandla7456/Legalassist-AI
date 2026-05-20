"""API middleware for abuse protection, request context, and logging."""

from __future__ import annotations

import hashlib
import json
import time
from typing import Callable
from hashlib import sha256

from sqlalchemy.orm import Session

from api.auth import verify_token, verify_api_key
from database import SessionLocal
from db.models import APIKey

import structlog
from fastapi import HTTPException, Request, status
from fastapi.responses import JSONResponse, Response

from api.config import get_settings
from api.idempotency import IdempotencyManager
from api.limiter import (
    build_rate_limit_response,
    get_rate_limit_policy,
    is_whitelisted,
    limiter,
    resolve_rate_limit_identifier,
)
from api.validation import PayloadTooLargeError, ValidationConfig
from observability.instrumentation import (
    bind_request_context,
    capture_exception,
    clear_request_context,
    generate_correlation_id,
    observe_request,
    record_api_error,
    traced_operation,
)

settings = get_settings()
logger = structlog.get_logger(__name__)
http_idempotency_manager = IdempotencyManager()

SKIP_PATHS = {"/api/v1/health", "/api/v1/health/ready", "/api/v1/health/live", "/metrics", "/"}
UPLOAD_PATH_PREFIXES = (
    "/api/v1/analyze/upload",
    "/api/v1/analyze/document",
    "/api/v1/documents",
)
ANALYTICS_PATH_PREFIXES = (
    "/api/v1/analytics",
)
IDEMPOTENT_METHODS = {"POST", "PUT", "PATCH", "DELETE"}


def _request_principal(request: Request) -> str:
    """Derive a safe principal for idempotency keys.

    Priority:
    1. Verified JWT -> `user:<user_id>`
    2. Verified API key -> `api_key:<key_id>` (or `user:<user_id>` if linked)
    3. Fallback anonymous fingerprint -> `anonymous:<sha256(ip|ua)>`

    This function avoids using raw secrets (Authorization header or full
    api key) directly as principals to prevent cross-user cache replay.
    """
    # If another middleware already resolved an authenticated principal, use it
    existing = getattr(request.state, "principal", None)
    if existing:
        return existing

    # 1) Try Authorization Bearer token and validate it
    auth_header = request.headers.get("authorization")
    if auth_header and auth_header.lower().startswith("bearer "):
        token = auth_header.split(None, 1)[1].strip()
        try:
            payload = verify_token(token)
            if payload:
                sub = payload.get("sub") or payload.get("user_id")
                if sub:
                    principal = f"user:{int(sub)}"
                    request.state.principal = principal
                    return principal
        except Exception:
            # Treat as unauthenticated if token invalid
            pass

    # 2) Try X-API-Key header but only store key_id, not secret
    api_key_hdr = request.headers.get("x-api-key")
    if api_key_hdr and "." in api_key_hdr:
        key_id, secret = api_key_hdr.split(".", 1)
        try:
            db: Session = SessionLocal()
            try:
                key_record = db.query(APIKey).filter(APIKey.key_id == key_id).first()
                if key_record and key_record.is_valid() and verify_api_key(secret, key_record.key_salt, key_record.key_hash):
                    # If API key is linked to a user, prefer that user identity
                    if getattr(key_record, "user_id", None):
                        principal = f"user:{int(key_record.user_id)}"
                    else:
                        principal = f"api_key:{key_id}"
                    request.state.principal = principal
                    return principal
            finally:
                db.close()
        except Exception:
            pass

    # 3) Do not trust X-User-Id header directly. Only use as last resort if present and matches authenticated state (not available here)

    # 4) Fallback anonymous fingerprint using IP + User-Agent
    ip = request.client.host if request.client is not None else "unknown"
    ua = request.headers.get("user-agent", "")
    fp = sha256(f"{ip}|{ua}".encode()).hexdigest()
    principal = f"anonymous:{fp}"
    request.state.principal = principal
    return principal


def _idempotency_exempt_path(path: str) -> bool:
    return path in SKIP_PATHS or path in {"/openapi.json", "/docs", "/redoc"}


def _response_headers_for_cache(response: Response) -> dict:
    headers = {}
    for key, value in response.headers.items():
        lower_key = key.lower()
        if lower_key in {"content-length", "transfer-encoding", "connection", "date", "server"}:
            continue
        headers[key] = value
    return headers


async def idempotency_middleware(request: Request, call_next: Callable):
    """Replay successful write responses when the client retries with the same key."""

    if request.method.upper() not in IDEMPOTENT_METHODS or _idempotency_exempt_path(request.url.path):
        return await call_next(request)

    idempotency_key = request.headers.get("Idempotency-Key")
    if not idempotency_key:
        return JSONResponse(
            status_code=status.HTTP_428_PRECONDITION_REQUIRED,
            content={
                "error_code": "IDEMPOTENCY_KEY_REQUIRED",
                "message": "Idempotency-Key header is required for write operations.",
            },
        )

    body = await request.body()
    body_fingerprint = hashlib.sha256(body or b"").hexdigest()
    key = http_idempotency_manager.build_http_key(
        method=request.method,
        path=request.url.path,
        idempotency_key=idempotency_key,
        principal=_request_principal(request),
        body=body,
    )

    cached = http_idempotency_manager.get_http_response(key)
    if cached:
        if cached.get("request_fingerprint") and cached["request_fingerprint"] != body_fingerprint:
            return JSONResponse(
                status_code=status.HTTP_409_CONFLICT,
                content={
                    "error_code": "IDEMPOTENCY_KEY_REUSED",
                    "message": "This Idempotency-Key was already used with a different request body.",
                },
            )
        return Response(
            content=cached["body"],
            status_code=cached["status_code"],
            headers={**cached["headers"], "X-Idempotent-Replay": "true"},
            media_type=cached.get("media_type") or cached["headers"].get("content-type"),
        )

    if not http_idempotency_manager.acquire_http(key, ttl=86400):
        cached = http_idempotency_manager.get_http_response(key)
        if cached:
            return Response(
                content=cached["body"],
                status_code=cached["status_code"],
                headers={**cached["headers"], "X-Idempotent-Replay": "true"},
                media_type=cached.get("media_type") or cached["headers"].get("content-type"),
            )
        return JSONResponse(
            status_code=status.HTTP_409_CONFLICT,
            content={
                "error_code": "IDEMPOTENCY_IN_PROGRESS",
                "message": "A request with this idempotency key is already in progress.",
            },
        )

    response = await call_next(request)

    response_body = b""
    async for chunk in response.body_iterator:
        response_body += chunk

    headers = _response_headers_for_cache(response)
    cache_payload = {
        "status_code": response.status_code,
        "headers": headers,
        "body": response_body,
        "media_type": response.media_type or headers.get("content-type"),
        "request_fingerprint": body_fingerprint,
    }

    if response.status_code < 400:
        http_idempotency_manager.store_http_response(key, cache_payload, ttl=86400)
    else:
        http_idempotency_manager.release_http_lock(key)

    return Response(
        content=response_body,
        status_code=response.status_code,
        headers=headers,
        media_type=response.media_type or headers.get("content-type"),
    )


async def rate_limit_middleware(request: Request, call_next: Callable):
    """Apply global and endpoint-specific Redis sliding-window throttling."""

    if not settings.RATE_LIMIT_ENABLED:
        return await call_next(request)

    path = request.url.path
    if path in SKIP_PATHS:
        return await call_next(request)

    identifier = resolve_rate_limit_identifier(request)
    request.state.rate_limit_identifier = identifier
    request.state.user_id = identifier

    if is_whitelisted(identifier):
        response = await call_next(request)
        response.headers["X-RateLimit-Scope"] = "whitelist"
        return response

    rule, matched_override = get_rate_limit_policy(path, request.method)
    allowed = await limiter.check_rate_limit(
        identifier=identifier,
        endpoint=f"{request.method.upper()} {path}",
        limit=rule.requests,
        window_seconds=rule.window,
        request_id=getattr(request.state, "request_id", None),
    )

    if not allowed:
        retry_after = await limiter.get_remaining_ttl(identifier, f"{request.method.upper()} {path}", rule.window)
        logger.warning(
            "rate_limit_exceeded",
            identifier=identifier,
            path=path,
            method=request.method,
            limit=rule.requests,
            window_seconds=rule.window,
            retry_after=retry_after,
        )
        return build_rate_limit_response(
            retry_after=retry_after,
            message=f"Rate limit exceeded. Limit is {rule.requests} requests per {rule.window} seconds.",
        )

    response = await call_next(request)
    response.headers["X-RateLimit-Limit"] = str(rule.requests)
    response.headers["X-RateLimit-Window"] = str(rule.window)
    response.headers["X-RateLimit-Scope"] = "endpoint" if matched_override else "global"
    return response


async def add_correlation_id_middleware(request: Request, call_next: Callable):
    """Attach correlation and request IDs to the request context."""

    correlation_id = request.headers.get("X-Correlation-Id") or generate_correlation_id()
    request.state.correlation_id = correlation_id
    request.state.request_id = correlation_id
    request.state.user_id = getattr(request.state, "rate_limit_identifier", request.headers.get("X-User-Id", "anonymous"))

    response = await call_next(request)
    response.headers["X-Correlation-Id"] = correlation_id
    response.headers["X-Request-Id"] = correlation_id
    return response


async def error_handling_middleware(request: Request, call_next: Callable):
    """Convert uncaught exceptions into a structured JSON 500 response."""

    try:
        return await call_next(request)
    except HTTPException:
        raise
    except Exception as exc:
        logger.error(
            "unhandled_error",
            path=request.url.path,
            method=request.method,
            error=str(exc),
        )
        record_api_error(request.url.path, exc)
        capture_exception(exc, path=request.url.path, method=request.method)
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={
                "error_code": "INTERNAL_SERVER_ERROR",
                "message": "An internal error occurred",
            },
        )


async def logging_middleware(request: Request, call_next: Callable):
    """Log request metadata and emit tracing/metrics events."""

    start_time = time.time()
    endpoint = request.url.path
    request_id = getattr(request.state, "request_id", request.headers.get("X-Correlation-Id") or generate_correlation_id())
    user_id = getattr(request.state, "user_id", request.headers.get("X-User-Id", "anonymous"))

    bind_request_context(request_id=request_id, user_id=user_id)

    response = None
    error_occurred = False

    try:
        with traced_operation(
            f"http {request.method} {endpoint}",
            {
                "http.method": request.method,
                "http.target": endpoint,
                "request.id": request_id,
                "user.id": user_id,
            },
        ):
            try:
                response = await call_next(request)
            except Exception as exc:
                error_occurred = True
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

        process_time = time.time() - start_time

        if not error_occurred and response:
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

    finally:
        clear_request_context()

    return response


def _request_size_limit_for_path(path: str) -> int:
    if any(path.startswith(prefix) for prefix in UPLOAD_PATH_PREFIXES):
        return ValidationConfig.MAX_UPLOAD_SIZE
    if any(path.startswith(prefix) for prefix in ANALYTICS_PATH_PREFIXES):
        return ValidationConfig.MAX_ANALYTICS_PAYLOAD
    return ValidationConfig.MAX_JSON_BODY


async def request_size_limit_middleware(request: Request, call_next: Callable):
    """Reject oversized requests before they reach the application layer."""

    if request.url.path in SKIP_PATHS:
        return await call_next(request)

    transfer_encoding = request.headers.get("transfer-encoding", "").lower()
    if "chunked" in transfer_encoding:
        return JSONResponse(
            status_code=status.HTTP_411_LENGTH_REQUIRED,
            content={
                "error_code": "CHUNKED_ENCODING_NOT_SUPPORTED",
                "message": "Chunked transfer encoding is not supported. Provide Content-Length header.",
            },
        )

    content_length = request.headers.get("content-length")
    if content_length is not None:
        try:
            content_length_bytes = int(content_length)
        except (TypeError, ValueError):
            content_length_bytes = None

        if content_length_bytes is not None:
            max_size = _request_size_limit_for_path(request.url.path)
            if content_length_bytes > max_size:
                logger.warning(
                    "request_size_limit_exceeded",
                    path=request.url.path,
                    content_length=content_length_bytes,
                    max_size=max_size,
                    size_mb=round(content_length_bytes / 1024 / 1024, 2),
                )
                return JSONResponse(
                    status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                    content={
                        "error_code": "PAYLOAD_TOO_LARGE",
                        "message": (
                            f"Request body too large: {round(content_length_bytes / 1024 / 1024, 2)} MB "
                            f"(max {round(max_size / 1024 / 1024, 2)} MB)"
                        ),
                    },
                )

    try:
        return await call_next(request)
    except PayloadTooLargeError as exc:
        return JSONResponse(
            status_code=exc.status_code,
            content={
                "error_code": "PAYLOAD_TOO_LARGE",
                "message": str(exc.detail),
            },
        )

