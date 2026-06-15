"""
Case Aggregate - Event Sourcing Implementation

The CaseAggregate rebuilds case state by replaying events and enforces
business rules. It emits domain events for state changes.

Reference: Issue #2312 - Audit-Grade Immutable Event Sourcing
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Set, Tuple, Type

from core.domain_events import (
    DomainEvent,
    CaseCreated,
    CaseStatusChanged,
    CaseAssigned,
    CaseArchived,
    CaseReopened,
    CaseDeleted,
    OutcomeRecorded,
    DocumentUploaded,
    DocumentDeleted,
    DeadlineSet,
    DeadlineCompleted,
    NoteAdded,
    NoteEdited,
    NoteDeleted,
    CollaboratorAdded,
    CollaboratorRemoved,
    AppealFiled,
    CaseMetadataUpdated,
    EventType,
)
from core.event_store import EventStore, StreamSlice


# =============================================================================
# Case State (Read Model)
# =============================================================================

@dataclass
class CaseState:
    """Immutable state snapshot of a case."""
    case_id: str = ""
    case_number: str = ""
    user_id: int = 0
    case_type: str = ""
    title: str = ""
    description: str = ""
    jurisdiction: str = ""
    status: str = "active"
    
    # Assigned users
    assigned_to: Optional[int] = None
    collaborators: Set[int] = field(default_factory=set)
    
    # Documents
    documents: List[Dict[str, Any]] = field(default_factory=list)
    
    # Deadlines
    deadlines: List[Dict[str, Any]] = field(default_factory=list)
    
    # Notes
    notes: List[Dict[str, Any]] = field(default_factory=list)
    
    # Outcome
    outcome: Optional[str] = None
    outcome_notes: str = ""
    
    # Appeals
    appeals: List[Dict[str, Any]] = field(default_factory=list)
    
    # Metadata
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    # Version
    version: int = 0
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    deleted_at: Optional[datetime] = None
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert state to dictionary."""
        return {
            "case_id": self.case_id,
            "case_number": self.case_number,
            "user_id": self.user_id,
            "case_type": self.case_type,
            "title": self.title,
            "description": self.description,
            "jurisdiction": self.jurisdiction,
            "status": self.status,
            "assigned_to": self.assigned_to,
            "collaborators": list(self.collaborators),
            "documents": self.documents,
            "deadlines": self.deadlines,
            "notes": self.notes,
            "outcome": self.outcome,
            "outcome_notes": self.outcome_notes,
            "appeals": self.appeals,
            "metadata": self.metadata,
            "version": self.version,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
            "deleted_at": self.deleted_at.isoformat() if self.deleted_at else None,
        }


# =============================================================================
# Business Rule Errors
# =============================================================================

class CaseError(Exception):
    """Base exception for case operations."""
    pass


class InvalidStateTransitionError(CaseError):
    """Raised when an invalid state transition is attempted."""
    pass


class ConcurrencyError(CaseError):
    """Raised when concurrent modification is detected."""
    pass


# =============================================================================
# Case Aggregate
# =============================================================================

class CaseAggregate:
    """
    Event-sourced aggregate for Case entities.
    
    Rebuilds state by replaying events and enforces business rules
    when applying new events.
    """
    
    # Valid status transitions
    VALID_STATUS_TRANSITIONS = {
        "active": ["pending", "closed", "archived"],
        "pending": ["active", "closed", "archived"],
        "closed": ["archived", "reopened"],
        "archived": ["reopened"],
        "reopened": ["active", "pending", "closed", "archived"],
    }
    
    def __init__(
        self,
        case_id: str,
        state: Optional[CaseState] = None,
        uncommitted_events: Optional[List[DomainEvent]] = None,
    ):
        self.case_id = case_id
        self._state = state or CaseState(case_id=case_id)
        self._uncommitted_events: List[DomainEvent] = uncommitted_events or []
        self._is_destroyed = False
    
    # =========================================================================
    # State Access
    # =========================================================================
    
    @property
    def state(self) -> CaseState:
        """Get current state (copy for immutability)."""
        return self._state
    
    @property
    def version(self) -> int:
        """Get current version."""
        return self._state.version
    
    @property
    def uncommitted_events(self) -> List[DomainEvent]:
        """Get uncommitted events."""
        return self._uncommitted_events.copy()
    
    # =========================================================================
    # Factory Methods
    # =========================================================================
    
    @classmethod
    def from_events(cls, events: List[DomainEvent]) -> CaseAggregate:
        """
        Rebuild aggregate state by replaying events.
        
        Args:
            events: List of events to replay
            
        Returns:
            CaseAggregate with rebuilt state
        """
        if not events:
            raise ValueError("Cannot create aggregate from empty events")
        
        case_id = events[0].aggregate_id
        aggregate = cls(case_id=case_id)
        
        for event in events:
            aggregate._apply(event)
        
        return aggregate
    
    @classmethod
    def from_snapshot(cls, case_id: str, state: CaseState, events: List[DomainEvent]) -> CaseAggregate:
        """Create aggregate from snapshot plus events after snapshot."""
        aggregate = cls(case_id=case_id, state=state)
        for event in events:
            aggregate._apply(event)
        return aggregate
    
    # =========================================================================
    # Command Methods (emit events)
    # =========================================================================
    
    def create(
        self,
        user_id: int,
        case_number: str,
        case_type: str,
        title: str,
        description: str = "",
        jurisdiction: str = "",
    ) -> None:
        """Create a new case."""
        if self._state.version > 0:
            raise CaseError("Case already exists")
        
        event = CaseCreated(
            aggregate_id=self.case_id,
            user_id=user_id,
            case_number=case_number,
            case_type=case_type,
            title=title,
            description=description,
            jurisdiction=jurisdiction,
        )
        
        self._emit(event)
    
    def change_status(
        self,
        new_status: str,
        changed_by: int,
        reason: str = "",
    ) -> None:
        """Change case status."""
        self._validate_status_transition(new_status)
        
        event = CaseStatusChanged(
            aggregate_id=self.case_id,
            previous_status=self._state.status,
            new_status=new_status,
            changed_by=changed_by,
            reason=reason,
        )
        
        self._emit(event)
    
    def assign(
        self,
        user_id: int,
        assigned_by: int,
        assignment_type: str = "primary",
    ) -> None:
        """Assign case to a user."""
        event = CaseAssigned(
            aggregate_id=self.case_id,
            assigned_to=user_id,
            assigned_by=assigned_by,
            assignment_type=assignment_type,
        )
        
        self._emit(event)
    
    def archive(self, archived_by: int, reason: str = "") -> None:
        """Archive the case."""
        self.change_status("archived", archived_by, reason)
        
        event = CaseArchived(
            aggregate_id=self.case_id,
            archived_by=archived_by,
            reason=reason,
        )
        
        self._emit(event)
    
    def reopen(self, reopened_by: int, reason: str = "") -> None:
        """Reopen an archived or closed case."""
        self._validate_status_transition("reopened")
        
        event = CaseReopened(
            aggregate_id=self.case_id,
            reopened_by=reopened_by,
            reason=reason,
        )
        
        self._emit(event)
        
        # Also change status to active (only if not already active)
        if self._state.status != "active":
            self.change_status("active", reopened_by, reason)
    
    def delete(self, deleted_by: int, reason: str = "", deletion_type: str = "soft") -> None:
        """Delete the case."""
        event = CaseDeleted(
            aggregate_id=self.case_id,
            deleted_by=deleted_by,
            reason=reason,
            deletion_type=deletion_type,
        )
        
        self._emit(event)
    
    def record_outcome(
        self,
        outcome: str,
        recorded_by: int,
        notes: str = "",
    ) -> None:
        """Record case outcome."""
        event = OutcomeRecorded(
            aggregate_id=self.case_id,
            outcome=outcome,
            notes=notes,
            recorded_by=recorded_by,
        )
        
        self._emit(event)
    
    def add_document(
        self,
        document_id: int,
        document_type: str,
        file_name: str,
        uploaded_by: int,
        summary: str = "",
    ) -> None:
        """Add a document to the case."""
        event = DocumentUploaded(
            aggregate_id=self.case_id,
            document_id=document_id,
            document_type=document_type,
            file_name=file_name,
            uploaded_by=uploaded_by,
            summary=summary,
        )
        
        self._emit(event)
    
    def delete_document(
        self,
        document_id: int,
        deleted_by: int,
        reason: str = "",
    ) -> None:
        """Delete a document from the case."""
        # Validate document exists
        doc_exists = any(d["document_id"] == document_id for d in self._state.documents)
        if not doc_exists:
            raise CaseError(f"Document {document_id} not found")
        
        event = DocumentDeleted(
            aggregate_id=self.case_id,
            document_id=document_id,
            deleted_by=deleted_by,
            reason=reason,
        )
        
        self._emit(event)
    
    def set_deadline(
        self,
        deadline_id: int,
        deadline_type: str,
        deadline_date: str,
        set_by: int,
        description: str = "",
    ) -> None:
        """Set a deadline for the case."""
        event = DeadlineSet(
            aggregate_id=self.case_id,
            deadline_id=deadline_id,
            deadline_type=deadline_type,
            deadline_date=deadline_date,
            description=description,
            set_by=set_by,
        )
        
        self._emit(event)
    
    def complete_deadline(
        self,
        deadline_id: int,
        completed_by: int,
        completion_notes: str = "",
    ) -> None:
        """Mark a deadline as completed."""
        event = DeadlineCompleted(
            aggregate_id=self.case_id,
            deadline_id=deadline_id,
            completed_by=completed_by,
            completion_notes=completion_notes,
        )
        
        self._emit(event)
    
    def add_note(
        self,
        note_id: int,
        content: str,
        added_by: int,
    ) -> None:
        """Add a note to the case."""
        event = NoteAdded(
            aggregate_id=self.case_id,
            note_id=note_id,
            content=content,
            added_by=added_by,
        )
        
        self._emit(event)
    
    def edit_note(
        self,
        note_id: int,
        previous_content: str,
        new_content: str,
        edited_by: int,
    ) -> None:
        """Edit a note."""
        event = NoteEdited(
            aggregate_id=self.case_id,
            note_id=note_id,
            previous_content=previous_content,
            new_content=new_content,
            edited_by=edited_by,
        )
        
        self._emit(event)
    
    def delete_note(
        self,
        note_id: int,
        deleted_by: int,
        reason: str = "",
    ) -> None:
        """Delete a note."""
        event = NoteDeleted(
            aggregate_id=self.case_id,
            note_id=note_id,
            deleted_by=deleted_by,
            reason=reason,
        )
        
        self._emit(event)
    
    def add_collaborator(
        self,
        user_id: int,
        role: str,
        added_by: int,
    ) -> None:
        """Add a collaborator."""
        event = CollaboratorAdded(
            aggregate_id=self.case_id,
            user_id=user_id,
            role=role,
            added_by=added_by,
        )
        
        self._emit(event)
    
    def remove_collaborator(
        self,
        user_id: int,
        removed_by: int,
        reason: str = "",
    ) -> None:
        """Remove a collaborator."""
        event = CollaboratorRemoved(
            aggregate_id=self.case_id,
            user_id=user_id,
            removed_by=removed_by,
            reason=reason,
        )
        
        self._emit(event)
    
    def file_appeal(
        self,
        appeal_id: int,
        appeal_type: str,
        filed_by: int,
        deadline_date: str,
    ) -> None:
        """File an appeal."""
        event = AppealFiled(
            aggregate_id=self.case_id,
            appeal_id=appeal_id,
            appeal_type=appeal_type,
            filed_by=filed_by,
            deadline_date=deadline_date,
        )
        
        self._emit(event)
    
    def update_metadata(
        self,
        previous_metadata: Dict[str, Any],
        new_metadata: Dict[str, Any],
        updated_by: int,
    ) -> None:
        """Update case metadata."""
        event = CaseMetadataUpdated(
            aggregate_id=self.case_id,
            previous_metadata=previous_metadata,
            new_metadata=new_metadata,
            updated_by=updated_by,
        )
        
        self._emit(event)
    
    # =========================================================================
    # Event Application
    # =========================================================================
    
    def _emit(self, event: DomainEvent) -> None:
        """Emit an event and update state."""
        if self._is_destroyed:
            raise CaseError("Aggregate has been destroyed")
        
        # Validate business rules
        self._validate_event(event)
        
        # Apply to state
        self._apply(event)
        
        # Track uncommitted event
        self._uncommitted_events.append(event)
    
    def _apply(self, event: DomainEvent) -> None:
        """Apply an event to the state."""
        handler = self._event_handlers.get(type(event).__name__)
        if handler:
            handler(self, event)
        
        # Update version - use getattr with default for frozen dataclass compatibility
        self._state.version = getattr(event, 'version', self._state.version + 1)
        self._state.updated_at = event.occurred_at
    
    def _validate_event(self, event: DomainEvent) -> None:
        """Validate an event against business rules."""
        # Subclass can override for additional validation
        pass
    
    def _validate_status_transition(self, new_status: str) -> None:
        """Validate status transition."""
        current = self._state.status
        valid = self.VALID_STATUS_TRANSITIONS.get(current, [])
        
        if new_status not in valid:
            raise InvalidStateTransitionError(
                f"Cannot transition from {current} to {new_status}"
            )
    
    # =========================================================================
    # Event Handlers
    # =========================================================================
    
    _event_handlers: Dict[str, callable] = {}
    
    def _handle_case_created(self, event: CaseCreated) -> None:
        self._state.case_number = event.case_number
        self._state.user_id = event.user_id
        self._state.case_type = event.case_type
        self._state.title = event.title
        self._state.description = event.description
        self._state.jurisdiction = event.jurisdiction
        self._state.created_at = event.occurred_at
    
    _event_handlers["CaseCreated"] = _handle_case_created
    
    def _handle_status_changed(self, event: CaseStatusChanged) -> None:
        self._state.status = event.new_status
    
    _event_handlers["CaseStatusChanged"] = _handle_status_changed
    
    def _handle_case_assigned(self, event: CaseAssigned) -> None:
        if event.assignment_type == "primary":
            self._state.assigned_to = event.assigned_to
        else:
            self._state.collaborators.add(event.assigned_to)
    
    _event_handlers["CaseAssigned"] = _handle_case_assigned
    
    def _handle_case_archived(self, event: CaseArchived) -> None:
        self._state.status = "archived"
    
    _event_handlers["CaseArchived"] = _handle_case_archived
    
    def _handle_case_reopened(self, event: CaseReopened) -> None:
        self._state.status = "active"
        self._state.deleted_at = None
    
    _event_handlers["CaseReopened"] = _handle_case_reopened
    
    def _handle_case_deleted(self, event: CaseDeleted) -> None:
        self._state.deleted_at = event.occurred_at
        if event.deletion_type == "soft":
            self._state.status = "deleted"
        else:
            self._is_destroyed = True
    
    _event_handlers["CaseDeleted"] = _handle_case_deleted
    
    def _handle_outcome_recorded(self, event: OutcomeRecorded) -> None:
        self._state.outcome = event.outcome
        self._state.outcome_notes = event.notes
    
    _event_handlers["OutcomeRecorded"] = _handle_outcome_recorded
    
    def _handle_document_uploaded(self, event: DocumentUploaded) -> None:
        self._state.documents.append({
            "document_id": event.document_id,
            "document_type": event.document_type,
            "file_name": event.file_name,
            "uploaded_at": event.occurred_at.isoformat(),
            "uploaded_by": event.uploaded_by,
            "summary": event.summary,
        })
    
    _event_handlers["DocumentUploaded"] = _handle_document_uploaded
    
    def _handle_document_deleted(self, event: DocumentDeleted) -> None:
        self._state.documents = [
            d for d in self._state.documents
            if d.get("document_id") != event.document_id
        ]
    
    _event_handlers["DocumentDeleted"] = _handle_document_deleted
    
    def _handle_deadline_set(self, event: DeadlineSet) -> None:
        self._state.deadlines.append({
            "deadline_id": event.deadline_id,
            "deadline_type": event.deadline_type,
            "deadline_date": event.deadline_date,
            "description": event.description,
            "completed": False,
        })
    
    _event_handlers["DeadlineSet"] = _handle_deadline_set
    
    def _handle_deadline_completed(self, event: DeadlineCompleted) -> None:
        for deadline in self._state.deadlines:
            if deadline.get("deadline_id") == event.deadline_id:
                deadline["completed"] = True
                deadline["completed_at"] = event.occurred_at.isoformat()
                deadline["completion_notes"] = event.completion_notes
                break
    
    _event_handlers["DeadlineCompleted"] = _handle_deadline_completed
    
    def _handle_note_added(self, event: NoteAdded) -> None:
        self._state.notes.append({
            "note_id": event.note_id,
            "content": event.content,
            "created_at": event.occurred_at.isoformat(),
            "created_by": event.added_by,
        })
    
    _event_handlers["NoteAdded"] = _handle_note_added
    
    def _handle_note_edited(self, event: NoteEdited) -> None:
        for note in self._state.notes:
            if note.get("note_id") == event.note_id:
                note["content"] = event.new_content
                note["edited_at"] = event.occurred_at.isoformat()
                note["edited_by"] = event.edited_by
                break
    
    _event_handlers["NoteEdited"] = _handle_note_edited
    
    def _handle_note_deleted(self, event: NoteDeleted) -> None:
        self._state.notes = [
            n for n in self._state.notes
            if n.get("note_id") != event.note_id
        ]
    
    _event_handlers["NoteDeleted"] = _handle_note_deleted
    
    def _handle_collaborator_added(self, event: CollaboratorAdded) -> None:
        self._state.collaborators.add(event.user_id)
    
    _event_handlers["CollaboratorAdded"] = _handle_collaborator_added
    
    def _handle_collaborator_removed(self, event: CollaboratorRemoved) -> None:
        self._state.collaborators.discard(event.user_id)
    
    _event_handlers["CollaboratorRemoved"] = _handle_collaborator_removed
    
    def _handle_appeal_filed(self, event: AppealFiled) -> None:
        self._state.appeals.append({
            "appeal_id": event.appeal_id,
            "appeal_type": event.appeal_type,
            "filed_at": event.occurred_at.isoformat(),
            "filed_by": event.filed_by,
            "deadline_date": event.deadline_date,
        })
    
    _event_handlers["AppealFiled"] = _handle_appeal_filed
    
    def _handle_metadata_updated(self, event: CaseMetadataUpdated) -> None:
        self._state.metadata = event.new_metadata
    
    _event_handlers["CaseMetadataUpdated"] = _handle_metadata_updated
    
    # =========================================================================
    # State Reconstruction
    # =========================================================================
    
    def get_timeline(self) -> List[Dict[str, Any]]:
        """Get timeline of all events as read model."""
        return [
            {
                "event_type": e.event_type,
                "occurred_at": e.occurred_at.isoformat(),
                "version": e.version,
            }
            for e in self._uncommitted_events
        ]
    
    def can_evidence_state_at(self, version: int) -> bool:
        """Check if state can be evidenced at a specific version."""
        return version <= self._state.version