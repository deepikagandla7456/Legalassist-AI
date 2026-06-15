"""
API Versioning Module

Provides comprehensive API versioning with:
- Version registry with status tracking
- Schema transformers for backward compatibility
- Deprecation middleware with RFC 8594 headers
- Versioned routing

Reference: Issue #2316 - API Versioning Strategy
"""

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
    get_schema_transformer,
    get_enum_transformer,
    transform_request_for_version,
    transform_response_for_version,
)

from api.versioning.deprecation import (
    DeprecationMiddleware,
    DeprecationWarning,
    create_deprecation_response,
    create_version_mismatch_response,
    get_deprecation_warnings_for_response,
)

from api.versioning.router import (
    VersionedRouter,
    VersionResolver,
    VersionedRoute,
    get_requested_version,
    require_version,
    generate_versioned_openapi,
    check_breaking_changes,
)

__all__ = [
    # Registry
    "VersionRegistry",
    "VersionInfo",
    "VersionStatus",
    "UsageStats",
    "get_version_registry",
    "register_custom_version",
    "deprecate_api_version",
    # Transformers
    "SchemaTransformer",
    "EnumTransformer",
    "TransformationType",
    "FieldTransformation",
    "get_schema_transformer",
    "get_enum_transformer",
    "transform_request_for_version",
    "transform_response_for_version",
    # Deprecation
    "DeprecationMiddleware",
    "DeprecationWarning",
    "create_deprecation_response",
    "create_version_mismatch_response",
    "get_deprecation_warnings_for_response",
    # Router
    "VersionedRouter",
    "VersionResolver",
    "VersionedRoute",
    "get_requested_version",
    "require_version",
    "generate_versioned_openapi",
    "check_breaking_changes",
]