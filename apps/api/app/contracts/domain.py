from datetime import datetime
from enum import StrEnum
from typing import Any
from uuid import UUID
from pydantic import Field
from app.contracts.common import StrictModel

class WorkspaceRole(StrEnum): OWNER="owner"; ADMIN="admin"; EDITOR="editor"; VIEWER="viewer"; BILLING="billing"
class ProjectStatus(StrEnum): DRAFT="draft"; ACTIVE="active"; ARCHIVED="archived"; DELETED="deleted"
class TaskStatus(StrEnum): PENDING="pending"; QUEUED="queued"; RUNNING="running"; SUCCEEDED="succeeded"; FAILED="failed"; RETRY_WAIT="retry_wait"; CANCELLED="cancelled"; SKIPPED="skipped"
class RenderStatus(StrEnum): QUEUED="queued"; PREPARING="preparing"; RENDERING="rendering"; UPLOADING="uploading"; VALIDATING="validating"; COMPLETED="completed"; FAILED="failed"; CANCEL_REQUESTED="cancel_requested"; CANCELLED="cancelled"

class WorkspaceContract(StrictModel): id: UUID; name: str = Field(min_length=1,max_length=120); slug: str; owner_user_id: UUID; created_at: datetime; updated_at: datetime
class MembershipContract(StrictModel): id: UUID; workspace_id: UUID; user_id: UUID; role: WorkspaceRole; status: str; created_at: datetime
class VideoProjectContract(StrictModel): id: UUID; workspace_id: UUID; created_by: UUID; name: str; production_mode: str; status: ProjectStatus; default_language: str; aspect_ratio: str; width: int = Field(gt=0); height: int = Field(gt=0); fps: int = Field(ge=1,le=120); created_at: datetime; updated_at: datetime
class CreativeBriefContract(StrictModel): id: UUID; project_id: UUID; version: int = Field(ge=1); input_prompt: str; normalized_brief: dict[str,Any]; created_at: datetime
class ScriptContract(StrictModel): id: UUID; project_id: UUID; version: int = Field(ge=1); language: str; title: str; body: dict[str,Any]; created_at: datetime
class StoryboardSceneContract(StrictModel): id: UUID; scene_index: int = Field(ge=0); title: str; duration_ms: int = Field(gt=0); visual_direction: dict[str,Any]; motion_plan: dict[str,Any]
class ProductionRunContract(StrictModel): id: UUID; project_id: UUID; workspace_id: UUID; status: str; progress_percent: float = Field(ge=0,le=100); created_at: datetime
class AgentTaskContract(StrictModel): id: UUID; production_run_id: UUID; agent_key: str; status: TaskStatus; attempt_count: int = Field(ge=0)
class MediaAssetContract(StrictModel): id: UUID; workspace_id: UUID; project_id: UUID | None; asset_type: str; storage_bucket: str; storage_path: str; mime_type: str; file_size_bytes: int = Field(ge=0)
class TimelineClipContract(StrictModel): id: UUID; track_id: UUID; clip_type: str; start_frame: int = Field(ge=0); duration_frames: int = Field(gt=0); component_key: str | None = None; props: dict[str,Any] = Field(default_factory=dict)
class TimelineContract(StrictModel): id: UUID; project_id: UUID; version: int = Field(ge=1); fps: int = Field(ge=1,le=120); width: int = Field(gt=0); height: int = Field(gt=0); duration_frames: int = Field(gt=0); clips: list[TimelineClipContract]
class RenderJobContract(StrictModel): id: UUID; project_id: UUID; workspace_id: UUID; timeline_id: UUID; status: RenderStatus; progress_percent: float = Field(ge=0,le=100)
class UsageContract(StrictModel): id: UUID; workspace_id: UUID; provider_key: str; model_key: str; currency: str = Field(min_length=3,max_length=3); created_at: datetime
class AuditContract(StrictModel): id: UUID; actor_user_id: UUID | None; action: str; resource_type: str; resource_id: UUID | None; created_at: datetime

class VoiceProfileContract(StrictModel): provider_key: str; voice_key: str; display_name: str; language: str
class AudioGenerationContract(StrictModel): id: UUID; project_id: UUID; scene_id: UUID | None; provider_key: str; voice_key: str; status: TaskStatus; created_at: datetime
class SubtitleSegmentContract(StrictModel): id: UUID; segment_index: int = Field(ge=0); text: str; start_ms: int = Field(ge=0); end_ms: int = Field(gt=0)
class SubtitleTrackContract(StrictModel): id: UUID; project_id: UUID; language: str; version: int = Field(ge=1); status: TaskStatus; segments: list[SubtitleSegmentContract]
class WorkflowCheckpointContract(StrictModel): id: UUID; production_run_id: UUID; stage_key: str; checkpoint_key: str; content_hash: str; payload: dict[str,Any]
class MotionComponentContract(StrictModel): component_key: str; version: str; category: str; props_schema: dict[str,Any]; enabled: bool
class CompositionContract(StrictModel): composition_id: str; timeline_id: UUID; timeline_version: int = Field(ge=1); timeline_hash: str; fps: int = Field(ge=1,le=120); width: int = Field(gt=0); height: int = Field(gt=0); duration_frames: int = Field(gt=0)
class RenderAttemptContract(StrictModel): id: UUID; render_job_id: UUID; attempt_number: int = Field(ge=1); worker_id: str | None; status: TaskStatus
class VideoExportContract(StrictModel): id: UUID; project_id: UUID; render_artifact_id: UUID; format: str; aspect_ratio: str; created_at: datetime
class AIProviderContract(StrictModel): provider_key: str; display_name: str; provider_type: str; enabled: bool
class PromptTemplateContract(StrictModel): prompt_key: str; version: int = Field(ge=1); agent_key: str; output_schema: dict[str,Any]; status: str
class UsageLedgerContract(StrictModel): id: UUID; workspace_id: UUID; reference_type: str; reference_id: UUID; entry_type: str; quantity: float; unit: str; amount_minor: int; currency: str = Field(min_length=3,max_length=3); idempotency_key: str
