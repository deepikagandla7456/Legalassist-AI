import sys
from unittest.mock import MagicMock

# Mock heavy/external modules to avoid import errors during test collection
sys.modules["streamlit"] = MagicMock()
sys.modules["pytesseract"] = MagicMock()
sys.modules["pdf2image"] = MagicMock()

import pytest  # noqa: E402
import json  # noqa: E402
from datetime import datetime, timezone  # noqa: E402
from sqlalchemy import create_engine  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402

from database import Base  # noqa: E402
from db.models import (  # noqa: E402
    User,
    Case,
    CaseStatus,
    CaseDeadline,
    NotificationLog,
    NotificationChannel,
    NotificationStatus,
)
from celery_app import export_data_task  # noqa: E402


@pytest.fixture(scope="function")
def test_db():
    """Create an in-memory SQLite database for testing the export task"""
    engine = create_engine(
        "sqlite:///:memory:", connect_args={"check_same_thread": False}
    )
    Base.metadata.create_all(bind=engine)
    TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    db = TestingSessionLocal()

    # Seed user
    user = User(id=1, email="test@example.com")
    db.add(user)
    db.commit()

    yield db
    db.close()


@pytest.fixture(autouse=True)
def patch_db_session(test_db, monkeypatch):
    """Automatically patch db_session context manager to use

    the in-memory SQLite session
    """
    from contextlib import contextmanager

    @contextmanager
    def mock_db_session():
        yield test_db

    monkeypatch.setattr("db.session.db_session", mock_db_session)


@pytest.fixture(autouse=True)
def patch_task_methods(monkeypatch):
    """Disable Celery Redis backend state updates during tests and set mock task ID"""
    monkeypatch.setattr(export_data_task, "update_state", lambda state, meta: None)
    export_data_task.request.id = "mock-task-id-123"


def test_export_unsupported_format():
    """Verify that requesting an unsupported format returns the

    contract-specified null-metadata dictionary
    """
    result = export_data_task._orig_run(user_id="1", format="xml")

    assert result["export_id"] is None
    assert result["file_path"] is None
    assert result["file_size_bytes"] == 0
    assert result["format"] == "xml"
    assert result["expires_in_hours"] is None
    assert result["expires_at"] is None
    assert result["created_at"] is None


def test_export_invalid_user_id():
    """Verify that an invalid user_id yields a clear ValueError"""
    with pytest.raises(ValueError, match="Must be an integer"):
        export_data_task._orig_run(user_id="not_an_int", format="json")


def test_export_empty_data(test_db):
    """Verify that a user with no cases, deadlines, or logs gets

    exported successfully without errors
    """
    result = export_data_task._orig_run(user_id="1", format="json")

    assert result["export_id"] is not None
    assert result["file_path"] is not None
    assert result["file_size_bytes"] > 0
    assert result["format"] == "json"

    with open(result["file_path"], "r", encoding="utf-8") as f:
        data = json.load(f)

    assert data["user_id"] == 1
    assert data["cases"] == []
    assert data["deadlines"] == []
    assert data["notifications"] == []


def test_export_json_success(test_db):
    """Verify standard JSON export of cases, deadlines, and notifications"""
    # Seed data
    case = Case(
        id=10,
        user_id=1,
        case_number="CASE-12345",
        case_type="civil",
        jurisdiction="Delhi",
        status=CaseStatus.ACTIVE,
        title="My Civil Suit",
    )
    test_db.add(case)
    test_db.commit()

    deadline = CaseDeadline(
        id=20,
        user_id=1,
        case_id=10,
        case_title="My Civil Suit",
        deadline_date=datetime(2026, 6, 1, 10, 0, 0, tzinfo=timezone.utc),
        deadline_type="appeal",
        description="Prepare appeal",
        is_completed=False,
    )
    test_db.add(deadline)
    test_db.commit()

    notification = NotificationLog(
        id=30,
        user_id=1,
        deadline_id=20,
        channel=NotificationChannel.EMAIL,
        status=NotificationStatus.SENT,
        recipient="test@example.com",
        days_before=30,
        sent_at=datetime(2026, 5, 2, 10, 0, 0, tzinfo=timezone.utc),
    )
    test_db.add(notification)
    test_db.commit()

    result = export_data_task._orig_run(user_id="1", format="json", anonymize=False)

    assert result["export_id"] is not None
    assert result["format"] == "json"

    with open(result["file_path"], "r", encoding="utf-8") as f:
        data = json.load(f)

    assert data["user_id"] == 1
    assert len(data["cases"]) == 1
    assert data["cases"][0]["case_number"] == "CASE-12345"
    assert data["cases"][0]["title"] == "My Civil Suit"

    assert len(data["deadlines"]) == 1
    assert data["deadlines"][0]["case_title"] == "My Civil Suit"
    assert data["deadlines"][0]["description"] == "Prepare appeal"

    assert len(data["notifications"]) == 1
    assert data["notifications"][0]["recipient"] == "test@example.com"
    assert data["notifications"][0]["status"] == "sent"


def test_export_json_anonymized(test_db):
    """Verify that anonymization correctly hashes case number/IDs,

    redacts descriptions and masks emails/phones
    """
    # Seed data
    case = Case(
        id=10,
        user_id=1,
        case_number="CASE-12345",
        case_type="civil",
        jurisdiction="Delhi",
        status=CaseStatus.ACTIVE,
        title="My Civil Suit",
    )
    test_db.add(case)
    test_db.commit()

    deadline = CaseDeadline(
        id=20,
        user_id=1,
        case_id=10,
        case_title="My Civil Suit",
        deadline_date=datetime(2026, 6, 1, 10, 0, 0, tzinfo=timezone.utc),
        deadline_type="appeal",
        description="Prepare appeal",
        is_completed=False,
    )
    test_db.add(deadline)
    test_db.commit()

    notification = NotificationLog(
        id=30,
        user_id=1,
        deadline_id=20,
        channel=NotificationChannel.EMAIL,
        status=NotificationStatus.SENT,
        recipient="test@example.com",
        days_before=30,
        sent_at=datetime(2026, 5, 2, 10, 0, 0, tzinfo=timezone.utc),
    )
    test_db.add(notification)
    test_db.commit()

    result = export_data_task._orig_run(user_id="1", format="json", anonymize=True)

    with open(result["file_path"], "r", encoding="utf-8") as f:
        data = json.load(f)

    assert len(data["cases"]) == 1
    assert data["cases"][0]["case_number"] != "CASE-12345"
    assert "ANON-" in data["cases"][0]["case_number"]
    assert data["cases"][0]["title"] == "Anonymized Case Reference"

    assert len(data["deadlines"]) == 1
    assert data["deadlines"][0]["case_title"] == "Anonymized Case Reference"
    assert data["deadlines"][0]["description"] == "Redacted"

    assert len(data["notifications"]) == 1
    assert data["notifications"][0]["recipient"] != "test@example.com"
    assert "t**t@example.com" in data["notifications"][0]["recipient"]


def test_export_csv_success(test_db):
    """Verify standard CSV export format and section boundaries"""
    # Seed data
    case = Case(
        id=10,
        user_id=1,
        case_number="CASE-12345",
        case_type="civil",
        jurisdiction="Delhi",
        status=CaseStatus.ACTIVE,
        title="My Civil Suit",
    )
    test_db.add(case)
    test_db.commit()

    result = export_data_task._orig_run(user_id="1", format="csv", anonymize=False)

    assert result["format"] == "csv"

    with open(result["file_path"], "r", encoding="utf-8") as f:
        content = f.read()

    assert "=== CASES ===" in content
    assert "=== DEADLINES ===" in content
    assert "=== NOTIFICATIONS ===" in content
    assert "CASE-12345" in content
    assert "My Civil Suit" in content
