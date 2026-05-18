"""Read-only case aggregation helpers."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

from db.models import Attachment, Case, CaseDeadline, CaseDocument, CaseTimeline
from .timeline_service import timeline_service


def get_user_cases_summary(db: Session, user_id: int, include_closed: bool = True) -> List[Dict[str, Any]]:
    cases = db.query(Case).filter(Case.user_id == user_id).all()
    if not include_closed:
        cases = [case for case in cases if case.status.value != "closed"]

    summaries = []
    for case in cases:
        latest_doc = db.query(CaseDocument).filter(CaseDocument.case_id == case.id).order_by(CaseDocument.uploaded_at.desc()).first()
        next_deadline = db.query(CaseDeadline).filter(
            CaseDeadline.case_id == case.id,
            CaseDeadline.is_completed == False,
            CaseDeadline.deadline_date > datetime.now(timezone.utc),
        ).order_by(CaseDeadline.deadline_date).first()
        doc_count = db.query(CaseDocument).filter(CaseDocument.case_id == case.id).count()

        summaries.append({
            "id": case.id,
            "case_number": case.case_number,
            "title": case.title or case.case_number,
            "case_type": case.case_type,
            "jurisdiction": case.jurisdiction,
            "status": case.status.value,
            "created_at": case.created_at.isoformat(),
            "latest_document_type": latest_doc.document_type.value if latest_doc else None,
            "latest_document_date": latest_doc.uploaded_at.isoformat() if latest_doc else None,
            "next_deadline_date": next_deadline.deadline_date.isoformat() if next_deadline else None,
            "next_deadline_type": next_deadline.deadline_type if next_deadline else None,
            "days_until_deadline": next_deadline.days_until_deadline() if next_deadline else None,
            "document_count": doc_count,
        })

    return summaries


def get_case_detail(db: Session, user_id: int, case_id: int) -> Optional[Dict[str, Any]]:
    case = db.query(Case).filter(Case.id == case_id).first()
    if not case or case.user_id != user_id:
        return None

    documents = db.query(CaseDocument).filter(CaseDocument.case_id == case_id).all()
    docs_list = [
        {
            "id": doc.id,
            "document_type": doc.document_type.value,
            "uploaded_at": doc.uploaded_at.isoformat(),
            "summary": doc.summary,
            "has_remedies": bool(doc.remedies),
        }
        for doc in documents
    ]

    attachments = db.query(Attachment).filter(Attachment.case_id == case_id).all()
    attachments_list = [
        {
            "id": a.id,
            "original_filename": a.original_filename,
            "uploaded_at": a.uploaded_at.isoformat(),
            "size_bytes": a.size_bytes,
            "content_type": a.content_type,
        }
        for a in attachments
    ]

    deadlines = db.query(CaseDeadline).filter(CaseDeadline.case_id == case_id).order_by(CaseDeadline.deadline_date).all()
    deadlines_list = [
        {
            "id": d.id,
            "deadline_type": d.deadline_type,
            "deadline_date": d.deadline_date.isoformat(),
            "description": d.description,
            "is_completed": d.is_completed,
            "days_until": d.days_until_deadline(),
        }
        for d in deadlines
    ]

    latest_doc = documents[-1] if documents else None
    remedies = latest_doc.remedies if latest_doc else None

    timeline_list = timeline_service.get_case_timeline_events(db, case_id)

    return {
        "case": {
            "id": case.id,
            "case_number": case.case_number,
            "title": case.title,
            "case_type": case.case_type,
            "jurisdiction": case.jurisdiction,
            "status": case.status.value,
            "created_at": case.created_at.isoformat(),
        },
        "documents": docs_list,
        "deadlines": deadlines_list,
        "remedies": remedies,
        "attachments": attachments_list,
        "timeline": timeline_list,
    }


def generate_case_summary_text(db: Session, user_id: int, case_id: int) -> Optional[str]:
    case = db.query(Case).filter(Case.id == case_id).first()
    if not case or case.user_id != user_id:
        return None

    documents = db.query(CaseDocument).filter(CaseDocument.case_id == case_id).all()
    timeline = db.query(CaseTimeline).filter(CaseTimeline.case_id == case_id).all()
    deadlines = db.query(CaseDeadline).filter(CaseDeadline.case_id == case_id).order_by(CaseDeadline.deadline_date).all()

    lines = [
        "=" * 60,
        f"CASE SUMMARY: {case.case_number}",
        "=" * 60,
        "",
        f"Title: {case.title or 'N/A'}",
        f"Type: {case.case_type}",
        f"Jurisdiction: {case.jurisdiction}",
        f"Status: {case.status.value}",
        f"Created: {case.created_at.strftime('%d %B %Y')}",
        "",
        "-" * 60,
        "DOCUMENTS",
        "-" * 60,
    ]

    for doc in documents:
        lines.append(f"\n[{doc.document_type.value}] - {doc.uploaded_at.strftime('%d %B %Y')}")
        if doc.summary:
            lines.append(f"Summary: {doc.summary}")

    lines.extend(["", "-" * 60, "TIMELINE", "-" * 60])
    for event in timeline:
        lines.append(f"[{event.event_date.strftime('%d %B %Y')}] {event.event_type}: {event.description}")

    lines.extend(["", "-" * 60, "DEADLINES", "-" * 60])
    for d in deadlines:
        status = "✓" if d.is_completed else "○"
        lines.append(f"[{status}] {d.deadline_type}: {d.deadline_date.strftime('%d %B %Y')} - {d.description or 'No description'}")

    lines.extend([
        "",
        "=" * 60,
        f"Generated: {datetime.now(timezone.utc).strftime('%d %B %Y %H:%M')}",
        "=" * 60,
    ])

    return "\n".join(lines)
