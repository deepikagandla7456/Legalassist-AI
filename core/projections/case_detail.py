"""
Case Detail Projection - Denormalized Read Model

Builds and maintains a denormalized case detail view from events.
Rebuildable from event log at any time.

Reference: Issue #2312
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional, Set

from core.domain_events import DomainEvent, EventType
from core.event_store import EventStore


@dataclass
class CaseDetailProjection:
    """
    Denormalized read model for case details.
    
    Built from events and always rebuildable from event log.
    """
    
    case_id: str
    case_number: str = ""
    user_id: int = 0
    case_type: str = ""
    title: str = ""
    description: str = ""
    jurisdiction: str = ""
    status: str = "active"
    
    # Assignment
    assigned_to: Optional[int] = None
    collaborators: Set[int] = field(default_factory=set)
    
    # Related entities (collected from events)
    documents: List[Dict[str, Any]] = field(default_factory=list)
    deadlines: List[Dict[str, Any]] = field(default_factory=list)
    notes: List[Dict[str, Any]] = field(default_factory=list)
    appeals: List[Dict[str, Any]] = field(default_factory=list)
    
    # Outcome
    outcome: Optional[str] = None
    outcome_notes: str = ""
    
    # Metadata
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    # Timestamps
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    deleted_at: Optional[datetime] = None
    
    # Version
    version: int = 0
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
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
            "appeals": self.appeals,
            "outcome": self.outcome,
            "outcome_notes": self.outcome_notes,
            "metadata": self.metadata,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
            "deleted_at": self.deleted_at.isoformat() if self.deleted_at else None,
            "version": self.version,
        }
    
    @classmethod
    def from_events(cls, case_id: str, events: List[DomainEvent]) -> "CaseDetailProjection":
        """Rebuild projection from events."""
        projection = cls(case_id=case_id)
        for event in events:
            projection.apply(event)
        return projection
    
    def apply(self, event: DomainEvent) -> None:
        """Apply a single event to update projection."""
        if event.aggregate_id != self.case_id:
            return
        
        self.version = event.version
        self.updated_at = event.occurred_at
        
        # Route to specific handler
        handler = self._handlers.get(event.event_type)
        if handler:
            handler(self, event)
    
    # ========================================================================
    # Event Handlers
    # ========================================================================
    
    def _handle_case_created(self, event) -> None:
        """Handle case created event."""
        self.case_number = event.case_number
        self.user_id = event.user_id
        self.case_type = event.case_type
        self.title = event.title
        self.description = event.description
        self.jurisdiction = event.jurisdiction
        self.created_at = event.occurred_at
        self.status = "active"
    
    def _handle_status_changed(self, event) -> None:
        """Handle status changed event."""
        self.status = event.new_status
    
    def _handle_case_assigned(self, event) -> None:
        """Handle case assigned event."""
        if event.assignment_type == "primary":
            self.assigned_to = event.assigned_to
        else:
            self.collaborators.add(event.assigned_to)
    
    def _handle_case_archived(self, event) -> None:
        """Handle case archived event."""
        self.status = "archived"
    
    def _handle_case_reopened(self, event) -> None:
        """Handle case reopened event."""
        self.status = "active"
        self.deleted_at = None
    
    def _handle_case_deleted(self, event) -> None:
        """Handle case deleted event."""
        if event.deletion_type == "soft":
            self.status = "deleted"
            self.deleted_at = event.occurred_at
        else:
            self.status = "deleted"
            self.deleted_at = event.occurred_at
    
    def _handle_outcome_recorded(self, event) -> None:
        """Handle outcome recorded event."""
        self.outcome = event.outcome
        self.outcome_notes = event.notes
    
    def _handle_document_uploaded(self, event) -> None:
        """Handle document uploaded event."""
        self.documents.append({
            "document_id": event.document_id,
            "document_type": event.document_type,
            "file_name": event.file_name,
            "uploaded_at": event.occurred_at.isoformat(),
            "uploaded_by": event.uploaded_by,
            "summary": event.summary,
        })
    
    def _handle_document_deleted(self, event) -> None:
        """Handle document deleted event."""
        self.documents = [
            d for d in self.documents
            if d.get("document_id") != event.document_id
        ]
    
    def _handle_deadline_set(self, event) -> None:
        """Handle deadline set event."""
        self.deadlines.append({
            "deadline_id": event.deadline_id,
            "deadline_type": event.deadline_type,
            "deadline_date": event.deadline_date,
            "description": event.description,
            "set_by": event.set_by,
            "completed": False,
        })
    
    def _handle_deadline_completed(self, event) -> None:
        """Handle deadline completed event."""
        for deadline in self.deadlines:
            if deadline.get("deadline_id") == event.deadline_id:
                deadline["completed"] = True
                deadline["completed_at"] = event.occurred_at.isoformat()
                deadline["completion_notes"] = event.completion_notes
                break
    
    def _handle_note_added(self, event) -> None:
        """Handle note added event."""
        self.notes.append({
            "note_id": event.note_id,
            "content": event.content,
            "created_at": event.occurred_at.isoformat(),
            "created_by": event.added_by,
        })
    
    def _handle_note_edited(self, event) -> None:
        """Handle note edited event."""
        for note in self.notes:
            if note.get("note_id") == event.note_id:
                note["content"] = event.new_content
                note["edited_at"] = event.occurred_at.isoformat()
                note["edited_by"] = event.edited_by
                break
    
    def _handle_note_deleted(self, event) -> None:
        """Handle note deleted event."""
        self.notes = [
            n for n in self.notes
            if n.get("note_id") != event.note_id
        ]
    
    def _handle_collaborator_added(self, event) -> None:
        """Handle collaborator added event."""
        self.collaborators.add(event.user_id)
    
    def _handle_collaborator_removed(self, event) -> None:
        """Handle collaborator removed event."""
        self.collaborators.discard(event.user_id)
    
    def _handle_appeal_filed(self, event) -> None:
        """Handle appeal filed event."""
        self.appeals.append({
            "appeal_id": event.appeal_id,
            "appeal_type": event.appeal_type,
            "filed_at": event.occurred_at.isoformat(),
            "filed_by": event.filed_by,
            "deadline_date": event.deadline_date,
        })
    
    def _handle_metadata_updated(self, event) -> None:
        """Handle metadata updated event."""
        self.metadata = event.new_metadata
    
    _handlers = {
        EventType.CASE_CREATED.value: _handle_case_created,
        EventType.CASE_STATUS_CHANGED.value: _handle_status_changed,
        EventType.CASE_ASSIGNED.value: _handle_case_assigned,
        EventType.CASE_ARCHIVED.value: _handle_case_archived,
        EventType.CASE_REOPENED.value: _handle_case_reopened,
        EventType.CASE_DELETED.value: _handle_case_deleted,
        EventType.OUTCOME_RECORDED.value: _handle_outcome_recorded,
        EventType.DOCUMENT_UPLOADED.value: _handle_document_uploaded,
        EventType.DOCUMENT_DELETED.value: _handle_document_deleted,
        EventType.DEADLINE_SET.value: _handle_deadline_set,
        EventType.DEADLINE_COMPLETED.value: _handle_deadline_completed,
        EventType.NOTE_ADDED.value: _handle_note_added,
        EventType.NOTE_EDITED.value: _handle_note_edited,
        EventType.NOTE_DELETED.value: _handle_note_deleted,
        EventType.COLLABORATOR_ADDED.value: _handle_collaborator_added,
        EventType.COLLABORATOR_REMOVED.value: _handle_collaborator_removed,
        EventType.APPEAL_FILED.value: _handle_appeal_filed,
        EventType.CASE_METADATA_UPDATED.value: _handle_metadata_updated,
    }


class CaseDetailProjectionManager:
    """Manages case detail projections."""
    
    def __init__(self, event_store: EventStore):
        self._event_store = event_store
        self._projections: Dict[str, CaseDetailProjection] = {}
    
    def get_projection(self, case_id: str) -> CaseDetailProjection:
        """Get or rebuild projection for a case."""
        if case_id not in self._projections:
            self._projections[case_id] = self._rebuild_projection(case_id)
        return self._projections[case_id]
    
    def _rebuild_projection(self, case_id: str) -> CaseDetailProjection:
        """Rebuild projection from event store."""
        stream = self._event_store.read_stream(case_id)
        return CaseDetailProjection.from_events(case_id, stream.events)
    
    def rebuild_all(self) -> Dict[str, CaseDetailProjection]:
        """Rebuild all projections."""
        self._projections.clear()
        
        # Read all events
        position = 0
        while True:
            slice = self._event_store.read_all(from_position=position)
            
            if not slice.events:
                break
            
            for event in slice.events:
                if event.aggregate_id not in self._projections:
                    self._projections[event.aggregate_id] = CaseDetailProjection(
                        case_id=event.aggregate_id
                    )
                self._projections[event.aggregate_id].apply(event)
            
            if not slice.has_more:
                break
            
            position += len(slice.events)
        
        return self._projections
    
    def subscribe_to_events(self) -> None:
        """Subscribe to event store for real-time updates."""
        def handle_event(event: DomainEvent) -> None:
            if event.aggregate_id not in self._projections:
                self._projections[event.aggregate_id] = CaseDetailProjection(
                    case_id=event.aggregate_id
                )
            self._projections[event.aggregate_id].apply(event)
        
        self._event_store.subscribe(handle_event)