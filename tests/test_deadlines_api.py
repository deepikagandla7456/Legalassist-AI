import os
from datetime import datetime, timedelta, timezone

os.environ["JWT_SECRET_KEY"] = "test-secret-key-value-12345"
os.environ["APP_ALLOWED_HOSTS"] = "localhost"

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import api.routes.deadlines as deadlines_route
from api.auth import CurrentUser, get_current_user
from database import Base, Case, CaseDeadline, CaseStatus


@pytest.fixture()
def test_db():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    SessionLocal = sessionmaker(
        autocommit=False,
        autoflush=False,
        expire_on_commit=False,
        bind=engine,
    )
    db = SessionLocal()
    yield db
    db.close()


@pytest.fixture()
def client(test_db):
    app = FastAPI()
    app.include_router(deadlines_route.router)
    app.dependency_overrides[get_current_user] = lambda: CurrentUser("42", "tester@example.com", "user")
    app.dependency_overrides[deadlines_route.get_db] = lambda: test_db
    return TestClient(app)


def _seed_case_and_deadline(test_db, *, user_id: int = 42):
    case = Case(
        user_id=user_id,
        case_number=f"CASE-{user_id}",
        case_type="civil",
        jurisdiction="Delhi",
        status=CaseStatus.ACTIVE,
        title="Example Case",
    )
    test_db.add(case)
    test_db.commit()
    test_db.refresh(case)

    deadline = CaseDeadline(
        user_id=user_id,
        case_id=case.id,
        case_title=case.title,
        deadline_date=datetime.now(timezone.utc) + timedelta(days=10),
        deadline_type="appeal",
        description="Appeal deadline",
        is_completed=False,
    )
    test_db.add(deadline)
    test_db.commit()
    test_db.refresh(deadline)
    return case, deadline


def test_get_deadline_details_forbidden_for_other_user(client, test_db):
    _, deadline = _seed_case_and_deadline(test_db, user_id=99)

    response = client.get(f"/api/v1/deadlines/{deadline.id}")

    assert response.status_code == 404
    assert response.json()["detail"] == "Deadline not found"


def test_create_deadline_forbidden_for_other_users_case(client, test_db):
    case, _ = _seed_case_and_deadline(test_db, user_id=99)
    due_date = (datetime.now(timezone.utc) + timedelta(days=5)).isoformat()

    response = client.post(
        "/api/v1/deadlines",
        params={
            "title": "Cross-user deadline",
            "due_date": due_date,
            "case_id": str(case.id),
        },
    )

    assert response.status_code == 404
    assert response.json()["detail"] == "Case not found"


def test_update_deadline_forbidden_for_other_user(client, test_db):
    _, deadline = _seed_case_and_deadline(test_db, user_id=99)

    response = client.put(
        f"/api/v1/deadlines/{deadline.id}",
        params={"title": "Updated title"},
    )

    assert response.status_code == 404
    assert response.json()["detail"] == "Deadline not found"