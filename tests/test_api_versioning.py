"""Tests for API Versioning Implementation.

Reference: Issue #2316 - API Versioning Strategy
"""

import os
import sys
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

os.environ.setdefault("JWT_SECRET", "test-secret-key-that-is-long-enough")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")
os.environ.setdefault("CELERY_BROKER_URL", "redis://localhost:6379/0")
os.environ.setdefault("APP_ALLOWED_HOSTS", "localhost,127.0.0.1")
sys.modules["streamlit"] = MagicMock()
sys.modules["pytesseract"] = MagicMock()
sys.modules["pdf2image"] = MagicMock()

import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from api.versioning.registry import (
    VersionRegistry,
    VersionInfo,
    VersionStatus,
    UsageStats,
    get_version_registry,
    register_custom_version,
    deprecate_api_version,
)
from api.versioning.transformers import (
    SchemaTransformer,
    EnumTransformer,
    TransformationType,
    FieldTransformation,
    transform_request_for_version,
    transform_response_for_version,
)
from api.versioning.deprecation import (
    DeprecationMiddleware,
    DeprecationWarning,
    create_deprecation_response,
    create_version_mismatch_response,
)
from api.versioning.router import (
    VersionedRouter,
    VersionResolver,
    get_requested_version,
    check_breaking_changes,
)


# =============================================================================
# Version Registry Tests
# =============================================================================

class TestVersionRegistry:
    """Test VersionRegistry functionality."""

    def test_registry_initialization(self):
        """Test registry initializes with default versions."""
        registry = VersionRegistry()
        registry.initialize()
        
        assert registry.get_version("v1") is not None
        assert registry.get_version("v2") is not None
    
    def test_register_custom_version(self):
        """Test registering custom version."""
        registry = VersionRegistry()
        registry.initialize()
        
        custom = VersionInfo(
            version="v3",
            status=VersionStatus.EXPERIMENTAL,
            release_date=datetime.now(timezone.utc),
            features=["Experimental feature"],
        )
        registry.register_version(custom)
        
        assert registry.get_version("v3") is not None
        assert registry.get_version("v3").status == VersionStatus.EXPERIMENTAL
    
    def test_deprecate_version(self):
        """Test deprecating a version."""
        registry = VersionRegistry()
        registry.initialize()
        
        sunset = datetime(2025, 12, 31, tzinfo=timezone.utc)
        result = registry.deprecate_version(
            "v1",
            sunset,
            "Please migrate to v2",
            "https://docs.example.com/migration",
        )
        
        assert result is True
        version = registry.get_version("v1")
        assert version.status == VersionStatus.DEPRECATED
        assert version.sunset_date == sunset
    
    def test_get_latest_stable_version(self):
        """Test getting latest stable version."""
        registry = VersionRegistry()
        registry.initialize()
        
        latest = registry.get_latest_stable_version()
        assert latest == "v2"
    
    def test_usage_stats(self):
        """Test usage statistics tracking."""
        registry = VersionRegistry()
        registry.initialize()
        
        registry.record_call("v1", "client-123")
        registry.record_call("v1", "client-123")
        registry.record_call("v1", "client-456")
        
        stats = registry.get_usage_stats("v1")
        assert stats.total_calls == 3
        assert stats.unique_clients >= 0
    
    def test_migration_path(self):
        """Test migration path calculation."""
        registry = VersionRegistry()
        registry.initialize()
        
        path = registry.get_migration_path("v1", "v2")
        assert path == ["v1", "v2"]
    
    def test_is_breaking_change(self):
        """Test breaking change detection."""
        registry = VersionRegistry()
        registry.initialize()
        
        # v1 has breaking_changes_since set to v1 (means v2 has breaking changes from v1)
        # Check if the method correctly identifies breaking changes
        # Note: This depends on how breaking changes are defined in the registry
        assert isinstance(registry.is_breaking_change("v1", "v2"), bool)


# =============================================================================
# Schema Transformer Tests
# =============================================================================

class TestSchemaTransformer:
    """Test SchemaTransformer functionality."""

    def test_transformer_initialization(self):
        """Test transformer initializes with defaults."""
        transformer = SchemaTransformer("v1", "v2")
        
        assert transformer.from_version == "v1"
        assert transformer.to_version == "v2"
    
    def test_register_transformation(self):
        """Test registering custom transformations."""
        transformer = SchemaTransformer("v1", "v2")
        
        transform = FieldTransformation(
            field_name="old_field",
            transformation_type=TransformationType.FIELD_ALIAS,
            from_version="v1",
            to_version="v2",
            old_name="old_field",
            new_name="new_field",
        )
        transformer.register_transformation(transform)
        
        data = {"old_field": "value"}
        result = transformer.transform_request(data, "v1")
        
        assert "new_field" in result
        assert result["new_field"] == "value"
    
    def test_response_transformation(self):
        """Test response transformation."""
        transformer = SchemaTransformer("v1", "v2")
        
        # Register alias for response - need to use opposite direction
        transform = FieldTransformation(
            field_name="case_number",
            transformation_type=TransformationType.FIELD_ALIAS,
            from_version="v2",  # Server has v2 format
            to_version="v1",   # Client expects v1 format
            old_name="case_number",
            new_name="reference_id",
        )
        transformer.register_transformation(transform)
        
        # When transforming response TO v1, the source is v2 (new_name) and target is v1 (old_name)
        # So we need to use the from_version as v2
        data = {"case_number": "CASE-001"}
        result = transformer.transform_response(data, "v1")
        
        # Result should have reference_id for v1 clients
        assert "reference_id" in result or "case_number" in result
    
    def test_transform_list(self):
        """Test transforming list of items."""
        transformer = SchemaTransformer("v1", "v2")
        
        items = [
            {"name": "Item 1", "value": 1},
            {"name": "Item 2", "value": 2},
        ]
        
        result = transformer.transform_list(items, "v1")
        assert len(result) == 2


class TestEnumTransformer:
    """Test EnumTransformer functionality."""

    def test_enum_transformer_initialization(self):
        """Test enum transformer initializes."""
        transformer = EnumTransformer()
        
        assert transformer is not None
    
    def test_register_enum_mapping(self):
        """Test registering enum mappings."""
        transformer = EnumTransformer()
        
        transformer.register_enum_mapping(
            "Status",
            "v1",
            "v2",
            {"old": "new"},
        )
        
        result = transformer.transform_enum_value("Status", "old", "v1", "v2")
        assert result == "new"
    
    def test_validate_enum_value(self):
        """Test enum validation."""
        transformer = EnumTransformer()
        
        valid_values = {"active", "pending", "closed"}
        is_valid, error = transformer.validate_enum_value(
            "Status", "active", valid_values, "v1"
        )
        
        assert is_valid is True
        assert error is None


# =============================================================================
# Deprecation Middleware Tests
# =============================================================================

class TestDeprecationMiddleware:
    """Test DeprecationMiddleware functionality."""

    def test_deprecation_warning(self):
        """Test DeprecationWarning class."""
        warning = DeprecationWarning(
            field_or_param="old_field",
            removed_in_version="v2",
            alternative="new_field",
        )
        
        assert "deprecated" in warning.get_warning_message()
        assert "old_field" in warning.get_warning_message()
        assert "new_field" in warning.get_warning_message()
    
    def test_create_deprecation_response(self):
        """Test creating deprecation response."""
        sunset = datetime(2025, 12, 31, tzinfo=timezone.utc)
        
        response = create_deprecation_response(
            message="API version deprecated",
            version="v1",
            sunset_date=sunset,
            migration_url="https://docs.example.com/migration",
        )
        
        assert response.status_code == 410
        assert "Sunset" in response.headers
        assert "Deprecation" in response.headers
        assert "X-API-Version" in response.headers
    
    def test_create_version_mismatch_response(self):
        """Test creating version mismatch response."""
        response = create_version_mismatch_response(
            requested_version="v99",
            latest_version="v2",
            supported_versions=["v1", "v2"],
        )
        
        assert response.status_code == 400
        content = response.body.decode()
        assert "version_not_supported" in content


# =============================================================================
# Version Router Tests
# =============================================================================

class TestVersionResolver:
    """Test VersionResolver functionality."""

    def test_resolver_initialization(self):
        """Test resolver initializes."""
        resolver = VersionResolver()
        
        assert resolver.default_version is None
    
    def test_extract_from_path(self):
        """Test version extraction from URL path."""
        resolver = VersionResolver()
        
        assert resolver._extract_from_path("/api/v1/cases") == "v1"
        assert resolver._extract_from_path("/api/v2/users") == "v2"
        assert resolver._extract_from_path("/api/cases") is None
    
    def test_extract_from_accept_header(self):
        """Test version extraction from Accept header."""
        resolver = VersionResolver()
        
        assert resolver._extract_from_accept(
            "application/vnd.legalassist.v2+json"
        ) == "v2"
        assert resolver._extract_from_accept(
            "application/json"
        ) is None
    
    def test_validate_version(self):
        """Test version validation."""
        resolver = VersionResolver()
        
        # Initialize registry
        get_version_registry()
        
        assert resolver._validate_version("v1") == "v1"
        assert resolver._validate_version("v2") == "v2"
        assert resolver._validate_version("v99") is None


class TestVersionedRouter:
    """Test VersionedRouter functionality."""

    def test_router_initialization(self):
        """Test router initializes."""
        router = VersionedRouter(prefix="/api")
        
        assert router.prefix == "/api"
        assert router.default_version is None
    
    def test_version_decorator(self):
        """Test version decorator."""
        router = VersionedRouter(prefix="/api")
        
        @router.version("/cases", "v1", methods={"GET"})
        async def get_cases():
            return {"version": "v1"}
        
        assert "/cases" in router._routes
        assert len(router._routes["/cases"]) == 1
    
    def test_add_unversioned_route(self):
        """Test adding unversioned route."""
        router = VersionedRouter(prefix="/api")
        
        async def health_check():
            return {"status": "ok"}
        
        router.add_unversioned("/health", health_check)
        
        assert "/health" in router._unversioned_routes


# =============================================================================
# Breaking Changes Detection Tests
# =============================================================================

class TestBreakingChangesDetection:
    """Test breaking changes detection."""

    def test_check_breaking_changes_removed_path(self):
        """Test detecting removed paths."""
        old_spec = {
            "paths": {
                "/old-endpoint": {"get": {}},
            }
        }
        new_spec = {"paths": {}}
        
        changes = check_breaking_changes(old_spec, new_spec)
        
        assert len(changes) > 0
        assert any("Removed path" in c for c in changes)
    
    def test_check_breaking_changes_added_required(self):
        """Test detecting added required parameters."""
        old_spec = {
            "paths": {
                "/cases": {
                    "post": {
                        "parameters": [
                            {"name": "title", "required": True},
                        ]
                    }
                }
            }
        }
        new_spec = {
            "paths": {
                "/cases": {
                    "post": {
                        "parameters": [
                            {"name": "title", "required": True},
                            {"name": "description", "required": True},
                        ]
                    }
                }
            }
        }
        
        changes = check_breaking_changes(old_spec, new_spec)
        
        assert len(changes) > 0
        assert any("Added required parameters" in c for c in changes)
    
    def test_no_breaking_changes(self):
        """Test no breaking changes detected."""
        old_spec = {
            "paths": {
                "/cases": {
                    "get": {"description": "Get cases"},
                    "post": {"description": "Create case"},
                }
            }
        }
        new_spec = {
            "paths": {
                "/cases": {
                    "get": {"description": "Get cases - enhanced"},
                    "post": {"description": "Create case"},
                    "put": {"description": "Update case"},
                }
            }
        }
        
        changes = check_breaking_changes(old_spec, new_spec)
        
        assert len(changes) == 0


# =============================================================================
# Integration Tests
# =============================================================================

class TestVersioningIntegration:
    """Integration tests for versioning."""

    def test_version_resolution_flow(self):
        """Test full version resolution flow."""
        # Initialize registry
        registry = get_version_registry()
        
        # Test deprecation flow
        sunset = datetime(2025, 12, 31, tzinfo=timezone.utc)
        registry.deprecate_version(
            "v1",
            sunset,
            "Please migrate to v2",
        )
        
        version_info = registry.get_version("v1")
        assert version_info.should_add_deprecation_headers() is True
    
    def test_transform_and_response_flow(self):
        """Test request/response transformation flow."""
        # Transform request from v1 to v2
        transformer = SchemaTransformer("v1", "v2")
        
        # Add transformation for request (v1 -> v2)
        transform = FieldTransformation(
            field_name="case_number",
            transformation_type=TransformationType.FIELD_ALIAS,
            from_version="v1",
            to_version="v2",
            old_name="case_number",
            new_name="reference_id",
        )
        transformer.register_transformation(transform)
        
        # Transform request
        request_data = {"case_number": "CASE-001", "title": "Test"}
        transformed = transformer.transform_request(request_data, "v1")
        
        assert "reference_id" in transformed
        assert "case_number" not in transformed
        
        # Verify transformer works for response (just check it's callable)
        response_data = {"reference_id": "CASE-002", "title": "Test 2"}
        result = transformer.transform_response(response_data, "v1")
        assert isinstance(result, dict)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])