import { z } from 'zod';

export const UUID = z.string().uuid();
export const Timestamp = z.string().datetime({ offset: true });
export const AspectRatio = z.enum(['16:9','9:16','1:1','4:5','4:3']);
export const UserRole = z.enum(['owner','admin','editor','member','viewer','billing']);
export const ProjectStatus = z.enum(['draft','active','archived','deleted']);
export const TaskStatus = z.enum(['pending','queued','running','succeeded','failed','retry_wait','cancelled','skipped']);
export const RunStatus = z.enum(['queued','planning','scripting','storyboarding','asset_generation','audio_generation','subtitle_generation','timeline_compilation','ready_for_review','render_queued','rendering','quality_check','completed','failed','cancel_requested','cancelled']);
export const RenderStatus = z.enum(['queued','preparing','rendering','uploading','validating','completed','failed','cancel_requested','cancelled']);

export const ProfileApiSchema = z.object({
  id: UUID,
  display_name: z.string().nullable(),
  avatar_path: z.string().nullable(),
  bio: z.string().nullable(),
  locale: z.string(),
  timezone: z.string(),
  created_at: Timestamp.optional(),
  updated_at: Timestamp.optional(),
}).strict();
export const WorkspaceApiSchema = z.object({
  id: UUID,
  name: z.string().min(1).max(120),
  slug: z.string().min(2).max(64),
  owner_user_id: UUID,
  plan_id: UUID.nullable().optional(),
  settings: z.record(z.string(), z.unknown()).optional(),
  role: UserRole.optional(),
  created_at: Timestamp,
  updated_at: Timestamp,
}).strict();
export const WorkspacePermissionsApiSchema = z.object({
  workspace_id: UUID,
  role: UserRole,
  permissions: z.array(z.string()),
}).strict();
export const WorkspaceMemberApiSchema = z.object({
  id: UUID,
  workspace_id: UUID,
  user_id: UUID,
  role: UserRole,
  status: z.enum(['active','suspended','left']),
  created_at: Timestamp,
  display_name: z.string().nullable().optional(),
}).strict();
export const WorkspaceInvitationApiSchema = z.object({
  id: UUID,
  workspace_id: UUID,
  email: z.email(),
  role: z.enum(['admin','editor','member','viewer','billing']),
  invited_by: UUID,
  expires_at: Timestamp,
  created_at: Timestamp,
}).strict();
export const VideoProjectApiSchema = z.object({
  id: UUID,
  workspace_id: UUID,
  created_by: UUID,
  name: z.string().min(1).max(160),
  description: z.string().max(4000).nullable(),
  production_mode: z.enum(['motion_graphic','explainer','presentation','social_short','documentary_lite']),
  status: ProjectStatus,
  default_language: z.string().min(2),
  target_duration_ms: z.number().int().positive().nullable(),
  aspect_ratio: AspectRatio,
  width: z.number().int().positive(),
  height: z.number().int().positive(),
  fps: z.number().int().min(1).max(120),
  settings: z.record(z.string(), z.unknown()).nullable().optional(),
  settings_version: z.number().int().positive().nullable().optional(),
  brand_kit_id: UUID.nullable().optional(),
  active_run_id: UUID.nullable().optional(),
  created_at: Timestamp,
  updated_at: Timestamp,
}).strict();
export const UserSchema = z.object({id:UUID,email:z.email().optional(),displayName:z.string().max(160).nullable(),avatarPath:z.string().nullable(),createdAt:Timestamp}).strict();
export const WorkspaceSchema = z.object({id:UUID,name:z.string().min(1).max(120),slug:z.string().min(2).max(80),ownerUserId:UUID,createdAt:Timestamp,updatedAt:Timestamp}).strict();
export const MembershipSchema = z.object({id:UUID,workspaceId:UUID,userId:UUID,role:UserRole,status:z.enum(['active','invited','suspended']),createdAt:Timestamp}).strict();
export const VideoProjectSchema = z.object({id:UUID,workspaceId:UUID,createdBy:UUID,name:z.string().min(1).max(160),description:z.string().max(4000).nullable(),productionMode:z.enum(['motion_graphic','explainer','presentation','social_short','documentary_lite']),status:ProjectStatus,defaultLanguage:z.string().min(2),targetDurationMs:z.number().int().positive().nullable(),aspectRatio:AspectRatio,width:z.number().int().positive(),height:z.number().int().positive(),fps:z.number().int().min(1).max(120),createdAt:Timestamp,updatedAt:Timestamp}).strict();
export const ArtifactVersionSchema = z.object({id:UUID,projectId:UUID,artifactType:z.string().min(1),artifactId:UUID,version:z.number().int().positive(),contentHash:z.string().min(32),createdAt:Timestamp}).strict();
export const SceneSchema = z.object({id:UUID,sceneIndex:z.number().int().nonnegative(),title:z.string().min(1),narrationText:z.string().nullable(),durationMs:z.number().int().positive(),visualDirection:z.record(z.string(),z.unknown()),motionPlan:z.record(z.string(),z.unknown())}).strict();
export const ProductionRunSchema = z.object({id:UUID,projectId:UUID,workspaceId:UUID,status:RunStatus,currentStage:z.string().nullable(),progressPercent:z.number().min(0).max(100),createdAt:Timestamp,updatedAt:Timestamp}).strict();
export const AgentTaskSchema = z.object({id:UUID,productionRunId:UUID,agentKey:z.string(),status:TaskStatus,attemptCount:z.number().int().nonnegative(),createdAt:Timestamp}).strict();
export const WorkflowEventSchema = z.object({id:UUID,productionRunId:UUID,eventType:z.string(),sequenceNumber:z.number().int().positive(),payload:z.record(z.string(),z.unknown()),createdAt:Timestamp}).strict();
export const MediaAssetSchema = z.object({id:UUID,workspaceId:UUID,projectId:UUID.nullable(),assetType:z.enum(['image','video','audio','font','subtitle','document']),storageBucket:z.string(),storagePath:z.string(),mimeType:z.string(),fileSizeBytes:z.number().int().nonnegative(),status:z.enum(['pending','available','quarantined','deleted']),createdAt:Timestamp}).strict();
export const SubtitleSegmentSchema = z.object({id:UUID,segmentIndex:z.number().int().nonnegative(),text:z.string(),startMs:z.number().int().nonnegative(),endMs:z.number().int().positive()}).refine(v=>v.endMs>v.startMs,'endMs must exceed startMs');
export const TimelineClipSchema = z.object({id:UUID,trackId:UUID,clipType:z.enum(['component','image','video','audio','subtitle']),startFrame:z.number().int().nonnegative(),durationFrames:z.number().int().positive(),componentKey:z.string().nullable(),props:z.record(z.string(),z.unknown())}).strict();
export const TimelineSchema = z.object({id:UUID,projectId:UUID,version:z.number().int().positive(),fps:z.number().int().positive(),width:z.number().int().positive(),height:z.number().int().positive(),durationFrames:z.number().int().positive(),clips:z.array(TimelineClipSchema),compiledHash:z.string().min(32)}).strict();
export const RenderJobSchema = z.object({id:UUID,projectId:UUID,workspaceId:UUID,timelineId:UUID,status:RenderStatus,progressPercent:z.number().min(0).max(100),attemptCount:z.number().int().nonnegative(),createdAt:Timestamp}).strict();
export const RenderArtifactSchema = z.object({id:UUID,renderJobId:UUID,artifactType:z.enum(['video','thumbnail','poster','captions']),storageBucket:z.string(),storagePath:z.string(),mimeType:z.string(),checksumSha256:z.string().nullable()}).strict();
export const AIModelConfigSchema = z.object({providerKey:z.string(),modelKey:z.string(),capabilities:z.array(z.string()),enabled:z.boolean()}).strict();
export const UsageRecordSchema = z.object({id:UUID,workspaceId:UUID,providerKey:z.string(),modelKey:z.string(),inputTokens:z.number().int().nonnegative().nullable(),outputTokens:z.number().int().nonnegative().nullable(),currency:z.string().length(3),createdAt:Timestamp}).strict();
export const AuditEventSchema = z.object({id:UUID,actorUserId:UUID.nullable(),action:z.string(),resourceType:z.string(),resourceId:UUID.nullable(),createdAt:Timestamp}).strict();
export const ApiErrorSchema = z.object({code:z.string(),message:z.string(),requestId:z.string().optional(),details:z.record(z.string(),z.unknown()).optional()}).strict();
export const ApiResponseSchema = <T extends z.ZodType>(data:T) => z.object({data,meta:z.object({requestId:z.string(),contractVersion:z.literal('1'),timestamp:Timestamp}).strict()}).strict();
export const PaginationSchema = z.object({limit:z.number().int().min(1).max(100),cursor:z.string().nullable()}).strict();
export type ProfileApi = z.infer<typeof ProfileApiSchema>;
export type WorkspaceApi = z.infer<typeof WorkspaceApiSchema>;
export type WorkspacePermissionsApi = z.infer<typeof WorkspacePermissionsApiSchema>;
export type WorkspaceMemberApi = z.infer<typeof WorkspaceMemberApiSchema>;
export type WorkspaceInvitationApi = z.infer<typeof WorkspaceInvitationApiSchema>;
export type VideoProjectApi = z.infer<typeof VideoProjectApiSchema>;
export type User = z.infer<typeof UserSchema>;
export type Workspace = z.infer<typeof WorkspaceSchema>;
export type Membership = z.infer<typeof MembershipSchema>;
export type VideoProject = z.infer<typeof VideoProjectSchema>;
export type ProductionRun = z.infer<typeof ProductionRunSchema>;
export type AgentTask = z.infer<typeof AgentTaskSchema>;
export type MediaAsset = z.infer<typeof MediaAssetSchema>;
export type Timeline = z.infer<typeof TimelineSchema>;
export type RenderJob = z.infer<typeof RenderJobSchema>;
export type ApiError = z.infer<typeof ApiErrorSchema>;

export const ScriptSchema = z.object({id:UUID,projectId:UUID,version:z.number().int().positive(),language:z.string(),title:z.string(),hook:z.string().nullable(),body:z.array(z.object({section:z.string(),text:z.string()}).strict()),cta:z.string().nullable(),estimatedDurationMs:z.number().int().positive().nullable(),createdAt:Timestamp}).strict();
export const StoryboardSchema = z.object({id:UUID,projectId:UUID,scriptId:UUID,version:z.number().int().positive(),globalVisualDirection:z.record(z.string(),z.unknown()),scenes:z.array(SceneSchema),createdAt:Timestamp}).strict();
export const WorkflowCheckpointSchema = z.object({id:UUID,productionRunId:UUID,stageKey:z.string(),checkpointKey:z.string(),contentHash:z.string().min(32),payload:z.record(z.string(),z.unknown()),createdAt:Timestamp}).strict();
export const VoiceProfileSchema = z.object({providerKey:z.string(),voiceKey:z.string(),displayName:z.string(),language:z.string(),supportsStyle:z.boolean()}).strict();
export const AudioGenerationSchema = z.object({id:UUID,projectId:UUID,sceneId:UUID.nullable(),providerKey:z.string(),voiceKey:z.string(),storageAssetId:UUID.nullable(),durationMs:z.number().int().positive().nullable(),status:TaskStatus,createdAt:Timestamp}).strict();
export const SubtitleTrackSchema = z.object({id:UUID,projectId:UUID,language:z.string(),version:z.number().int().positive(),status:TaskStatus,segments:z.array(SubtitleSegmentSchema)}).strict();
export const MotionComponentSchema = z.object({componentKey:z.string(),version:z.string(),category:z.string(),propsSchema:z.record(z.string(),z.unknown()),enabled:z.boolean()}).strict();
export const CompositionSchema = z.object({compositionId:z.string(),timelineId:UUID,timelineVersion:z.number().int().positive(),timelineHash:z.string().min(32),fps:z.number().int().min(1).max(120),width:z.number().int().positive(),height:z.number().int().positive(),durationFrames:z.number().int().positive()}).strict();
export const RenderAttemptSchema = z.object({id:UUID,renderJobId:UUID,attemptNumber:z.number().int().positive(),workerId:z.string().nullable(),status:TaskStatus,startedAt:Timestamp.nullable(),endedAt:Timestamp.nullable()}).strict();
export const VideoExportSchema = z.object({id:UUID,projectId:UUID,renderArtifactId:UUID,format:z.enum(['mp4','webm','mov']),aspectRatio:AspectRatio,createdAt:Timestamp}).strict();
export const AIProviderSchema = z.object({providerKey:z.string(),displayName:z.string(),providerType:z.enum(['llm','tts','image','media']),enabled:z.boolean()}).strict();
export const PromptTemplateSchema = z.object({promptKey:z.string(),version:z.number().int().positive(),agentKey:z.string(),outputSchema:z.record(z.string(),z.unknown()),status:z.enum(['draft','active','deprecated'])}).strict();
export const UsageLedgerSchema = z.object({id:UUID,workspaceId:UUID,referenceType:z.string(),referenceId:UUID,entryType:z.string(),quantity:z.number(),unit:z.string(),amountMinor:z.number().int(),currency:z.string().length(3),idempotencyKey:z.string().min(16),createdAt:Timestamp}).strict();
export type Script = z.infer<typeof ScriptSchema>;
export type Storyboard = z.infer<typeof StoryboardSchema>;
export type AudioGeneration = z.infer<typeof AudioGenerationSchema>;
export type SubtitleTrack = z.infer<typeof SubtitleTrackSchema>;
export type Composition = z.infer<typeof CompositionSchema>;
export type AIProvider = z.infer<typeof AIProviderSchema>;

export const CreativeBriefApiSchema = z.object({
  id: UUID, workspace_id: UUID, project_id: UUID, version: z.number().int().positive(),
  input_prompt: z.string(), normalized_brief: z.record(z.string(), z.unknown()),
  source_references: z.array(z.record(z.string(), z.unknown())),
  status: z.enum(['draft','approved','superseded']), approved_by: UUID.nullable(),
  approved_at: Timestamp.nullable(), created_by: UUID, created_at: Timestamp,
}).strict();
export const VideoScriptApiSchema = z.object({
  id: UUID, workspace_id: UUID, project_id: UUID, brief_id: UUID.nullable(),
  version: z.number().int().positive(), language: z.string(), title: z.string(),
  hook: z.string().nullable(), body: z.record(z.string(), z.unknown()),
  cta: z.string().nullable(), estimated_duration_ms: z.number().int().positive().nullable(),
  word_count: z.number().int().nonnegative().nullable(),
  status: z.enum(['draft','approved','superseded']), created_by_agent: z.string().nullable(),
  created_by: UUID, created_at: Timestamp,
}).strict();
export const StoryboardSceneApiSchema = z.object({
  id: UUID, workspace_id: UUID, project_id: UUID, storyboard_id: UUID,
  scene_index: z.number().int().nonnegative(), title: z.string(), purpose: z.string().nullable(),
  narration_text: z.string().nullable(), duration_ms: z.number().int().positive(),
  visual_direction: z.record(z.string(), z.unknown()), transition_in: z.string().nullable(),
  transition_out: z.string().nullable(), motion_plan: z.record(z.string(), z.unknown()),
  asset_requirements: z.array(z.record(z.string(), z.unknown())),
  created_at: Timestamp, updated_at: Timestamp,
}).strict();
export const StoryboardApiSchema = z.object({
  id: UUID, workspace_id: UUID, project_id: UUID, script_id: UUID,
  version: z.number().int().positive(), global_visual_direction: z.record(z.string(), z.unknown()),
  status: z.enum(['draft','approved','superseded']), created_by: UUID, created_at: Timestamp,
  scenes: z.array(StoryboardSceneApiSchema),
}).strict();
export const ArtifactVersionApiSchema = z.object({
  id: UUID, artifact_type: z.enum(['creative_brief','video_script','storyboard','storyboard_scene']),
  artifact_id: UUID, version: z.number().int().positive(), content_hash: z.string().length(64),
  created_by: UUID.nullable(), created_by_agent: z.string().nullable(),
  change_summary: z.string().nullable(), created_at: Timestamp,
}).strict();
export type CreativeBriefApi = z.infer<typeof CreativeBriefApiSchema>;
export type VideoScriptApi = z.infer<typeof VideoScriptApiSchema>;
export type StoryboardApi = z.infer<typeof StoryboardApiSchema>;
export type StoryboardSceneApi = z.infer<typeof StoryboardSceneApiSchema>;
export type ArtifactVersionApi = z.infer<typeof ArtifactVersionApiSchema>;

export const ProductionRunApiSchema = z.object({
  id: UUID, project_id: UUID, workspace_id: UUID, requested_by: UUID,
  status: z.enum(['queued','planning','scripting','storyboarding','ready_for_review','failed','cancel_requested','cancelled','completed']),
  current_stage: z.string().nullable(), progress_percent: z.number(),
  error_code: z.string().nullable(), error_message_safe: z.string().nullable(),
  started_at: Timestamp.nullable(), completed_at: Timestamp.nullable(),
  created_at: Timestamp, updated_at: Timestamp,
}).strict();
export const RenderJobApiSchema = z.object({
  id: UUID, project_id: UUID, workspace_id: UUID, requested_by: UUID,
  status: z.enum(['queued','rendering','completed','failed','cancel_requested','cancelled']),
  composition_id: z.string(), composition_version: z.string(), timeline_hash: z.string().length(64),
  progress_percent: z.number(), output_bucket: z.string().nullable(), output_path: z.string().nullable(),
  output_size_bytes: z.number().int().nullable(), output_sha256: z.string().nullable(),
  error_code: z.string().nullable(), error_message_safe: z.string().nullable(),
  started_at: Timestamp.nullable(), completed_at: Timestamp.nullable(), created_at: Timestamp,
}).strict();
export type ProductionRunApi = z.infer<typeof ProductionRunApiSchema>;
export type RenderJobApi = z.infer<typeof RenderJobApiSchema>;

export const ProjectAssetApiSchema = z.object({
  id: UUID, project_id: UUID, workspace_id: UUID, uploaded_by: UUID,
  file_name: z.string(), content_type: z.string(), size_bytes: z.number().int().positive(),
  sha256: z.string().length(64), status: z.enum(['active','deleted']), created_at: Timestamp,
}).strict();
export type ProjectAssetApi = z.infer<typeof ProjectAssetApiSchema>;
