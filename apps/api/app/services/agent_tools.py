from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from uuid import UUID

from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.workspace_authorization import WorkspacePermissionResolver


class ToolInput(BaseModel):
    model_config = ConfigDict(extra="forbid")


class BriefInput(ToolInput):
    input_prompt: str = Field(min_length=1, max_length=20000)


class ScriptInput(ToolInput):
    brief_id: UUID


class StoryboardInput(ToolInput):
    script_id: UUID


class SceneInput(ToolInput):
    scene_id: UUID
    revision_instruction: str = Field(min_length=3, max_length=2000)


@dataclass(frozen=True)
class AgentTool:
    key: str
    agent_key: str
    stage: str
    description: str
    permission: str
    input_model: type[ToolInput]


class AgentToolRegistry:
    """Explicit allowlist for model-backed creative tools; no dynamic code execution."""

    def __init__(self) -> None:
        specs = (
            AgentTool("creative.generate_brief", "prompt_interpreter", "brief",
                      "Interpret a user prompt into a structured creative brief.",
                      "project.update", BriefInput),
            AgentTool("creative.write_script", "scriptwriter", "script",
                      "Write a structured narration script from an approved brief.",
                      "project.update", ScriptInput),
            AgentTool("creative.create_storyboard", "story_director", "storyboard",
                      "Create a storyboard from an approved script.",
                      "project.update", StoryboardInput),
            AgentTool("creative.regenerate_scene", "scene_regenerator", "scene",
                      "Regenerate one scene while preserving its approved narrative source.",
                      "project.update", SceneInput),
        )
        self._by_stage = {item.stage: item for item in specs}
        self._by_key = {item.key: item for item in specs}

    def resolve(self, key: str) -> AgentTool:
        tool = self._by_key.get(key)
        if tool is None:
            raise HTTPException(status_code=404, detail="Agent tool is not registered")
        return tool

    def for_stage(self, stage: str) -> AgentTool:
        tool = self._by_stage.get(stage)
        if tool is None:
            raise HTTPException(status_code=422, detail="Creative stage has no registered agent tool")
        return tool

    def validate(self, stage: str, payload: dict[str, Any]) -> dict[str, Any]:
        tool = self.for_stage(stage)
        try:
            return tool.input_model.model_validate(payload).model_dump(mode="json")
        except Exception as exc:
            raise HTTPException(status_code=422, detail="Agent tool input does not match its registered schema") from exc

    def discover(self) -> list[dict[str, Any]]:
        return [{
            "key": tool.key,
            "agent_key": tool.agent_key,
            "stage": tool.stage,
            "description": tool.description,
            "permission": tool.permission,
            "input_schema": tool.input_model.model_json_schema(),
        } for tool in self._by_stage.values()]

    async def authorize(
        self, *, db: AsyncSession, actor: UUID, workspace_id: UUID,
        project_id: UUID, stage: str, payload: dict[str, Any],
    ) -> AgentTool:
        tool = self.for_stage(stage)
        self.validate(stage, payload)
        project_workspace = await db.scalar(text("""
            select workspace_id from public.video_projects
            where id=:project and status <> 'deleted'
        """), {"project": project_id})
        if project_workspace is None or str(project_workspace) != str(workspace_id):
            raise HTTPException(status_code=404, detail="Project is not available in this workspace")
        await self._permissions.require_permission(
            session=db, user_id=str(actor), workspace_id=str(workspace_id),
            permission=tool.permission,
        )
        # Resource identifiers are resolved inside the same project/workspace.
        resource_checks = {
            "script": ("select id from public.creative_briefs where id=:id and project_id=:project and workspace_id=:workspace and status='approved'", "brief_id"),
            "storyboard": ("select id from public.video_scripts where id=:id and project_id=:project and workspace_id=:workspace and status='approved'", "script_id"),
            "scene": ("select sc.id from public.storyboard_scenes sc join public.storyboards sb on sb.id=sc.storyboard_id where sc.id=:id and sc.project_id=:project and sc.workspace_id=:workspace and sb.status <> 'superseded'", "scene_id"),
        }
        if stage in resource_checks:
            query, field = resource_checks[stage]
            resource_id = payload.get(field)
            found = await db.scalar(text(query), {
                "id": resource_id, "project": project_id, "workspace": workspace_id,
            })
            if found is None:
                raise HTTPException(status_code=404, detail="Agent tool resource is not available in this project")
        return tool

    def __init_permissions(self) -> None:
        self._permissions = WorkspacePermissionResolver()


agent_tool_registry = AgentToolRegistry()
agent_tool_registry.__init_permissions()
