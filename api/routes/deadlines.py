"""
Deadline Endpoints
GET /api/v1/deadlines/upcoming - Get user's upcoming deadlines
GET /api/v1/deadlines/{deadline_id} - Get deadline details
POST /api/v1/deadlines - Create new deadline
"""
from fastapi import APIRouter, HTTPException, status, Depends
from api.models import DeadlineResponse, UpcomingDeadlinesResponse
from api.auth import get_current_user, CurrentUser
import structlog
from datetime import datetime, timedelta, timezone
from database import get_db, UserPreference

router = APIRouter(prefix="/api/v1/deadlines", tags=["deadlines"])
logger = structlog.get_logger(__name__)


def _load_reminder_settings(user_id: str) -> tuple:
    """Load reminder settings from user preferences. Returns (enabled, days)."""
    db = None
    try:
        db = get_db()
        pref = db.query(UserPreference).filter(
            UserPreference.user_id == int(user_id)
        ).first()
        if pref:
            enabled = pref.notify_1_day or pref.notify_3_days or pref.notify_10_days or pref.notify_30_days
            if pref.notify_1_day:
                days = 1
            elif pref.notify_3_days:
                days = 3
            elif pref.notify_10_days:
                days = 10
            elif pref.notify_30_days:
                days = 30
            else:
                days = 7
            return (enabled, days)
        return (True, 7)
    finally:
        if db:
            db.close()


@router.get(
    "/upcoming",
    response_model=UpcomingDeadlinesResponse,
    summary="Get user's upcoming deadlines"
)
async def get_upcoming_deadlines(
    days: int = 30,
    current_user: CurrentUser = Depends(get_current_user)
) -> UpcomingDeadlinesResponse:
    """
    Get upcoming deadlines for user
    
    - **days**: Look ahead N days (default 30)
    
    Returns sorted list of upcoming deadlines by urgency
    """
    
    logger.info(
        "Fetching upcoming deadlines",
        user_id=current_user.user_id,
        days=days
    )
    
    reminder_enabled, reminder_days = _load_reminder_settings(current_user.user_id)

    now = datetime.now(timezone.utc)
    deadlines = [
        DeadlineResponse(
            deadline_id="dl_001",
            user_id=current_user.user_id,
            case_id="case_001",
            title="Motion Response Due",
            description="Response to plaintiff's motion for summary judgment",
            due_date=now + timedelta(days=3),
            days_until_due=3,
            priority="critical",
            status="pending",
            reminder_enabled=reminder_enabled,
            reminder_days=reminder_days,
            created_at=now
        ),
        DeadlineResponse(
            deadline_id="dl_002",
            user_id=current_user.user_id,
            case_id="case_002",
            title="Filing Deadline",
            description="Appeal filing deadline",
            due_date=now + timedelta(days=10),
            days_until_due=10,
            priority="high",
            status="pending",
            reminder_enabled=reminder_enabled,
            reminder_days=reminder_days,
            created_at=now
        ),
        DeadlineResponse(
            deadline_id="dl_003",
            user_id=current_user.user_id,
            case_id="case_003",
            title="Document Production",
            description="Produce documents per discovery order",
            due_date=now + timedelta(days=21),
            days_until_due=21,
            priority="medium",
            status="pending",
            reminder_enabled=reminder_enabled,
            reminder_days=reminder_days,
            created_at=now
        ),
    ]
    
    critical = sum(1 for d in deadlines if d.priority == "critical")
    high = sum(1 for d in deadlines if d.priority == "high")
    medium = sum(1 for d in deadlines if d.priority == "medium")
    low = sum(1 for d in deadlines if d.priority == "low")
    
    return UpcomingDeadlinesResponse(
        user_id=current_user.user_id,
        total_deadlines=len(deadlines),
        critical_count=critical,
        high_count=high,
        medium_count=medium,
        low_count=low,
        deadlines=deadlines,
        generated_at=datetime.now(timezone.utc)
    )


@router.get(
    "/{deadline_id}",
    response_model=DeadlineResponse,
    summary="Get deadline details"
)
async def get_deadline_details(
    deadline_id: str,
    current_user: CurrentUser = Depends(get_current_user)
) -> DeadlineResponse:
    """Get complete deadline details"""
    
    logger.info(
        "Fetching deadline",
        deadline_id=deadline_id,
        user_id=current_user.user_id
    )
    
    reminder_enabled, reminder_days = _load_reminder_settings(current_user.user_id)
    now = datetime.now(timezone.utc)
    return DeadlineResponse(
        deadline_id=deadline_id,
        user_id=current_user.user_id,
        case_id="case_001",
        title="Example Deadline",
        description="Example deadline description",
        due_date=now + timedelta(days=5),
        days_until_due=5,
        priority="high",
        status="pending",
        reminder_enabled=reminder_enabled,
        reminder_days=reminder_days,
        created_at=now
    )


@router.post(
    "",
    response_model=DeadlineResponse,
    summary="Create new deadline"
)
async def create_deadline(
    title: str,
    due_date: datetime,
    description: str = "",
    priority: str = "medium",
    case_id: str = None,
    reminder_days: int = 7,
    current_user: CurrentUser = Depends(get_current_user)
) -> DeadlineResponse:
    """Create a new deadline"""
    
    logger.info(
        "Creating deadline",
        user_id=current_user.user_id,
        title=title
    )
    
    reminder_enabled, pref_reminder_days = _load_reminder_settings(current_user.user_id)
    now = datetime.now(timezone.utc)
    days_until = (due_date - now).days
    
    return DeadlineResponse(
        deadline_id="dl_new",
        user_id=current_user.user_id,
        case_id=case_id,
        title=title,
        description=description,
        due_date=due_date,
        days_until_due=days_until,
        priority=priority,
        status="pending",
        reminder_enabled=reminder_enabled,
        reminder_days=pref_reminder_days,
        created_at=now
    )


@router.put(
    "/{deadline_id}",
    response_model=DeadlineResponse,
    summary="Update deadline"
)
async def update_deadline(
    deadline_id: str,
    title: str = None,
    due_date: datetime = None,
    priority: str = None,
    current_user: CurrentUser = Depends(get_current_user)
) -> DeadlineResponse:
    """Update a deadline"""
    
    logger.info(
        "Updating deadline",
        deadline_id=deadline_id,
        user_id=current_user.user_id
    )
    
    reminder_enabled, pref_reminder_days = _load_reminder_settings(current_user.user_id)
    now = datetime.now(timezone.utc)
    return DeadlineResponse(
        deadline_id=deadline_id,
        user_id=current_user.user_id,
        case_id="case_001",
        title=title or "Updated Deadline",
        description="Updated description",
        due_date=due_date or (now + timedelta(days=7)),
        days_until_due=7,
        priority=priority or "medium",
        status="pending",
        reminder_enabled=reminder_enabled,
        reminder_days=pref_reminder_days,
        created_at=now
    )
