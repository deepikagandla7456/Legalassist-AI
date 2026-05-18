"""Anonymized case export helpers."""

from __future__ import annotations

import hashlib
import hmac
import os
from pathlib import Path
from typing import Any, Dict, Optional

from sqlalchemy.orm import Session

from db.session import SessionLocal
from db.models import Case, CaseDocument, CaseTimeline


def _get_case_anonymization_secret() -> str:
    secret = os.getenv("CASE_ANONYMIZATION_SECRET", "").strip()
    if secret:
        return secret

    jwt_secret_path = Path(__file__).resolve().parents[1] / ".jwt_secret"
    if not jwt_secret_path.exists():
        jwt_secret_path = Path(__file__).resolve().parents[2] / ".jwt_secret"

    if jwt_secret_path.exists():
        try:
            file_secret = jwt_secret_path.read_text(encoding="utf-8").strip()
            if file_secret:
                return file_secret
        except Exception:
            pass

    raise RuntimeError("CASE_ANONYMIZATION_SECRET is not configured.")


def _generate_anonymized_case_id(case_id: int, created_at: Any) -> str:
    created_at_str = getattr(created_at, "isoformat", None)
    created_at_str = created_at.isoformat() if callable(created_at_str) else str(created_at)
    secret = _get_case_anonymization_secret().encode("utf-8")
    msg = f"{case_id}-{created_at_str}".encode("utf-8")
    digest = hmac.new(secret, msg, hashlib.sha256).hexdigest()
    return digest[:12]


def generate_anonymized_case_data(case_id: int) -> Optional[Dict[str, Any]]:
    db: Session = SessionLocal()
    try:
        case = db.query(Case).filter(Case.id == case_id).first()
        if not case:
            return None

        documents = db.query(CaseDocument).filter(CaseDocument.case_id == case_id).all()
        timeline = db.query(CaseTimeline).filter(CaseTimeline.case_id == case_id).all()
        anonymized_id = _generate_anonymized_case_id(case_id=case_id, created_at=case.created_at)

        return {
            "anonymized_id": anonymized_id,
            "case_type": case.case_type,
            "jurisdiction": case.jurisdiction,
            "status": case.status.value,
            "document_count": len(documents),
            "documents": [
                {
                    "type": doc.document_type.value,
                    "summary": doc.summary,
                    "remedies": doc.remedies,
                }
                for doc in documents
            ],
            "timeline": [
                {
                    "event_type": e.event_type,
                    "description": e.description,
                }
                for e in timeline
            ],
            "created_date": case.created_at.strftime("%B %Y"),
        }
    finally:
        db.close()
