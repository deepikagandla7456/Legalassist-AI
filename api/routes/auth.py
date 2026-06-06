"""
Authentication Endpoints
POST /api/v1/auth/token - Get access token
POST /api/v1/auth/api-key - Create API key
GET /api/v1/auth/me - Get current user
"""
from fastapi import APIRouter, HTTPException, status, Depends
from datetime import datetime, timedelta
from api.auth import create_access_token, generate_api_key, hash_api_key, CurrentUser, get_current_user, revoke_jwt_token
from api.models import TokenResponse, APIKeyCreate, APIKeyResponse
from fastapi import Request
import structlog

router = APIRouter(prefix="/api/v1/auth", tags=["auth"])
logger = structlog.get_logger(__name__)


@router.post(
    "/token",
    response_model=TokenResponse,
    summary="Get access token"
)
async def get_token(
    username: str,
    password: str
) -> TokenResponse:
    """
    Authenticate user and get access token
    
    - **username**: User email or username
    - **password**: User password
    
    Returns JWT token valid for 24 hours
    """
    
    # In production, validate against database
    logger.info("Token request", username=username)
    
    token = create_access_token({"sub": "user123", "email": username, "role": "user"})
    
    return TokenResponse(
        access_token=token,
        token_type="bearer",
        expires_in=24 * 3600  # 24 hours in seconds
    )


@router.post(
    "/api-keys",
    response_model=APIKeyResponse,
    summary="Create API key"
)
async def create_api_key(
    request: APIKeyCreate,
    current_user: CurrentUser = Depends(get_current_user)
) -> APIKeyResponse:
    """
    Create new API key for programmatic access
    
    - **name**: Name for the API key
    - **expires_in_days**: Optional expiration (1-365 days)
    
    Returns API key (only shown on creation - save it!)
    """
    
    logger.info(
        "Creating API key",
        user_id=current_user.user_id,
        key_name=request.name
    )
    
    key = generate_api_key()
    key_hash = hash_api_key(key)
    expires_at = None
    
    if request.expires_in_days:
        expires_at = datetime.utcnow() + timedelta(days=request.expires_in_days)
    
    return APIKeyResponse(
        id="key_123",
        name=request.name,
        key=key,  # Only shown now
        created_at=datetime.utcnow(),
        expires_at=expires_at
    )


@router.get(
    "/api-keys",
    summary="List API keys"
)
async def list_api_keys(
    current_user: CurrentUser = Depends(get_current_user)
) -> dict:
    """List all API keys for current user"""
    
    logger.info("Listing API keys", user_id=current_user.user_id)
    
    return {
        "user_id": current_user.user_id,
        "keys": [
            {
                "id": "key_123",
                "name": "Production API Key",
                "created_at": datetime.utcnow().isoformat(),
                "expires_at": None,
                "last_used": None
            }
        ]
    }


@router.delete(
    "/api-keys/{key_id}",
    summary="Delete API key"
)
async def delete_api_key(
    key_id: str,
    current_user: CurrentUser = Depends(get_current_user)
) -> dict:
    """Delete an API key"""
    
    logger.info(
        "Deleting API key",
        user_id=current_user.user_id,
        key_id=key_id
    )
    
    return {"status": "deleted", "key_id": key_id}


@router.get(
    "/me",
    summary="Get current user info"
)
async def get_current_user_info(
    current_user: CurrentUser = Depends(get_current_user)
) -> dict:
    """Get information about current user"""
    
    return {
        "user_id": current_user.user_id,
        "email": current_user.email,
        "role": current_user.role,
        "subscription_tier": "pro"
    }


@router.post(
    "/logout",
    summary="Logout and revoke current JWT token"
)
async def logout(
    request: Request,
    current_user: CurrentUser = Depends(get_current_user),
) -> dict:
    """Revoke the current JWT token.

    Requires the user to be authenticated. Extracts the token from the
    Authorization header, validates that its subject matches the requesting
    user, and blacklists it so it can no longer be used.
    """
    auth = request.headers.get("Authorization") or request.headers.get("authorization")
    token = None
    if auth and auth.lower().startswith("bearer "):
        token = auth.split(None, 1)[1].strip()

    if not token:
        return {"status": "ok", "revoked": False, "detail": "No token to revoke"}

    revoke_jwt_token(token, int(current_user.user_id))
    return {"status": "ok", "revoked": True}
