"""
Projections for Event Sourcing

Projections rebuild read models from event streams.
All projections are rebuildable from the event log.

Reference: Issue #2312 - Audit-Grade Immutable Event Sourcing
"""

from core.domain_events import DomainEvent

__all__ = [
    "CaseDetailProjection",
    "TimelineProjection",
    "AnalyticsProjection",
    "SearchProjection",
]