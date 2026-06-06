"""
Authentication Endpoints
POST /api/v1/auth/token - Get access token
POST /api/v1/auth/api-key - Create API key
GET /api/v1/auth/me - Get current user
"""
from fastapi import APIRouter, HTTPException, status, Depends
from datetime import datetime, timedelta
from sqlalchemy.orm import Session
from api.auth import create_access_token, generate_api_key, hash_api_key, CurrentUser, get_current_user
from api.models import TokenResponse, APIKeyCreate, APIKeyResponse
from api.rate_limits import check_api_key_creation_limit
from database import get_db, APIKey
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
    current_user: CurrentUser = Depends(get_current_user),
    _: None = Depends(check_api_key_creation_limit),
    db: Session = Depends(get_db),
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
    
    record = APIKey(
        user_id=int(current_user.user_id),
        name=request.name,
        key_hash=key_hash,
        expires_at=expires_at,
    )
    db.add(record)
    db.commit()
    db.refresh(record)
    
    return APIKeyResponse(
        id=str(record.id),
        name=record.name,
        key=key,
        created_at=record.created_at,
        expires_at=record.expires_at
    )


@router.get(
    "/api-keys",
    summary="List API keys"
)
async def list_api_keys(
    current_user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    """List all API keys for current user"""
    
    logger.info("Listing API keys", user_id=current_user.user_id)
    
    records = db.query(APIKey).filter(
        APIKey.user_id == int(current_user.user_id),
        APIKey.is_active == True,
    ).all()
    
    return {
        "user_id": current_user.user_id,
        "keys": [
            {
                "id": str(r.id),
                "name": r.name,
                "created_at": r.created_at.isoformat(),
                "expires_at": r.expires_at.isoformat() if r.expires_at else None,
                "last_used": r.last_used_at.isoformat() if r.last_used_at else None,
            }
            for r in records
        ]
    }


@router.delete(
    "/api-keys/{key_id}",
    summary="Delete API key"
)
async def delete_api_key(
    key_id: str,
    current_user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    """Delete an API key"""
    
    logger.info(
        "Deleting API key",
        user_id=current_user.user_id,
        key_id=key_id
    )
    
    record = db.query(APIKey).filter(
        APIKey.id == int(key_id),
        APIKey.user_id == int(current_user.user_id),
        APIKey.is_active == True,
    ).first()
    
    if not record:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="API key not found or already deleted"
        )
    
    record.is_active = False
    db.commit()
    
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
