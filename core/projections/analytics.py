"""
Analytics Projection - Aggregated Stats from Events

Builds aggregated analytics from event streams.
Feeds analytics_engine.py with rebuildable stats.

Reference: Issue #2312
"""

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

from core.domain_events import DomainEvent, EventType
from core.event_store import EventStore


@dataclass
class CaseAnalytics:
    """Analytics for a single case."""
    case_id: str
    total_events: int = 0
    status_history: List[str] = field(default_factory=list)
    document_count: int = 0
    deadline_count: int = 0
    note_count: int = 0
    collaborator_count: int = 0
    appeal_count: int = 0
    last_activity: Optional[datetime] = None
    created_at: Optional[datetime] = None


@dataclass
class SystemAnalytics:
    """System-wide analytics."""
    total_cases: int = 0
    active_cases: int = 0
    closed_cases: int = 0
    archived_cases: int = 0
    deleted_cases: int = 0
    total_events: int = 0
    events_by_type: Dict[str, int] = field(default_factory=dict)
    cases_by_type: Dict[str, int] = field(default_factory=dict)
    cases_by_jurisdiction: Dict[str, int] = field(default_factory=dict)
    recent_activity_count: int = 0


class AnalyticsProjection:
    """
    Analytics projection built from events.
    
    Aggregates statistics and feeds analytics_engine.py.
    """
    
    def __init__(self, event_store: EventStore):
        self._event_store = event_store
        self._case_analytics: Dict[str, CaseAnalytics] = {}
        self._system_analytics = SystemAnalytics()
        self._initialized = False
    
    def rebuild_all(self) -> SystemAnalytics:
        """Rebuild all analytics from event store."""
        self._case_analytics.clear()
        self._system_analytics = SystemAnalytics()
        
        position = 0
        while True:
            slice = self._event_store.read_all(from_position=position)
            
            if not slice.events:
                break
            
            for event in slice.events:
                self._apply_event(event)
            
            if not slice.has_more:
                break
            
            position += len(slice.events)
        
        self._initialized = True
        return self._system_analytics
    
    def _apply_event(self, event: DomainEvent) -> None:
        """Apply event to analytics."""
        case_id = event.aggregate_id
        
        # Initialize case analytics if needed
        if case_id not in self._case_analytics:
            self._case_analytics[case_id] = CaseAnalytics(case_id=case_id)
        
        case = self._case_analytics[case_id]
        case.total_events += 1
        case.last_activity = event.occurred_at
        
        # Update system analytics
        self._system_analytics.total_events += 1
        self._system_analytics.events_by_type[event.event_type] = \
            self._system_analytics.events_by_type.get(event.event_type, 0) + 1
        
        # Route to specific handler
        handler = self._handlers.get(event.event_type)
        if handler:
            handler(self, case, event)
    
    def _handle_case_created(self, case: CaseAnalytics, event) -> None:
        """Handle case created."""
        case.created_at = event.occurred_at
        case.status_history.append("active")
        
        self._system_analytics.total_cases += 1
        self._system_analytics.active_cases += 1
        self._system_analytics.cases_by_type[event.case_type] = \
            self._system_analytics.cases_by_type.get(event.case_type, 0) + 1
        self._system_analytics.cases_by_jurisdiction[event.jurisdiction] = \
            self._system_analytics.cases_by_jurisdiction.get(event.jurisdiction, 0) + 1
    
    def _handle_status_changed(self, case: CaseAnalytics, event) -> None:
        """Handle status changed."""
        old_status = event.previous_status
        new_status = event.new_status
        
        case.status_history.append(new_status)
        
        # Update system counts
        if old_status == "active":
            self._system_analytics.active_cases -= 1
        elif old_status == "closed":
            self._system_analytics.closed_cases -= 1
        elif old_status == "archived":
            self._system_analytics.archived_cases -= 1
        
        if new_status == "active":
            self._system_analytics.active_cases += 1
        elif new_status == "closed":
            self._system_analytics.closed_cases += 1
        elif new_status == "archived":
            self._system_analytics.archived_cases += 1
    
    def _handle_document_uploaded(self, case: CaseAnalytics, event) -> None:
        """Handle document uploaded."""
        case.document_count += 1
    
    def _handle_document_deleted(self, case: CaseAnalytics, event) -> None:
        """Handle document deleted."""
        case.document_count = max(0, case.document_count - 1)
    
    def _handle_deadline_set(self, case: CaseAnalytics, event) -> None:
        """Handle deadline set."""
        case.deadline_count += 1
    
    def _handle_note_added(self, case: CaseAnalytics, event) -> None:
        """Handle note added."""
        case.note_count += 1
    
    def _handle_collaborator_added(self, case: CaseAnalytics, event) -> None:
        """Handle collaborator added."""
        case.collaborator_count += 1
    
    def _handle_appeal_filed(self, case: CaseAnalytics, event) -> None:
        """Handle appeal filed."""
        case.appeal_count += 1
    
    def _handle_case_deleted(self, case: CaseAnalytics, event) -> None:
        """Handle case deleted."""
        case.status_history.append("deleted")
        self._system_analytics.active_cases = max(0, self._system_analytics.active_cases - 1)
        self._system_analytics.deleted_cases += 1
    
    def get_case_analytics(self, case_id: str) -> Optional[CaseAnalytics]:
        """Get analytics for a specific case."""
        return self._case_analytics.get(case_id)
    
    def get_system_analytics(self) -> SystemAnalytics:
        """Get system-wide analytics."""
        if not self._initialized:
            return self.rebuild_all()
        return self._system_analytics
    
    def get_recent_activity(self, hours: int = 24) -> int:
        """Get count of events in recent hours."""
        cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)
        
        position = 0
        count = 0
        while True:
            slice = self._event_store.read_all(from_position=position)
            
            if not slice.events:
                break
            
            for event in slice.events:
                if event.occurred_at >= cutoff:
                    count += 1
                elif count > 0:
                    # Events are ordered, so we can stop
                    return count
            
            if not slice.has_more:
                break
            
            position += len(slice.events)
        
        return count
    
    def subscribe_to_events(self) -> None:
        """Subscribe to event store for real-time updates."""
        def handle_event(event: DomainEvent) -> None:
            self._apply_event(event)
        
        self._event_store.subscribe(handle_event)
    
    _handlers = {
        EventType.CASE_CREATED.value: _handle_case_created,
        EventType.CASE_STATUS_CHANGED.value: _handle_status_changed,
        EventType.DOCUMENT_UPLOADED.value: _handle_document_uploaded,
        EventType.DOCUMENT_DELETED.value: _handle_document_deleted,
        EventType.DEADLINE_SET.value: _handle_deadline_set,
        EventType.NOTE_ADDED.value: _handle_note_added,
        EventType.COLLABORATOR_ADDED.value: _handle_collaborator_added,
        EventType.APPEAL_FILED.value: _handle_appeal_filed,
        EventType.CASE_DELETED.value: _handle_case_deleted,
    }