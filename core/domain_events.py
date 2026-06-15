"""
Audit-Grade Immutable Domain Events for Case Lifecycle

This module defines all immutable domain events for the case management system.
Each event is a frozen dataclass representing a state transition.

Reference: Issue #2312 - Audit-Grade Immutable Event Sourcing
"""

from __future__ import annotations

import hashlib
import json
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, Optional, List, Tuple


class EventType(Enum):
    """Enumeration of all domain event types."""
    # Case lifecycle events
    CASE_CREATED = "case.created"
    CASE_STATUS_CHANGED = "case.status_changed"
    CASE_ASSIGNED = "case.assigned"
    CASE_ARCHIVED = "case.archived"
    CASE_REOPENED = "case.reopened"
    CASE_DELETED = "case.deleted"
    OUTCOME_RECORDED = "case.outcome_recorded"
    
    # Document events
    DOCUMENT_UPLOADED = "document.uploaded"
    DOCUMENT_DELETED = "document.deleted"
    
    # Deadline events
    DEADLINE_SET = "deadline.set"
    DEADLINE_COMPLETED = "deadline.completed"
    
    # Note events
    NOTE_ADDED = "note.added"
    NOTE_EDITED = "note.edited"
    NOTE_DELETED = "note.deleted"
    
    # Collaboration events
    COLLABORATOR_ADDED = "collaborator.added"
    COLLABORATOR_REMOVED = "collaborator.removed"
    
    # Appeal events
    APPEAL_FILED = "appeal.filed"
    
    # Metadata events
    CASE_METADATA_UPDATED = "case.metadata_updated"


class CaseStatus(Enum):
    """Case status enumeration."""
    ACTIVE = "active"
    PENDING = "pending"
    CLOSED = "closed"
    ARCHIVED = "archived"


@dataclass(frozen=True)
class DomainEvent:
    """Base class for all immutable domain events."""
    
    event_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    event_type: str = ""
    occurred_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    aggregate_id: str = ""
    aggregate_type: str = "Case"
    version: int = 1
    prev_hash: str = ""
    signature: str = ""
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    def __post_init__(self):
        """Validate event after initialization."""
        if not self.event_id:
            object.__setattr__(self, 'event_id', str(uuid.uuid4()))
        if not self.occurred_at:
            object.__setattr__(self, 'occurred_at', datetime.now(timezone.utc))
    
    def compute_hash(self, prev_hash: str = "") -> str:
        """Compute SHA-256 hash of event content."""
        content = {
            "event_id": self.event_id,
            "event_type": self.event_type,
            "occurred_at": self.occurred_at.isoformat(),
            "aggregate_id": self.aggregate_id,
            "aggregate_type": self.aggregate_type,
            "version": self.version,
            "payload": self._get_payload(),
        }
        content_json = json.dumps(content, sort_keys=True, default=str)
        return hashlib.sha256(f"{prev_hash}|{content_json}".encode()).hexdigest()
    
    def _get_payload(self) -> Dict[str, Any]:
        """Override in subclasses to return event-specific payload."""
        return {}
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert event to dictionary for serialization."""
        return {
            "event_id": self.event_id,
            "event_type": self.event_type,
            "occurred_at": self.occurred_at.isoformat(),
            "aggregate_id": self.aggregate_id,
            "aggregate_type": self.aggregate_type,
            "version": self.version,
            "prev_hash": self.prev_hash,
            "signature": self.signature,
            "metadata": self.metadata,
            "payload": self._get_payload(),
        }


# =============================================================================
# Case Lifecycle Events
# =============================================================================

@dataclass(frozen=True)
class CaseCreated(DomainEvent):
    """Event emitted when a new case is created."""
    
    user_id: int = 0
    case_number: str = ""
    case_type: str = ""
    title: str = ""
    description: str = ""
    jurisdiction: str = ""
    
    def __post_init__(self):
        object.__setattr__(self, 'event_type', EventType.CASE_CREATED.value)
        super().__post_init__()
    
    def _get_payload(self) -> Dict[str, Any]:
        return {
            "user_id": self.user_id,
            "case_number": self.case_number,
            "case_type": self.case_type,
            "title": self.title,
            "description": self.description,
            "jurisdiction": self.jurisdiction,
        }


@dataclass(frozen=True)
class CaseStatusChanged(DomainEvent):
    """Event emitted when case status changes."""
    
    previous_status: str = ""
    new_status: str = ""
    changed_by: int = 0
    reason: str = ""
    
    def __post_init__(self):
        object.__setattr__(self, 'event_type', EventType.CASE_STATUS_CHANGED.value)
        super().__post_init__()
    
    def _get_payload(self) -> Dict[str, Any]:
        return {
            "previous_status": self.previous_status,
            "new_status": self.new_status,
            "changed_by": self.changed_by,
            "reason": self.reason,
        }


@dataclass(frozen=True)
class CaseAssigned(DomainEvent):
    """Event emitted when a case is assigned."""
    
    assigned_to: int = 0
    assigned_by: int = 0
    assignment_type: str = "primary"
    
    def __post_init__(self):
        object.__setattr__(self, 'event_type', EventType.CASE_ASSIGNED.value)
        super().__post_init__()
    
    def _get_payload(self) -> Dict[str, Any]:
        return {
            "assigned_to": self.assigned_to,
            "assigned_by": self.assigned_by,
            "assignment_type": self.assignment_type,
        }


@dataclass(frozen=True)
class CaseArchived(DomainEvent):
    """Event emitted when a case is archived."""
    
    archived_by: int = 0
    reason: str = ""
    
    def __post_init__(self):
        object.__setattr__(self, 'event_type', EventType.CASE_ARCHIVED.value)
        super().__post_init__()
    
    def _get_payload(self) -> Dict[str, Any]:
        return {
            "archived_by": self.archived_by,
            "reason": self.reason,
        }


@dataclass(frozen=True)
class CaseReopened(DomainEvent):
    """Event emitted when an archived/closed case is reopened."""
    
    reopened_by: int = 0
    reason: str = ""
    
    def __post_init__(self):
        object.__setattr__(self, 'event_type', EventType.CASE_REOPENED.value)
        super().__post_init__()
    
    def _get_payload(self) -> Dict[str, Any]:
        return {
            "reopened_by": self.reopened_by,
            "reason": self.reason,
        }


@dataclass(frozen=True)
class CaseDeleted(DomainEvent):
    """Event emitted when a case is deleted (soft delete)."""
    
    deleted_by: int = 0
    reason: str = ""
    deletion_type: str = "soft"  # soft or hard
    
    def __post_init__(self):
        object.__setattr__(self, 'event_type', EventType.CASE_DELETED.value)
        super().__post_init__()
    
    def _get_payload(self) -> Dict[str, Any]:
        return {
            "deleted_by": self.deleted_by,
            "reason": self.reason,
            "deletion_type": self.deletion_type,
        }


@dataclass(frozen=True)
class OutcomeRecorded(DomainEvent):
    """Event emitted when case outcome is recorded."""
    
    outcome: str = ""
    notes: str = ""
    recorded_by: int = 0
    
    def __post_init__(self):
        object.__setattr__(self, 'event_type', EventType.OUTCOME_RECORDED.value)
        super().__post_init__()
    
    def _get_payload(self) -> Dict[str, Any]:
        return {
            "outcome": self.outcome,
            "notes": self.notes,
            "recorded_by": self.recorded_by,
        }


# =============================================================================
# Document Events
# =============================================================================

@dataclass(frozen=True)
class DocumentUploaded(DomainEvent):
    """Event emitted when a document is uploaded."""
    
    document_id: int = 0
    document_type: str = ""
    file_name: str = ""
    uploaded_by: int = 0
    summary: str = ""
    
    def __post_init__(self):
        object.__setattr__(self, 'event_type', EventType.DOCUMENT_UPLOADED.value)
        super().__post_init__()
    
    def _get_payload(self) -> Dict[str, Any]:
        return {
            "document_id": self.document_id,
            "document_type": self.document_type,
            "file_name": self.file_name,
            "uploaded_by": self.uploaded_by,
            "summary": self.summary,
        }


@dataclass(frozen=True)
class DocumentDeleted(DomainEvent):
    """Event emitted when a document is deleted."""
    
    document_id: int = 0
    deleted_by: int = 0
    reason: str = ""
    
    def __post_init__(self):
        object.__setattr__(self, 'event_type', EventType.DOCUMENT_DELETED.value)
        super().__post_init__()
    
    def _get_payload(self) -> Dict[str, Any]:
        return {
            "document_id": self.document_id,
            "deleted_by": self.deleted_by,
            "reason": self.reason,
        }


# =============================================================================
# Deadline Events
# =============================================================================

@dataclass(frozen=True)
class DeadlineSet(DomainEvent):
    """Event emitted when a deadline is set."""
    
    deadline_id: int = 0
    deadline_type: str = ""
    deadline_date: str = ""
    description: str = ""
    set_by: int = 0
    
    def __post_init__(self):
        object.__setattr__(self, 'event_type', EventType.DEADLINE_SET.value)
        super().__post_init__()
    
    def _get_payload(self) -> Dict[str, Any]:
        return {
            "deadline_id": self.deadline_id,
            "deadline_type": self.deadline_type,
            "deadline_date": self.deadline_date,
            "description": self.description,
            "set_by": self.set_by,
        }


@dataclass(frozen=True)
class DeadlineCompleted(DomainEvent):
    """Event emitted when a deadline is marked as completed."""
    
    deadline_id: int = 0
    completed_by: int = 0
    completion_notes: str = ""
    
    def __post_init__(self):
        object.__setattr__(self, 'event_type', EventType.DEADLINE_COMPLETED.value)
        super().__post_init__()
    
    def _get_payload(self) -> Dict[str, Any]:
        return {
            "deadline_id": self.deadline_id,
            "completed_by": self.completed_by,
            "completion_notes": self.completion_notes,
        }


# =============================================================================
# Note Events
# =============================================================================

@dataclass(frozen=True)
class NoteAdded(DomainEvent):
    """Event emitted when a note is added."""
    
    note_id: int = 0
    content: str = ""
    added_by: int = 0
    
    def __post_init__(self):
        object.__setattr__(self, 'event_type', EventType.NOTE_ADDED.value)
        super().__post_init__()
    
    def _get_payload(self) -> Dict[str, Any]:
        return {
            "note_id": self.note_id,
            "content": self.content,
            "added_by": self.added_by,
        }


@dataclass(frozen=True)
class NoteEdited(DomainEvent):
    """Event emitted when a note is edited."""
    
    note_id: int = 0
    previous_content: str = ""
    new_content: str = ""
    edited_by: int = 0
    
    def __post_init__(self):
        object.__setattr__(self, 'event_type', EventType.NOTE_EDITED.value)
        super().__post_init__()
    
    def _get_payload(self) -> Dict[str, Any]:
        return {
            "note_id": self.note_id,
            "previous_content": self.previous_content,
            "new_content": self.new_content,
            "edited_by": self.edited_by,
        }


@dataclass(frozen=True)
class NoteDeleted(DomainEvent):
    """Event emitted when a note is deleted."""
    
    note_id: int = 0
    deleted_by: int = 0
    reason: str = ""
    
    def __post_init__(self):
        object.__setattr__(self, 'event_type', EventType.NOTE_DELETED.value)
        super().__post_init__()
    
    def _get_payload(self) -> Dict[str, Any]:
        return {
            "note_id": self.note_id,
            "deleted_by": self.deleted_by,
            "reason": self.reason,
        }


# =============================================================================
# Collaboration Events
# =============================================================================

@dataclass(frozen=True)
class CollaboratorAdded(DomainEvent):
    """Event emitted when a collaborator is added."""
    
    user_id: int = 0
    role: str = "viewer"
    added_by: int = 0
    
    def __post_init__(self):
        object.__setattr__(self, 'event_type', EventType.COLLABORATOR_ADDED.value)
        super().__post_init__()
    
    def _get_payload(self) -> Dict[str, Any]:
        return {
            "user_id": self.user_id,
            "role": self.role,
            "added_by": self.added_by,
        }


@dataclass(frozen=True)
class CollaboratorRemoved(DomainEvent):
    """Event emitted when a collaborator is removed."""
    
    user_id: int = 0
    removed_by: int = 0
    reason: str = ""
    
    def __post_init__(self):
        object.__setattr__(self, 'event_type', EventType.COLLABORATOR_REMOVED.value)
        super().__post_init__()
    
    def _get_payload(self) -> Dict[str, Any]:
        return {
            "user_id": self.user_id,
            "removed_by": self.removed_by,
            "reason": self.reason,
        }


# =============================================================================
# Appeal Events
# =============================================================================

@dataclass(frozen=True)
class AppealFiled(DomainEvent):
    """Event emitted when an appeal is filed."""
    
    appeal_id: int = 0
    appeal_type: str = ""
    filed_by: int = 0
    deadline_date: str = ""
    
    def __post_init__(self):
        object.__setattr__(self, 'event_type', EventType.APPEAL_FILED.value)
        super().__post_init__()
    
    def _get_payload(self) -> Dict[str, Any]:
        return {
            "appeal_id": self.appeal_id,
            "appeal_type": self.appeal_type,
            "filed_by": self.filed_by,
            "deadline_date": self.deadline_date,
        }


# =============================================================================
# Metadata Events
# =============================================================================

@dataclass(frozen=True)
class CaseMetadataUpdated(DomainEvent):
    """Event emitted when case metadata is updated."""
    
    previous_metadata: Dict[str, Any] = field(default_factory=dict)
    new_metadata: Dict[str, Any] = field(default_factory=dict)
    updated_by: int = 0
    
    def __post_init__(self):
        object.__setattr__(self, 'event_type', EventType.CASE_METADATA_UPDATED.value)
        super().__post_init__()
    
    def _get_payload(self) -> Dict[str, Any]:
        return {
            "previous_metadata": self.previous_metadata,
            "new_metadata": self.new_metadata,
            "updated_by": self.updated_by,
        }


# =============================================================================
# Event Factory
# =============================================================================

EVENT_TYPE_MAP: Dict[str, type] = {
    EventType.CASE_CREATED.value: CaseCreated,
    EventType.CASE_STATUS_CHANGED.value: CaseStatusChanged,
    EventType.CASE_ASSIGNED.value: CaseAssigned,
    EventType.CASE_ARCHIVED.value: CaseArchived,
    EventType.CASE_REOPENED.value: CaseReopened,
    EventType.CASE_DELETED.value: CaseDeleted,
    EventType.OUTCOME_RECORDED.value: OutcomeRecorded,
    EventType.DOCUMENT_UPLOADED.value: DocumentUploaded,
    EventType.DOCUMENT_DELETED.value: DocumentDeleted,
    EventType.DEADLINE_SET.value: DeadlineSet,
    EventType.DEADLINE_COMPLETED.value: DeadlineCompleted,
    EventType.NOTE_ADDED.value: NoteAdded,
    EventType.NOTE_EDITED.value: NoteEdited,
    EventType.NOTE_DELETED.value: NoteDeleted,
    EventType.COLLABORATOR_ADDED.value: CollaboratorAdded,
    EventType.COLLABORATOR_REMOVED.value: CollaboratorRemoved,
    EventType.APPEAL_FILED.value: AppealFiled,
    EventType.CASE_METADATA_UPDATED.value: CaseMetadataUpdated,
}


def create_event(event_type: str, aggregate_id: str, **kwargs) -> DomainEvent:
    """Factory function to create domain events."""
    event_class = EVENT_TYPE_MAP.get(event_type)
    if not event_class:
        raise ValueError(f"Unknown event type: {event_type}")
    return event_class(aggregate_id=aggregate_id, **kwargs)


def deserialize_event(data: Dict[str, Any]) -> DomainEvent:
    """Deserialize a dictionary back into a domain event."""
    event_type = data.get("event_type", "")
    event_class = EVENT_TYPE_MAP.get(event_type)
    if not event_class:
        raise ValueError(f"Unknown event type: {event_type}")
    
    payload = data.get("payload", {})
    return event_class(
        event_id=data.get("event_id", ""),
        aggregate_id=data.get("aggregate_id", ""),
        version=data.get("version", 1),
        prev_hash=data.get("prev_hash", ""),
        signature=data.get("signature", ""),
        occurred_at=datetime.fromisoformat(data["occurred_at"]) if "occurred_at" in data else datetime.now(timezone.utc),
        metadata=data.get("metadata", {}),
        **payload,
    )