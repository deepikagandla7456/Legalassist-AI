"""CRUD operations for token management."""

import datetime as dt
import threading

from sqlalchemy.orm import Session

from db.models import RevokedToken


_revocation_cache = None
_revocation_cache_lock = threading.Lock()


def _get_revocation_cache():
    """Get the Redis revocation cache if available."""
    global _revocation_cache
    if _revocation_cache is not None:
        return _revocation_cache
    
    with _revocation_cache_lock:
        if _revocation_cache is None:
            try:
                import redis
                from config import Config
                redis_url = getattr(Config, "REDIS_URL", "redis://localhost:6379/0")
                _revocation_cache = redis.from_url(redis_url, decode_responses=True)
            except Exception:
                return None
    return _revocation_cache


def _is_token_revoked_uncached(db: Session, jti: str) -> bool:
    """Check if token JTI is revoked (no cache)."""
    return db.query(RevokedToken).filter(RevokedToken.jti == jti).first() is not None


def is_token_revoked(db: Session, jti: str) -> bool:
    """Check if token JTI is revoked, using Redis coordinated cache."""
    cache = _get_revocation_cache()
    if cache is None:
        return _is_token_revoked_uncached(db, jti)

    cache_key = f"revoked:{jti}"
    cached = cache.get(cache_key)
    if cached is not None:
        return cached == "1"

    lock_key = f"{cache_key}:lock"
    lock_value = str(dt.datetime.now(dt.timezone.utc).timestamp())

    if cache.set(lock_key, lock_value, nx=True, ex=10):
        try:
            revoked = _is_token_revoked_uncached(db, jti)
            ttl = 3600 if revoked else 300
            cache.setex(cache_key, ttl, "1" if revoked else "0")
            return revoked
        finally:
            if cache.get(lock_key) == lock_value:
                cache.delete(lock_key)

    # Wait for other process to populate cache
    for _ in range(50):
        import time
        time.sleep(0.02)
        cached = cache.get(cache_key)
        if cached is not None:
            return cached == "1"

    return _is_token_revoked_uncached(db, jti)


def revoke_token(db: Session, jti: str, expires_at: dt.datetime) -> RevokedToken:
    """Add a token JTI to the revocation blacklist."""
    token = RevokedToken(jti=jti, expires_at=expires_at)
    db.add(token)
    db.commit()
    db.refresh(token)
    return token


def cleanup_expired_revoked_tokens(db: Session) -> int:
    """Remove expired tokens from the blacklist."""
    now = dt.datetime.now(dt.timezone.utc)
    deleted = db.query(RevokedToken).filter(RevokedToken.expires_at < now).delete(synchronize_session=False)
    db.commit()
    return deleted