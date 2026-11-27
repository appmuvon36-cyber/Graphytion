from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.workspace_authorization import WorkspacePermissionResolver

HANDLER_STAGE = {
    "creative.generate_brief": "brief",
    "creative.write_script": "script",
    "creative.create_storyboard": "storyboard",
    "creative.regenerate_scene": "scene",
}


@dataclass(frozen=True)
class AgentTool:
    id: UUID
    key: str
    agent_key: str
    stage: str
    handler_key: str
    description: str
    permission: str
    input_schema: dict[str, Any]
    configuration: dict[str, Any]
    version: int


def _validate(schema: dict[str, Any], value: Any, path: str = "$") -> str | None:
    kind = schema.get("type", "object")
    checks = {
        "object": lambda v: isinstance(v, dict),
        "array": lambda v: isinstance(v, list),
        "string": lambda v: isinstance(v, str),
        "integer": lambda v: isinstance(v, int) and not isinstance(v, bool),
        "number": lambda v: isinstance(v, (int, float)) and not isinstance(v, bool),
        "boolean": lambda v: isinstance(v, bool),
        "null": lambda v: v is None,
    }
    if kind not in checks or not checks[kind](value):
        return f"{path}: expected {kind}"
    if "enum" in schema and value not in schema["enum"]:
        return f"{path}: value is not in enum"
    if kind == "string" and not int(schema.get("minLength", 0)) <= len(value) <= int(schema.get("maxLength", 20000)):
        return f"{path}: string length outside limits"
    if kind in {"integer", "number"}:
        if "minimum" in schema and value < schema["minimum"]:
            return f"{path}: below minimum"
        if "maximum" in schema and value > schema["maximum"]:
            return f"{path}: above maximum"
    if kind == "array":
        if len(value) > int(schema.get("maxItems", 1000)):
            return f"{path}: too many items"
        for i, item in enumerate(value):
            error = _validate(schema.get("items", {}), item, f"{path}[{i}]")
            if error:
                return error
    if kind == "object":
        props = schema.get("properties", {})
        if not isinstance(props, dict):
            return f"{path}: malformed properties"
        if any(key not in value for key in schema.get("required", [])):
            return f"{path}: required property missing"
        if schema.get("additionalProperties", False) is False and set(value) - set(props):
            return f"{path}: additional properties are not allowed"
        for key, item in value.items():
            if key in props:
                error = _validate(props[key], item, f"{path}.{key}")
                if error:
                    return error
    return None


class AgentToolRegistry:
    """Persisted registry; handler execution remains a strict backend allowlist."""

    def __init__(self) -> None:
        self._permissions = WorkspacePermissionResolver()

    @staticmethod
    def _tool(row: Any) -> AgentTool:
        handler, stage = str(row["handler_key"]), str(row["stage"])
        if HANDLER_STAGE.get(handler) != stage:
            raise HTTPException(409, "Registered handler is not valid for this stage")
        return AgentTool(
            id=row["id"], key=row["tool_key"], agent_key=row["agent_key"],
            stage=stage, handler_key=handler, description=row["description"],
            permission=row["permission_key"], input_schema=row["input_schema"] or {},
            configuration=row["configuration"] or {}, version=int(row["version"]),
        )

    async def _allowed(self, *, db: AsyncSession, actor: UUID, workspace_id: UUID,
                       tool: AgentTool, resource_id: str | None = None) -> bool:
        await self._permissions.require_membership(
            session=db, user_id=str(actor), workspace_id=str(workspace_id))
        principals = [("user", str(actor)), ("workspace", str(workspace_id)),
                      ("agent", tool.agent_key), ("tool", tool.key)]
        if resource_id:
            principals.append(("resource", resource_id))
        effects = (await db.execute(text("""
            select effect from public.agent_tool_permissions
            where workspace_id=:workspace and (tool_key is null or tool_key in (:tool,'*'))
              and revoked_at is null and valid_from<=now()
              and (expires_at is null or expires_at>now())
              and (principal_type,principal_id) in
                (select * from unnest(cast(:types as text[]),cast(:ids as text[])))
              and permission_key in (:permission,'*')
        """), {"workspace": workspace_id, "tool": tool.key,
               "types": [p[0] for p in principals], "ids": [p[1] for p in principals],
               "permission": tool.permission})).scalars().all()
        if "deny" in effects:
            return False
        if "allow" in effects:
            return True
        try:
            await self._permissions.require_permission(
                session=db, user_id=str(actor), workspace_id=str(workspace_id),
                permission=tool.permission)
            return True
        except HTTPException as exc:
            if exc.status_code == 403:
                return False
            raise

    async def for_stage(self, *, db: AsyncSession, workspace_id: UUID, stage: str) -> AgentTool:
        if stage not in HANDLER_STAGE.values():
            raise HTTPException(422, "Unsupported creative stage")
        row = (await db.execute(text("""
            select id,tool_key,agent_key,stage,handler_key,description,permission_key,
                   input_schema,configuration,version
            from public.agent_tool_registry
            where stage=:stage and is_active=true
              and (workspace_id=:workspace or workspace_id is null)
            order by (workspace_id is not null) desc,version desc,created_at desc limit 1
        """), {"stage": stage, "workspace": workspace_id})).mappings().first()
        if row is None:
            raise HTTPException(503, "No active tool is registered for this stage")
        return self._tool(row)

    def validate(self, tool: AgentTool, payload: dict[str, Any]) -> dict[str, Any]:
        error = _validate(tool.input_schema, payload)
        if error:
            raise HTTPException(422, detail={"code": "AGENT_TOOL_INPUT_INVALID", "message": error})
        return payload

    async def discover(self, *, db: AsyncSession, actor: UUID, workspace_id: UUID) -> list[dict[str, Any]]:
        rows = (await db.execute(text("""
            select id,tool_key,agent_key,stage,handler_key,description,permission_key,
                   input_schema,configuration,version
            from public.agent_tool_registry
            where is_active=true and (workspace_id=:workspace or workspace_id is null)
            order by stage,(workspace_id is not null) desc,version desc,created_at desc
        """), {"workspace": workspace_id})).mappings().all()
        result = {}
        for row in rows:
            tool = self._tool(row)
            if tool.stage in result:
                continue
            if await self._allowed(db=db, actor=actor, workspace_id=workspace_id, tool=tool):
                result[tool.stage] = {
                    "id": str(tool.id), "key": tool.key, "agent_key": tool.agent_key,
                    "stage": tool.stage, "handler_key": tool.handler_key,
                    "description": tool.description, "permission": tool.permission,
                    "input_schema": tool.input_schema, "configuration": tool.configuration,
                    "version": tool.version,
                }
        return list(result.values())

    async def authorize(self, *, db: AsyncSession, actor: UUID, workspace_id: UUID,
                        project_id: UUID, stage: str, payload: dict[str, Any]) -> AgentTool:
        tool = await self.for_stage(db=db, workspace_id=workspace_id, stage=stage)
        self.validate(tool, payload)
        project_workspace = await db.scalar(text("""
            select workspace_id from public.video_projects
            where id=:project and status<>'deleted'
        """), {"project": project_id})
        if project_workspace is None or str(project_workspace) != str(workspace_id):
            raise HTTPException(404, "Project is not available in this workspace")
        resource_fields = {"script": "brief_id", "storyboard": "script_id", "scene": "scene_id"}
        resource_id = str(payload[resource_fields[stage]]) if stage in resource_fields and payload.get(resource_fields[stage]) else None
        if not await self._allowed(db=db, actor=actor, workspace_id=workspace_id,
                                   tool=tool, resource_id=resource_id):
            raise HTTPException(403, "Agent tool permission denied")
        resource_checks = {
            "script": ("select id from public.creative_briefs where id=:id and project_id=:project and workspace_id=:workspace and status='approved'", "brief_id"),
            "storyboard": ("select id from public.video_scripts where id=:id and project_id=:project and workspace_id=:workspace and status='approved'", "script_id"),
            "scene": ("select sc.id from public.storyboard_scenes sc join public.storyboards sb on sb.id=sc.storyboard_id where sc.id=:id and sc.project_id=:project and sc.workspace_id=:workspace and sb.status<>'superseded'", "scene_id"),
        }
        if stage in resource_checks:
            query, field = resource_checks[stage]
            found = await db.scalar(text(query), {"id": payload.get(field),
                "project": project_id, "workspace": workspace_id})
            if found is None:
                raise HTTPException(404, "Agent tool resource is not available in this project")
        return tool


agent_tool_registry = AgentToolRegistry()
