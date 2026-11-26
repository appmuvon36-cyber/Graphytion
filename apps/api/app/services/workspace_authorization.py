from enum import StrEnum

from fastapi import HTTPException
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


class WorkspaceRole(StrEnum):
    OWNER = "owner"
    ADMIN = "admin"
    EDITOR = "editor"
    MEMBER = "member"
    VIEWER = "viewer"
    BILLING = "billing"


ROLE_PERMISSIONS: dict[WorkspaceRole, frozenset[str]] = {
    WorkspaceRole.OWNER: frozenset(
        {
            "workspace.read",
            "workspace.update",
            "workspace.delete",
            "member.read",
            "member.manage",
            "project.read",
            "project.create",
            "project.update",
            "project.archive",
            "project.delete",
        }
    ),
    WorkspaceRole.ADMIN: frozenset(
        {
            "workspace.read",
            "workspace.update",
            "member.read",
            "member.manage",
            "project.read",
            "project.create",
            "project.update",
            "project.archive",
            "project.delete",
        }
    ),
    WorkspaceRole.EDITOR: frozenset(
        {
            "workspace.read",
            "member.read",
            "project.read",
            "project.create",
            "project.update",
            "project.archive",
        }
    ),
    WorkspaceRole.MEMBER: frozenset(
        {"workspace.read", "member.read", "project.read", "project.create", "project.update"}
    ),
    WorkspaceRole.VIEWER: frozenset({"workspace.read", "project.read"}),
    WorkspaceRole.BILLING: frozenset({"workspace.read", "billing.read", "billing.manage"}),
}


class WorkspacePermissionResolver:
    """Database-backed tenant membership and role-to-permission resolver."""

    async def require_membership(
        self,
        *,
        session: AsyncSession,
        user_id: str,
        workspace_id: str,
        allowed_roles: set[str] | None = None,
    ) -> str:
        row = (
            (
                await session.execute(
                    text("""
            select role from public.workspace_members
            where user_id=:user_id and workspace_id=:workspace_id and status='active'
        """),
                    {"user_id": user_id, "workspace_id": workspace_id},
                )
            )
            .mappings()
            .first()
        )
        if row is None:
            raise HTTPException(status_code=404, detail="Workspace not found")
        role = str(row["role"])
        if allowed_roles is not None and role not in allowed_roles:
            raise HTTPException(status_code=403, detail="Insufficient workspace permission")
        return role

    async def require_permission(
        self, *, session: AsyncSession, user_id: str, workspace_id: str, permission: str
    ) -> WorkspaceRole:
        role = WorkspaceRole(
            await self.require_membership(
                session=session, user_id=user_id, workspace_id=workspace_id
            )
        )
        if permission not in ROLE_PERMISSIONS[role]:
            raise HTTPException(status_code=403, detail="Insufficient workspace permission")
        return role


workspace_permission_resolver = WorkspacePermissionResolver()
