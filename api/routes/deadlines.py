"""
Deadline Endpoints
GET /api/v1/deadlines/upcoming - Get user's upcoming deadlines
GET /api/v1/deadlines/{deadline_id} - Get deadline details
POST /api/v1/deadlines - Create new deadline
PUT /api/v1/deadlines/{deadline_id} - Update deadline
"""
from fastapi import APIRouter, HTTPException, status, Depends, Query
from api.models import DeadlineResponse, UpcomingDeadlinesResponse
from api.auth import get_current_user, CurrentUser
import structlog
from datetime import datetime, timezone, timedelta
from database import get_db, CaseDeadline

router = APIRouter(prefix="/api/v1/deadlines", tags=["deadlines"])
logger = structlog.get_logger(__name__)


def _derive_priority(days_until: int) -> str:
    if days_until <= 3:
        return "critical"
    if days_until <= 7:
        return "high"
    if days_until <= 14:
        return "medium"
    return "low"


def _compute_status(is_completed: bool, due_date: datetime) -> str:
    if is_completed:
        return "completed"
    if due_date < datetime.now(timezone.utc):
        return "overdue"
    return "pending"


def _deadline_to_response(d: CaseDeadline) -> DeadlineResponse:
    now = datetime.now(timezone.utc)
    due = d.deadline_date
    days_until = (due - now).days
    return DeadlineResponse(
        deadline_id=str(d.id),
        user_id=str(d.user_id),
        case_id=str(d.case_id) if d.case_id else None,
        title=d.case_title,
        description=d.description or f"{d.deadline_type} deadline",
        due_date=due,
        days_until_due=days_until,
        priority=_derive_priority(days_until),
        status=_compute_status(d.is_completed, due),
        reminder_enabled=True,
        reminder_days=7,
        created_at=d.created_at,
    )


@router.get(
    "/upcoming",
    response_model=UpcomingDeadlinesResponse,
    summary="Get user's upcoming deadlines"
)
async def get_upcoming_deadlines(
    days: int = Query(30, ge=1, le=365, description="Look-ahead window in days (max 365)"),
    current_user: CurrentUser = Depends(get_current_user)
) -> UpcomingDeadlinesResponse:
    logger.info(
        "Fetching upcoming deadlines",
        user_id=current_user.user_id,
        days=days,
        limit=limit,
        offset=offset,
    )

    db = None
    try:
        db = get_db()
        now = datetime.now(timezone.utc)
        look_ahead = now + timedelta(days=days)

        query = db.query(CaseDeadline).filter(
            CaseDeadline.user_id == int(current_user.user_id),
            CaseDeadline.deadline_date >= now,
            CaseDeadline.deadline_date <= look_ahead,
        ).order_by(CaseDeadline.deadline_date.asc())

        rows = query.all()

        deadlines = [_deadline_to_response(r) for r in rows]

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
            generated_at=datetime.now(timezone.utc),
        )
    finally:
        if db:
            db.close()


@router.get(
    "/{deadline_id}",
    response_model=DeadlineResponse,
    summary="Get deadline details"
)
async def get_deadline_details(
    deadline_id: str,
    current_user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db_rls),
) -> DeadlineResponse:
    logger.info(
        "Fetching deadline",
        deadline_id=deadline_id,
        user_id=current_user.user_id
    )

    db = None
    try:
        db = get_db()
        deadline = db.query(CaseDeadline).filter(
            CaseDeadline.id == int(deadline_id),
            CaseDeadline.user_id == int(current_user.user_id),
        ).first()

        if not deadline:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Deadline not found"
            )

        return _deadline_to_response(deadline)
    finally:
        if db:
            db.close()


@router.post(
    "",
    response_model=DeadlineResponse,
    summary="Create new deadline"
)
async def create_deadline(
    case_id: int,
    title: str,
    due_date: datetime,
    description: str = "",
    deadline_type: str = "filing",
    priority: str = "medium",
    reminder_enabled: bool = True,
    reminder_days: int = 7,
    current_user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> DeadlineResponse:
    logger.info(
        "Creating deadline",
        user_id=current_user.user_id,
        title=request.title
    )
    
    now = datetime.now(timezone.utc)
    if due_date.tzinfo is None:
        due_date = due_date.replace(tzinfo=timezone.utc)
    if due_date < now:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Deadline date must be in the future"
        )
    days_until = (due_date - now).days
    
    return DeadlineResponse(
        deadline_id=str(deadline_id),
        user_id=str(current_user.user_id),
        case_id=str(case["id"]),
        title=title,
        description=description,
        due_date=normalized_due_date,
        days_until_due=days_until,
        priority=_deadline_priority(days_until),
        status="active",
        reminder_enabled=True,
        reminder_days=request.reminder_days,
        created_at=now
    )


@router.put(
    "/{deadline_id}",
    response_model=DeadlineResponse,
    summary="Update deadline"
)
async def update_deadline(
    deadline_id: int,
    title: str = None,
    due_date: datetime = None,
    deadline_type: str = None,
    priority: str = None,
    description: str = None,
    current_user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> DeadlineResponse:
    logger.info(
        "Updating deadline",
        deadline_id=deadline_id,
        user_id=current_user.user_id
    )
    
    # In production, fetch and update from database
    now = datetime.now(timezone.utc)
    if due_date is not None:
        if due_date.tzinfo is None:
            due_date = due_date.replace(tzinfo=timezone.utc)
        if due_date < now:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Deadline date must be in the future"
            )
    return DeadlineResponse(
        deadline_id=str(updated_deadline.id),
        user_id=str(updated_deadline.user_id),
        case_id=str(updated_deadline.case_id),
        title=updated_deadline.case_title,
        description=updated_deadline.description or "",
        due_date=due_date or now,
        days_until_due=days_until,
        priority=_deadline_priority(days_until),
        status=updated_deadline.status,
        reminder_enabled=True,
        reminder_days=7,
        created_at=updated_deadline.created_at
    )

    db = None
    try:
        updated_deadline = transition_deadline(
            db=db,
            deadline_id=int(deadline_id),
            target_status="active",
            actor_user_id=current_user.user_id
        )
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )
        
    now = datetime.now(timezone.utc)
    due_date = _normalize_utc_datetime(updated_deadline.deadline_date)
    days_until = _days_until_due(due_date, now)
    
    return DeadlineResponse(
        deadline_id=str(updated_deadline.id),
        user_id=str(updated_deadline.user_id),
        case_id=str(updated_deadline.case_id),
        title=updated_deadline.case_title,
        description=updated_deadline.description or "",
        due_date=due_date or now,
        days_until_due=days_until,
        priority=_deadline_priority(days_until),
        status=updated_deadline.status,
        reminder_enabled=True,
        reminder_days=7,
        created_at=updated_deadline.created_at
    )


        if not deadline:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Deadline not found"
            )

        if title is not None:
            deadline.case_title = title
        if due_date is not None:
            deadline.deadline_date = due_date
        deadline.updated_at = datetime.now(timezone.utc)
        db.commit()
        db.refresh(deadline)

        return _deadline_to_response(deadline)
    except Exception:
        if db:
            db.rollback()
        raise
    finally:
        if db:
            db.close()
