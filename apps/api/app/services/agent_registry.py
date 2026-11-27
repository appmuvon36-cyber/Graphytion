from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


STAGE_AGENT_KEYS: dict[str, tuple[str, ...]] = {
    "brief": ("prompt_interpreter",),
    "script": ("scriptwriter",),
    "storyboard": ("story_director", "storyboard_director"),
    "scene": ("scene_regenerator",),
}
AGENT_CONTRACTS = {
    "prompt_interpreter": ("creative_pipeline.interpret_prompt", "CreativeBriefOutput", 1),
    "scriptwriter": ("creative_pipeline.write_script", "ScriptOutput", 1),
    "story_director": ("creative_pipeline.direct_story", "StoryArcOutput", 1),
    "storyboard_director": ("creative_pipeline.direct_storyboard", "StoryboardOutput", 1),
    "scene_regenerator": ("creative_pipeline.regenerate_scene", "StoryboardSceneOutput", 1),
}


@dataclass(frozen=True)
class AgentProfile:
    agent_key: str
    display_name: str
    stage_key: str
    execution_handler: str
    output_schema_key: str
    prompt_version: int
    permission_key: str


class AgentRegistry:
    """Persisted canonical agent registry; execution handlers remain code-allowlisted."""

    async def resolve(self, *, db: AsyncSession, agent_key: str, stage: str) -> AgentProfile:
        row = (await db.execute(text("""
            select agent_key,display_name,stage_key,execution_handler,output_schema_key,
                   prompt_version,permission_key,is_enabled
            from public.agent_registry where agent_key=:agent
        """), {"agent": agent_key})).mappings().first()
        if row is None or not row["is_enabled"]:
            raise HTTPException(503, f"Agent {agent_key} is not enabled in the canonical registry")
        if row["stage_key"] != stage:
            raise HTTPException(409, "Registered agent stage does not match the requested workflow stage")
        contract = AGENT_CONTRACTS.get(agent_key)
        if contract is None or (
            row["execution_handler"], row["output_schema_key"], int(row["prompt_version"])
        ) != contract:
            raise HTTPException(409, "Agent registry contract does not match the deployed structured handler")
        return AgentProfile(
            agent_key=row["agent_key"], display_name=row["display_name"],
            stage_key=row["stage_key"], execution_handler=row["execution_handler"],
            output_schema_key=row["output_schema_key"], prompt_version=int(row["prompt_version"]),
            permission_key=row["permission_key"],
        )


agent_registry = AgentRegistry()
