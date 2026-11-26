from enum import StrEnum
class WorkspaceRole(StrEnum):
    OWNER="owner"
    ADMIN="admin"
    EDITOR="editor"
    VIEWER="viewer"
    BILLING="billing"
class WorkspaceAuthorization:
    """Authorization port; Phase 02 implements persisted workspace membership queries."""
    async def require_membership(self, *, user_id: str, workspace_id: str, allowed_roles: set[WorkspaceRole]) -> WorkspaceRole:
        raise NotImplementedError("Persistent membership authorization is implemented in Phase 02.")
