"""
API Versioned Router

Provides version-aware routing with:
- URL-based versioning (/api/v1/*, /api/v2/*)
- Accept header fallback (application/vnd.legalassist.v2+json)
- X-API-Version header fallback
- Default to latest stable version

Reference: Issue #2316 - API Versioning Strategy
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Set, Union
import logging

from fastapi import APIRouter, Request, Response
from fastapi.routing import APIRoute
from starlette.responses import JSONResponse

from api.versioning.registry import get_version_registry, VersionStatus
from api.versioning.transformers import (
    get_schema_transformer,
    transform_request_for_version,
    transform_response_for_version,
)
from api.versioning.deprecation import create_version_mismatch_response

logger = logging.getLogger(__name__)


# Header names
ACCEPT_HEADER = "Accept"
API_VERSION_HEADER = "X-API-Version"


@dataclass
class VersionedRoute:
    """A route with version information."""
    path: str
    version: str
    handler: Callable
    methods: Set[str] = field(default_factory=lambda: {"GET"})
    summary: str = ""
    description: str = ""
    deprecated: bool = False
    deprecation_message: Optional[str] = None


class VersionResolver:
    """
    Resolves API version from multiple sources with priority:
    1. URL path (/api/v2/...)
    2. X-API-Version header
    3. Accept header (application/vnd.legalassist.v2+json)
    4. Default to latest stable
    """
    
    # Accept header pattern
    ACCEPT_PATTERN = re.compile(
        r'application/vnd\.legalassist\.v(\d+)\+json'
    )
    
    def __init__(self, default_version: Optional[str] = None):
        self.default_version = default_version
    
    def resolve_version(
        self,
        request: Request,
        path: str,
    ) -> tuple[str, str]:
        """
        Resolve API version from request.
        
        Returns (version, resolution_method)
        """
        # 1. Check URL path
        path_version = self._extract_from_path(path)
        if path_version:
            return path_version, "url_path"
        
        # 2. Check X-API-Version header
        header_version = request.headers.get(API_VERSION_HEADER)
        if header_version:
            validated = self._validate_version(header_version)
            if validated:
                return validated, "header"
        
        # 3. Check Accept header
        accept_header = request.headers.get(ACCEPT_HEADER, "")
        accept_version = self._extract_from_accept(accept_header)
        if accept_version:
            return accept_version, "accept_header"
        
        # 4. Default to latest stable or configured default
        registry = get_version_registry()
        if self.default_version:
            return self.default_version, "default"
        return registry.get_latest_stable_version(), "default"
    
    def _extract_from_path(self, path: str) -> Optional[str]:
        """Extract version from URL path."""
        match = re.match(r"^/api/(v\d+)/", path)
        if match:
            return match.group(1)
        return None
    
    def _extract_from_accept(self, accept_header: str) -> Optional[str]:
        """Extract version from Accept header."""
        match = self.ACCEPT_PATTERN.search(accept_header)
        if match:
            return f"v{match.group(1)}"
        return None
    
    def _validate_version(self, version: str) -> Optional[str]:
        """Validate and normalize version string."""
        registry = get_version_registry()
        
        # Normalize version
        if not version.startswith("v"):
            version = f"v{version}"
        
        # Check if version exists
        if registry.get_version(version):
            return version
        
        return None


class VersionedRouter:
    """
    API Router with built-in versioning support.
    
    Usage:
        router = VersionedRouter(prefix="/api")
        
        @router.version("/cases", "v1", methods=["GET"])
        async def get_cases_v1(request: Request):
            ...
        
        @router.version("/cases", "v2", methods=["GET"])
        async def get_cases_v2(request: Request):
            ...
    """
    
    def __init__(
        self,
        prefix: str = "/api",
        default_version: Optional[str] = None,
        add_deprecation_headers: bool = True,
    ):
        self.prefix = prefix
        self.default_version = default_version
        self.add_deprecation_headers = add_deprecation_headers
        
        self._version_resolver = VersionResolver(default_version)
        self._routes: Dict[str, List[VersionedRoute]] = {}
        self._unversioned_routes: Dict[str, Callable] = {}
        self._routers: Dict[str, APIRouter] = {}
    
    def version(
        self,
        path: str,
        version: str,
        methods: Optional[Set[str]] = None,
        **kwargs,
    ) -> Callable:
        """Decorator to register a versioned route."""
        def decorator(func: Callable) -> Callable:
            route = VersionedRoute(
                path=path,
                version=version,
                handler=func,
                methods=methods or {"GET"},
                **kwargs,
            )
            
            key = self._normalize_path(path)
            if key not in self._routes:
                self._routes[key] = []
            self._routes[key].append(route)
            
            return func
        return decorator
    
    def add_unversioned(self, path: str, handler: Callable, methods: Optional[Set[str]] = None) -> None:
        """Add an unversioned route (available to all versions)."""
        key = self._normalize_path(path)
        self._unversioned_routes[key] = handler
    
    def include_versioned_router(
        self,
        router: APIRouter,
        version: str,
        prefix: str = "",
    ) -> None:
        """Include an existing APIRouter for a specific version."""
        if version not in self._routers:
            self._routers[version] = APIRouter()
        # Copy routes from the provided router
        for route in router.routes:
            if hasattr(route, 'path'):
                self._routers[version].routes.append(route)
    
    def _normalize_path(self, path: str) -> str:
        """Normalize path for routing."""
        path = path.strip("/")
        return f"/{path}"
    
    def get_handler(
        self,
        request: Request,
    ) -> tuple[Optional[Callable], Optional[str], dict]:
        """
        Get the appropriate handler for a request.
        
        Returns (handler, version, route_kwargs)
        """
        path = request.url.path
        
        # Extract the route path (without /api/v1/ prefix)
        route_path = self._extract_route_path(path)
        normalized = self._normalize_path(route_path)
        
        # Resolve version
        version, resolution_method = self._version_resolver.resolve_version(request, path)
        
        # Find matching route for this version
        routes = self._routes.get(normalized, [])
        for route in routes:
            if route.version == version:
                return route.handler, version, {}
        
        # If exact version not found, try unversioned
        if normalized in self._unversioned_routes:
            return self._unversioned_routes[normalized], version, {}
        
        # Try fallback to default version
        if self.default_version and version != self.default_version:
            for route in routes:
                if route.version == self.default_version:
                    return route.handler, self.default_version, {}
        
        return None, version, {}
    
    def _extract_route_path(self, full_path: str) -> str:
        """Extract route path without version prefix."""
        # Remove /api prefix
        if full_path.startswith("/api/"):
            path = full_path[4:]
        else:
            path = full_path
        
        # Remove version prefix
        match = re.match(r"^/v\d+(.*)$", path)
        if match:
            return match.group(1) or "/"
        
        return path
    
    def add_deprecation_headers_to_response(
        self,
        response: Response,
        version: str,
    ) -> None:
        """Add deprecation headers if needed."""
        if not self.add_deprecation_headers:
            return
        
        registry = get_version_registry()
        version_info = registry.get_version(version)
        
        if version_info and version_info.should_add_deprecation_headers():
            if version_info.sunset_date:
                response.headers["Sunset"] = version_info.sunset_date.strftime(
                    "%a, %d %b %Y %H:%M:%S GMT"
                )
            response.headers["Deprecation"] = "true"
            response.headers["X-API-Version"] = version


# =============================================================================
# Version-Aware Route Dependency
# =============================================================================

async def get_requested_version(request: Request) -> str:
    """
    Dependency to get the requested API version.
    
    Use in route handlers to determine which version the client expects.
    """
    resolver = VersionResolver()
    version, _ = resolver.resolve_version(request, request.url.path)
    return version


async def require_version(min_version: str) -> Callable:
    """Dependency factory to require minimum API version."""
    async def check_version(request: Request) -> str:
        resolver = VersionResolver()
        version, _ = resolver.resolve_version(request, request.url.path)
        
        registry = get_version_registry()
        current = resolver._validate_version(version)
        minimum = resolver._validate_version(min_version)
        
        if current and minimum:
            migration_path = registry.get_migration_path(current, minimum)
            if migration_path is None:
                raise ValueError(
                    f"API version {version} is not supported. "
                    f"Please upgrade to {min_version} or higher."
                )
        
        return version
    
    return check_version


# =============================================================================
# OpenAPI Schema Versioning
# =============================================================================

def generate_versioned_openapi(
    title: str,
    description: str,
    version: str,
    routes: List[VersionedRoute],
) -> dict:
    """Generate OpenAPI schema for a specific version."""
    return {
        "openapi": "3.0.0",
        "info": {
            "title": f"{title} ({version})",
            "description": description,
            "version": version,
        },
        "paths": {
            route.path: {
                method.lower(): {
                    "summary": route.summary,
                    "description": route.description,
                    "deprecated": route.deprecated,
                    "responses": {
                        "200": {"description": "Success"},
                        "400": {"description": "Bad Request"},
                        "401": {"description": "Unauthorized"},
                    },
                }
                for method in route.methods
            }
            for route in routes
        },
    }


def check_breaking_changes(
    old_spec: dict,
    new_spec: dict,
) -> List[str]:
    """
    Check for breaking changes between two OpenAPI specs.
    
    Returns list of breaking changes found.
    """
    breaking_changes = []
    
    old_paths = old_spec.get("paths", {})
    new_paths = new_spec.get("paths", {})
    
    # Check for removed paths
    for path in old_paths:
        if path not in new_paths:
            breaking_changes.append(f"Removed path: {path}")
    
    # Check for changed methods
    for path, methods in old_paths.items():
        if path in new_paths:
            for method, spec in methods.items():
                if method not in new_paths[path]:
                    breaking_changes.append(f"Removed {method.upper()} on {path}")
                
                # Check required parameters
                old_params = spec.get("parameters", [])
                new_params = new_paths[path].get(method, {}).get("parameters", [])
                
                old_required = {p["name"] for p in old_params if p.get("required")}
                new_required = {p["name"] for p in new_params if p.get("required")}
                
                added_required = new_required - old_required
                if added_required:
                    breaking_changes.append(
                        f"Added required parameters on {path}: {added_required}"
                    )
    
    return breaking_changes