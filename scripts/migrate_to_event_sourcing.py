#!/usr/bin/env python3
"""
Migration Script: Convert Legacy Data to Event Sourcing

This script migrates existing Case/Document/Timeline/Deadline records
into retroactive events for the event store.

Usage:
    python scripts/migrate_to_event_sourcing.py [--dry-run] [--batch-size=100]

Reference: Issue #2312 - Audit-Grade Immutable Event Sourcing
"""

import argparse
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from config import Config
from database import SessionLocal
from db.base import Base
from db.models import Case, CaseDocument, CaseTimeline, CaseDeadline, CaseNote

from core.domain_events import (
    CaseCreated,
    CaseStatusChanged,
    CaseArchived,
    CaseReopened,
    CaseDeleted,
    DocumentUploaded,
    DocumentDeleted,
    DeadlineSet,
    DeadlineCompleted,
    NoteAdded,
    NoteEdited,
    NoteDeleted,
    EventType,
)
from core.event_store import EventStore, StoredEvent


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)


class MigrationRunner:
    """Runs migration from legacy tables to event store."""
    
    def __init__(self, session, dry_run: bool = False, batch_size: int = 100):
        self._session = session
        self._dry_run = dry_run
        self._batch_size = batch_size
        self._event_store = EventStore(session)
        self._stats = {
            "cases_processed": 0,
            "documents_processed": 0,
            "deadlines_processed": 0,
            "notes_processed": 0,
            "events_created": 0,
            "errors": 0,
        }
    
    def run(self) -> dict:
        """Run the full migration."""
        logger.info("Starting migration to event sourcing...")
        
        if self._dry_run:
            logger.warning("DRY RUN MODE - No changes will be persisted")
        
        # Ensure event store tables exist
        self._ensure_tables()
        
        # Migrate cases
        self._migrate_cases()
        
        # Migrate documents
        self._migrate_documents()
        
        # Migrate deadlines
        self._migrate_deadlines()
        
        # Migrate notes
        self._migrate_notes()
        
        if not self._dry_run:
            self._session.commit()
            logger.info("Migration completed successfully")
        else:
            logger.info("Dry run completed - no changes persisted")
        
        return self._stats
    
    def _ensure_tables(self) -> None:
        """Ensure event store tables exist."""
        from core.event_store import Base as EventStoreBase
        
        try:
            EventStoreBase.metadata.create_all(self._session.get_bind())
            logger.info("Event store tables verified/created")
        except Exception as e:
            logger.error(f"Failed to create event store tables: {e}")
            raise
    
    def _migrate_cases(self) -> None:
        """Migrate cases to events."""
        logger.info("Migrating cases...")
        
        cases = self._session.query(Case).all()
        
        for case in cases:
            try:
                # Check if already migrated
                existing = self._session.query(StoredEvent).filter(
                    StoredEvent.aggregate_id == str(case.id),
                    StoredEvent.event_type == EventType.CASE_CREATED.value,
                ).first()
                
                if existing:
                    logger.debug(f"Case {case.id} already migrated, skipping")
                    continue
                
                # Create CaseCreated event
                created_event = CaseCreated(
                    aggregate_id=str(case.id),
                    user_id=case.user_id,
                    case_number=case.case_number or f"CASE-{case.id}",
                    case_type=case.case_type or "unknown",
                    title=case.title or "Untitled",
                    description=case.description or "",
                    jurisdiction=case.jurisdiction or "",
                )
                
                self._event_store.append(created_event)
                self._stats["events_created"] += 1
                
                # Create status change event if not active
                if case.status and case.status != "active":
                    status_event = CaseStatusChanged(
                        aggregate_id=str(case.id),
                        previous_status="active",
                        new_status=case.status.value if hasattr(case.status, 'value') else str(case.status),
                        changed_by=case.user_id,
                        reason="Initial status from migration",
                    )
                    self._event_store.append(status_event)
                    self._stats["events_created"] += 1
                
                # Handle archived status
                if hasattr(case, 'is_archived') and case.is_archived:
                    archived_event = CaseArchived(
                        aggregate_id=str(case.id),
                        archived_by=case.user_id,
                        reason="Archived before event sourcing migration",
                    )
                    self._event_store.append(archived_event)
                    self._stats["events_created"] += 1
                
                # Handle deleted status
                if hasattr(case, 'is_deleted') and case.is_deleted:
                    deleted_event = CaseDeleted(
                        aggregate_id=str(case.id),
                        deleted_by=case.user_id,
                        reason="Deleted before event sourcing migration",
                        deletion_type="soft",
                    )
                    self._event_store.append(deleted_event)
                    self._stats["events_created"] += 1
                
                self._stats["cases_processed"] += 1
                
                if self._stats["cases_processed"] % self._batch_size == 0:
                    logger.info(f"Processed {self._stats['cases_processed']} cases...")
                    if not self._dry_run:
                        self._session.commit()
                
            except Exception as e:
                logger.error(f"Error migrating case {case.id}: {e}")
                self._stats["errors"] += 1
        
        logger.info(f"Cases migration complete: {self._stats['cases_processed']} cases, {self._stats['events_created']} events")
    
    def _migrate_documents(self) -> None:
        """Migrate documents to events."""
        logger.info("Migrating documents...")
        
        documents = self._session.query(CaseDocument).all()
        
        for doc in documents:
            try:
                # Check if already migrated
                existing = self._session.query(StoredEvent).filter(
                    StoredEvent.aggregate_id == str(doc.case_id),
                    StoredEvent.event_type == EventType.DOCUMENT_UPLOADED.value,
                    StoredEvent.payload.contains({"document_id": doc.id}),
                ).first()
                
                if existing:
                    continue
                
                uploaded_event = DocumentUploaded(
                    aggregate_id=str(doc.case_id),
                    document_id=doc.id,
                    document_type=str(doc.document_type.value if hasattr(doc.document_type, 'value') else doc.document_type) if doc.document_type else "unknown",
                    file_name=doc.file_path or "unknown",
                    uploaded_by=doc.uploaded_by or 0,
                    summary=doc.summary or "",
                )
                
                self._event_store.append(uploaded_event)
                self._stats["documents_processed"] += 1
                self._stats["events_created"] += 1
                
            except Exception as e:
                logger.error(f"Error migrating document {doc.id}: {e}")
                self._stats["errors"] += 1
        
        logger.info(f"Documents migration complete: {self._stats['documents_processed']} documents")
    
    def _migrate_deadlines(self) -> None:
        """Migrate deadlines to events."""
        logger.info("Migrating deadlines...")
        
        deadlines = self._session.query(CaseDeadline).all()
        
        for deadline in deadlines:
            try:
                # Check if already migrated
                existing = self._session.query(StoredEvent).filter(
                    StoredEvent.aggregate_id == str(deadline.case_id),
                    StoredEvent.event_type == EventType.DEADLINE_SET.value,
                ).first()
                
                if existing:
                    continue
                
                deadline_event = DeadlineSet(
                    aggregate_id=str(deadline.case_id),
                    deadline_id=deadline.id,
                    deadline_type=deadline.deadline_type or "unknown",
                    deadline_date=deadline.deadline_date.isoformat() if deadline.deadline_date else "",
                    description=deadline.description or "",
                    set_by=deadline.user_id or 0,
                )
                
                self._event_store.append(deadline_event)
                self._stats["deadlines_processed"] += 1
                self._stats["events_created"] += 1
                
                # Handle completed deadlines
                if deadline.completed:
                    completed_event = DeadlineCompleted(
                        aggregate_id=str(deadline.case_id),
                        deadline_id=deadline.id,
                        completed_by=deadline.user_id or 0,
                        completion_notes="Completed before event sourcing migration",
                    )
                    self._event_store.append(completed_event)
                    self._stats["events_created"] += 1
                
            except Exception as e:
                logger.error(f"Error migrating deadline {deadline.id}: {e}")
                self._stats["errors"] += 1
        
        logger.info(f"Deadlines migration complete: {self._stats['deadlines_processed']} deadlines")
    
    def _migrate_notes(self) -> None:
        """Migrate notes to events."""
        logger.info("Migrating notes...")
        
        notes = self._session.query(CaseNote).all()
        
        for note in notes:
            try:
                # Check if already migrated
                existing = self._session.query(StoredEvent).filter(
                    StoredEvent.aggregate_id == str(note.case_id),
                    StoredEvent.event_type == EventType.NOTE_ADDED.value,
                ).first()
                
                if existing:
                    continue
                
                note_event = NoteAdded(
                    aggregate_id=str(note.case_id),
                    note_id=note.id,
                    content=note.content or "",
                    added_by=note.user_id or 0,
                )
                
                self._event_store.append(note_event)
                self._stats["notes_processed"] += 1
                self._stats["events_created"] += 1
                
            except Exception as e:
                logger.error(f"Error migrating note {note.id}: {e}")
                self._stats["errors"] += 1
        
        logger.info(f"Notes migration complete: {self._stats['notes_processed']} notes")
    
    def rollback(self) -> None:
        """Rollback migration (delete migrated events)."""
        if self._dry_run:
            logger.warning("Cannot rollback in dry run mode")
            return
        
        logger.warning("Rolling back migration...")
        
        # Delete all events created during migration
        # (In production, you'd want to track which events were created by migration)
        self._session.query(StoredEvent).filter(
            StoredEvent.event_id.like("migration-%")
        ).delete()
        
        self._session.commit()
        logger.info("Rollback complete")


def main():
    parser = argparse.ArgumentParser(description="Migrate legacy data to event sourcing")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Run without persisting changes"
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=100,
        help="Batch size for processing"
    )
    
    args = parser.parse_args()
    
    # Create session
    session = SessionLocal()
    
    try:
        runner = MigrationRunner(
            session,
            dry_run=args.dry_run,
            batch_size=args.batch_size
        )
        
        stats = runner.run()
        
        print("\n" + "=" * 50)
        print("MIGRATION SUMMARY")
        print("=" * 50)
        print(f"Cases processed:    {stats['cases_processed']}")
        print(f"Documents processed: {stats['documents_processed']}")
        print(f"Deadlines processed: {stats['deadlines_processed']}")
        print(f"Notes processed:     {stats['notes_processed']}")
        print(f"Events created:      {stats['events_created']}")
        print(f"Errors:              {stats['errors']}")
        print("=" * 50)
        
        if stats['errors'] > 0:
            sys.exit(1)
        
    finally:
        session.close()


if __name__ == "__main__":
    main()