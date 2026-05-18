"""Natural-language deadline parsing and automatic deadline creation."""

from __future__ import annotations

import datetime as dt
import re
from typing import Dict, Optional

from sqlalchemy.orm import Session

from db.models import CaseDeadline
from .timeline_service import timeline_service


def _extract_days_from_text(text: str) -> Optional[int]:
    if not text or not isinstance(text, str):
        return None

    text = text.strip()

    if text.isdigit():
        return int(text)

    primary_match = re.search(r"(\d+)\s*days?\b", text, re.IGNORECASE)
    if primary_match:
        return int(primary_match.group(1))

    fallback_match = re.search(r"(?:in|within|after)\s+(\d+)\s*days?", text, re.IGNORECASE)
    if fallback_match:
        return int(fallback_match.group(1))

    return None


def _validate_days_value(days: int) -> bool:
    return 1 <= days <= 365


def auto_create_deadlines_from_remedies(
    db: Session,
    user_id: int,
    case_id: int,
    case_title: str,
    remedies: Dict,
    document_id: int,
) -> None:
    appeal_days = remedies.get("appeal_days")
    if not appeal_days:
        return

    appeal_days_str = str(appeal_days).strip()
    days = _extract_days_from_text(appeal_days_str)
    if days is None or not _validate_days_value(days):
        return

    current_time = dt.datetime.now(dt.timezone.utc)
    deadline_date = current_time + dt.timedelta(days=days)

    existing_deadline = db.query(CaseDeadline).filter(
        CaseDeadline.case_id == case_id,
        CaseDeadline.deadline_type == "appeal",
        CaseDeadline.is_completed == False,
        CaseDeadline.deadline_date >= deadline_date - dt.timedelta(days=1),
        CaseDeadline.deadline_date <= deadline_date + dt.timedelta(days=1),
    ).first()

    if existing_deadline:
        return

    deadline = CaseDeadline(
        user_id=user_id,
        case_id=case_id,
        case_title=case_title,
        deadline_date=deadline_date,
        deadline_type="appeal",
        description=f"Appeal deadline - {remedies.get('appeal_court', 'Unknown court')}",
    )
    db.add(deadline)
    db.flush()

    timeline_service.create_event(
        db=db,
        case_id=case_id,
        event_type="deadline_created",
        description=f"Appeal deadline set for {deadline_date.strftime('%d %B %Y')} based on document analysis",
        metadata={
            "deadline_id": deadline.id,
            "document_id": document_id,
            "source_days": days,
            "original_text": appeal_days_str,
        },
    )
