"""
Timeline Projection - Auto-generated from Events

Builds a timeline of all case events, replacing manual timeline creation.
Rebuildable from event log at any time.

Reference: Issue #2312
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional

from core.domain_events import DomainEvent, EventType
from core.event_store import EventStore


@dataclass
class TimelineEvent:
    """A single event in the timeline."""
    event_id: str
    event_type: str
    description: str
    occurred_at: datetime
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class TimelineProjection:
    """
    Timeline projection for a case.
    
    Automatically generated from events, replacing manual timeline creation.
    """
    
    case_id: str
    events: List[TimelineEvent] = field(default_factory=list)
    version: int = 0
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "case_id": self.case_id,
            "events": [
                {
                    "event_id": e.event_id,
                    "event_type": e.event_type,
                    "description": e.description,
                    "occurred_at": e.occurred_at.isoformat(),
                    "metadata": e.metadata,
                }
                for e in self.events
            ],
            "version": self.version,
        }
    
    @classmethod
    def from_events(cls, case_id: str, events: List[DomainEvent]) -> "TimelineProjection":
        """Build timeline from events."""
        projection = cls(case_id=case_id)
        for event in events:
            projection.apply(event)
        return projection
    
    def apply(self, event: DomainEvent) -> None:
        """Apply an event to build timeline."""
        if event.aggregate_id != self.case_id:
            return
        
        self.version = event.version
        
        description = self._get_description(event)
        
        timeline_event = TimelineEvent(
            event_id=event.event_id,
            event_type=event.event_type,
            description=description,
            occurred_at=event.occurred_at,
            metadata=event.metadata,
        )
        
        self.events.append(timeline_event)
    
    def _get_description(self, event: DomainEvent) -> str:
        """Generate human-readable description for event."""
        # Use getattr with default to handle different event types
        def get(field, default=""):
            return getattr(event, field, default)
        
        descriptions = {
            EventType.CASE_CREATED.value: f"Case created: {get('title')}",
            EventType.CASE_STATUS_CHANGED.value: f"Status changed from {get('previous_status')} to {get('new_status')}",
            EventType.CASE_ASSIGNED.value: f"Case assigned to user {get('assigned_to')}",
            EventType.CASE_ARCHIVED.value: "Case archived",
            EventType.CASE_REOPENED.value: "Case reopened",
            EventType.CASE_DELETED.value: "Case deleted",
            EventType.OUTCOME_RECORDED.value: f"Outcome recorded: {get('outcome')}",
            EventType.DOCUMENT_UPLOADED.value: f"Document uploaded: {get('file_name')}",
            EventType.DOCUMENT_DELETED.value: "Document deleted",
            EventType.DEADLINE_SET.value: f"Deadline set: {get('deadline_type')} on {get('deadline_date')}",
            EventType.DEADLINE_COMPLETED.value: "Deadline marked as completed",
            EventType.NOTE_ADDED.value: "Note added",
            EventType.NOTE_EDITED.value: "Note edited",
            EventType.NOTE_DELETED.value: "Note deleted",
            EventType.COLLABORATOR_ADDED.value: f"Collaborator {get('user_id')} added",
            EventType.COLLABORATOR_REMOVED.value: f"Collaborator {get('user_id')} removed",
            EventType.APPEAL_FILED.value: f"Appeal filed: {get('appeal_type')}",
            EventType.CASE_METADATA_UPDATED.value: "Case metadata updated",
        }
        
        return descriptions.get(event.event_type, f"Event: {event.event_type}")


class TimelineProjectionManager:
    """Manages timeline projections."""
    
    def __init__(self, event_store: EventStore):
        self._event_store = event_store
        self._projections: Dict[str, TimelineProjection] = {}
    
    def get_timeline(self, case_id: str) -> TimelineProjection:
        """Get or rebuild timeline for a case."""
        if case_id not in self._projections:
            self._projections[case_id] = self._rebuild_timeline(case_id)
        return self._projections[case_id]
    
    def _rebuild_timeline(self, case_id: str) -> TimelineProjection:
        """Rebuild timeline from event store."""
        stream = self._event_store.read_stream(case_id)
        return TimelineProjection.from_events(case_id, stream.events)
    
    def subscribe_to_events(self) -> None:
        """Subscribe to event store for real-time updates."""
        def handle_event(event: DomainEvent) -> None:
            case_id = event.aggregate_id
            if case_id not in self._projections:
                self._projections[case_id] = TimelineProjection(case_id=case_id)
            self._projections[case_id].apply(event)
        
        self._event_store.subscribe(handle_event)