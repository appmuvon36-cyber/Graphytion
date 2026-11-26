from enum import StrEnum
from typing import Protocol

class WorkspaceRole(StrEnum):
    OWNER = "owner"
    ADMIN = "admin"
    EDITOR = "editor"
    VIEWER = "viewer"
    BILLING = "billing"

class WorkspaceAuthorization(Protocol):
    """Port for persistent workspace membership and role enforcement (implemented in Phase 02)."""
    async def require_membership(self, *, user_id: str, workspace_id: str, allowed_roles: set[WorkspaceRole]) -> WorkspaceRole: ...
