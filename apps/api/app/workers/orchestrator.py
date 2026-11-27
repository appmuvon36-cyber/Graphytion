from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
import socket
from datetime import datetime, timezone
from typing import Any, Literal
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, ValidationError
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.routes.media_generation import MediaGenerationCreate, _validate_config
from app.api.v1.routes.render import _validate_snapshot
from app.api.v1.routes.voiceover import VoiceoverCreate
from app.core.database import SessionLocal, set_rls_subject
from app.services.brand_kit import apply_brand_tokens
from app.services.composition_assets import collect_asset_ids, resolve_project_assets
from app.services.composition_validation import validate_snapshot
from app.services.queue_notifications import notify_worker

logger = logging.getLogger("graphytion.orchestrator")
WORKER_ID = f"{socket.gethostname()}:{os.getpid()}:orchestrator:{uuid4().hex[:8]}"
LEASE_SECONDS = 120
POLL_SECONDS = 2
SCHEMA_VERSION = 1


class StepEnvelope(BaseModel):
    model_config = ConfigDict(extra="forbid")
    run_id: UUID
    step_id: UUID
    step_type: str
    schema_version: int = Field(ge=1, le=100)
    input_refs: dict[str, Any]
    configuration: dict[str, Any]
    dependency_outputs: dict[str, dict[str, Any]]
    idempotency_key: str = Field(min_length=32, max_length=128)
    execution_context: dict[str, Any]


class MediaConfiguration(BaseModel):
    model_config = ConfigDict(extra="forbid")
    media_type: Literal["image", "video"]
    prompt: str = Field(min_length=1, max_length=32000)
    model_key: str = Field(min_length=1, max_length=128)
    generation_config: dict[str, Any] = Field(default_factory=dict)


class VoiceoverConfiguration(BaseModel):
    model_config = ConfigDict(extra="forbid")
    text: str = Field(min_length=1, max_length=20000)
    provider_key: Literal["gemini", "openai"] = "gemini"
    model_key: str = "gemini-3.8-flash-lite-tts"
    voice_key: str = "Kore"
    language: str = "id-ID"
    generation_config: dict[str, Any] = Field(default_factory=dict)


class SubtitleSegment(BaseModel):
    model_config = ConfigDict(extra="forbid")
    start_ms: int = Field(ge=0)
    end_ms: int = Field(gt=0)
    text: str = Field(min_length=1, max_length=4000)
    speaker: str | None = None


class SubtitleConfiguration(BaseModel):
    model_config = ConfigDict(extra="forbid")
    language: str = Field(default="id-ID", min_length=2, max_length=16)
    format: Literal["webvtt", "srt"] = "webvtt"
    style_config: dict[str, Any] = Field(default_factory=dict)
    segments: list[SubtitleSegment] = Field(min_length=1, max_length=5000)


class SnapshotConfiguration(BaseModel):
    model_config = ConfigDict(extra="forbid")
    snapshot: dict[str, Any]
    expected_version: int | None = Field(default=None, ge=1)


class StepInputError(ValueError):
    pass


class StepCancelledError(StepInputError):
    pass


def _canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str)


def _fingerprint(value: Any) -> str:
    return hashlib.sha256(_canonical(value).encode("utf-8")).hexdigest()


async def _append_event(
    db: AsyncSession, run_id: UUID, event_type: str, payload: dict[str, Any]
) -> None:
    # Serialize sequence allocation on the Production Run row.
    await db.execute(text("select id from public.production_runs where id=:run for update"), {"run": run_id})
    await db.execute(
        text("""
            insert into public.workflow_events(production_run_id,event_type,event_payload,sequence_number)
            values(:run,:type,cast(:payload as jsonb),
              (select coalesce(max(sequence_number),0)+1
               from public.workflow_events where production_run_id=:run))
            on conflict(production_run_id,sequence_number) do nothing
        """),
        {"run": run_id, "type": event_type, "payload": _canonical(payload)},
    )


async def _heartbeat(step_id: UUID) -> None:
    while True:
        await asyncio.sleep(30)
        async with SessionLocal() as db:
            renewed = await db.scalar(
                text("select private.graphytion_heartbeat_production_step(:step,:worker,:lease)"),
                {"step": step_id, "worker": WORKER_ID, "lease": LEASE_SECONDS},
            )
            await db.commit()
            if not renewed:
                raise RuntimeError("Production step dispatcher lease was lost")


async def _load_envelope(db: AsyncSession, step: dict[str, Any]) -> tuple[StepEnvelope, dict[str, Any]]:
    run = (await db.execute(
        text("""
            select id,workspace_id,project_id,requested_by,status,input_snapshot,config_snapshot,
                   cancel_requested_at
            from public.production_runs where id=:run
        """),
        {"run": step["production_run_id"]},
    )).mappings().first()
    if run is None:
        raise StepInputError("Production Run no longer exists")
    if run["status"] in {"cancel_requested", "cancelled"} or run["cancel_requested_at"] is not None:
        raise StepCancelledError("Production Run cancellation was requested")

    await set_rls_subject(db, str(run["requested_by"]))
    parents = (await db.execute(
        text("""
            select parent.step_key,parent.output_refs,parent.step_type,parent.status
            from public.production_run_step_dependencies d
            join public.production_run_steps parent on parent.id=d.depends_on_step_id
            where d.step_id=:step order by parent.step_key
        """),
        {"step": step["id"]},
    )).mappings().all()
    if any(row["status"] != "completed" for row in parents):
        raise StepInputError("A dependency output is not complete")
    dependency_outputs = {row["step_key"]: dict(row["output_refs"] or {}) for row in parents}
    config = dict(step["config"] or {})
    input_refs = dict(step["input_refs"] or {})
    fingerprint = _fingerprint({
        "schema_version": SCHEMA_VERSION,
        "input_refs": input_refs,
        "configuration": config,
        "dependency_outputs": dependency_outputs,
    })
    key = hashlib.sha256(
        f"{step['production_run_id']}:{step['id']}:{fingerprint}".encode("utf-8")
    ).hexdigest()
    envelope = StepEnvelope(
        run_id=step["production_run_id"],
        step_id=step["id"],
        step_type=step["step_type"],
        schema_version=int(step["payload_schema_version"] or SCHEMA_VERSION),
        input_refs=input_refs,
        configuration=config,
        dependency_outputs=dependency_outputs,
        idempotency_key=key,
        execution_context={
            "workspace_id": str(run["workspace_id"]),
            "project_id": str(run["project_id"]),
            "requested_by": str(run["requested_by"]),
            "worker_id": WORKER_ID,
            "attempt": int(step["attempt_count"]),
            "created_at": datetime.now(timezone.utc).isoformat(),
        },
    )
    await db.execute(
        text("""
            update public.production_run_steps
               set input_fingerprint=:fingerprint,payload_contract=cast(:contract as jsonb),
                   payload_schema_version=:version,external_operation_state='not_started',
                   updated_at=now()
             where id=:step and worker_id=:worker and status='running'
        """),
        {
            "fingerprint": fingerprint,
            "contract": _canonical(envelope.model_dump(mode="json")),
            "version": envelope.schema_version,
            "step": step["id"],
            "worker": WORKER_ID,
        },
    )
    return envelope, dict(run)


async def _finish_without_child(
    db: AsyncSession, step: dict[str, Any], outputs: dict[str, Any]
) -> None:
    await db.execute(
        text("""
            update public.production_run_steps
               set status='completed',output_refs=cast(:outputs as jsonb),
                   completed_at=now(),worker_id=null,lease_expires_at=null,
                   heartbeat_at=null,external_operation_state='completed',updated_at=now()
             where id=:step and worker_id=:worker and status='running'
        """),
        {"outputs": _canonical(outputs), "step": step["id"], "worker": WORKER_ID},
    )
    await _append_event(
        db, step["production_run_id"], "step.completed",
        {"step_id": str(step["id"]), "step_key": step["step_key"], "output_refs": outputs},
    )
    await db.execute(
        text("select private.graphytion_sync_production_run(:run)"),
        {"run": step["production_run_id"]},
    )


async def _attach_child(
    db: AsyncSession, step: dict[str, Any], child_type: str, child_id: UUID, output: dict[str, Any]
) -> None:
    updated = await db.execute(
        text("""
            update public.production_run_steps
               set child_job_type=:type,child_job_id=:child,status='running',
                   output_refs=cast(:output as jsonb),worker_id=null,
                   lease_expires_at=null,heartbeat_at=null,
                   external_operation_state='submitted',
                   started_at=coalesce(started_at,now()),updated_at=now()
             where id=:step and worker_id=:worker and status='running'
               and child_job_id is null
               and exists(select 1 from public.production_runs r
                 where r.id=:run and r.status not in ('cancel_requested','cancelled')
                   and r.cancel_requested_at is null)
        """),
        {
            "type": child_type, "child": child_id, "output": _canonical(output),
            "step": step["id"], "worker": WORKER_ID, "run": step["production_run_id"],
        },
    )
    if updated.rowcount != 1:
        raise RuntimeError("Step ownership changed before child-job attachment")
    await _append_event(
        db, step["production_run_id"], "step.child_job_attached",
        {"step_id": str(step["id"]), "step_key": step["step_key"],
         "child_job_type": child_type, "child_job_id": str(child_id)},
    )
    await db.execute(
        text("select private.graphytion_sync_production_run(:run)"),
        {"run": step["production_run_id"]},
    )


async def _dispatch_creative_gate(
    db: AsyncSession, step: dict[str, Any], envelope: StepEnvelope
) -> None:
    if step["requires_approval"] and not step["approved_at"]:
        raise StepInputError("Creative review requires explicit owner approval")
    task = (await db.execute(
        text("""
            select id,status,output_payload,output_artifact_id
            from public.agent_tasks where production_run_id=:run
            order by created_at desc limit 1
        """),
        {"run": envelope.run_id},
    )).mappings().first()
    if task is None or task["status"] not in {"succeeded", "completed"}:
        raise StepInputError("Creative agent output is not available")
    if not task["output_payload"] and not task["output_artifact_id"]:
        raise StepInputError("Creative agent output has no persisted artifact reference")
    await _finish_without_child(db, step, {
        "agent_task_id": str(task["id"]),
        "output_artifact_id": str(task["output_artifact_id"]) if task["output_artifact_id"] else None,
        "creative_output": task["output_payload"] or {},
        "approved_at": step["approved_at"].isoformat() if step["approved_at"] else None,
    })


async def _dispatch_media(
    db: AsyncSession, step: dict[str, Any], envelope: StepEnvelope, run: dict[str, Any]
) -> None:
    config = MediaConfiguration.model_validate(envelope.configuration)
    payload = MediaGenerationCreate(
        media_type=config.media_type,
        provider_key="gemini",
        model_key=config.model_key,
        prompt=config.prompt,
        generation_config=config.generation_config,
        production_run_id=envelope.run_id,
        parent_step_id=envelope.step_id,
    )
    generation_config = _validate_config(payload)
    old = (await db.execute(
        text("select id,status,media_type,model_key,prompt,generation_config from public.media_generation_jobs where workspace_id=:workspace and idempotency_key=:key"),
        {"workspace": run["workspace_id"], "key": envelope.idempotency_key},
    )).mappings().first()
    if old:
        if old["media_type"] != payload.media_type or old["model_key"] != payload.model_key or old["prompt"] != payload.prompt or old["generation_config"] != generation_config:
            raise StepInputError("Media idempotency key conflicts with a different generation payload")
        child_id = old["id"]
    else:
        child_id = await db.scalar(text("""
            insert into public.media_generation_jobs(
              workspace_id,project_id,requested_by,media_type,provider_key,model_key,
              prompt,generation_config,idempotency_key,production_run_id,parent_step_id,
              quota_debit_microusd,quota_reconciliation_status,economics_status
            ) values(:workspace,:project,:actor,:type,'gemini',:model,:prompt,
              cast(:config as jsonb),:key,:run,:step,0,'not_required','unpriced')
            returning id
        """), {
            "workspace": run["workspace_id"], "project": run["project_id"],
            "actor": run["requested_by"], "type": payload.media_type, "model": payload.model_key,
            "prompt": payload.prompt, "config": _canonical(generation_config),
            "key": envelope.idempotency_key, "run": envelope.run_id, "step": envelope.step_id,
        })
    await _attach_child(db, step, "media_generation", child_id, {
        "media_type": payload.media_type, "model_key": payload.model_key,
        "idempotency_key": envelope.idempotency_key,
    })
    await db.commit()
    await notify_worker("media", str(child_id))


async def _dispatch_voiceover(
    db: AsyncSession, step: dict[str, Any], envelope: StepEnvelope, run: dict[str, Any]
) -> None:
    config = VoiceoverConfiguration.model_validate(envelope.configuration)
    payload = VoiceoverCreate(
        text=config.text, provider_key=config.provider_key, model_key=config.model_key,
        voice_key=config.voice_key, language=config.language,
        generation_config=config.generation_config,
        production_run_id=envelope.run_id, parent_step_id=envelope.step_id,
    )
    old = (await db.execute(
        text("select id,status,input_text,provider_key,model_key,voice_key,language,generation_config from public.audio_generations where workspace_id=:workspace and idempotency_key=:key"),
        {"workspace": run["workspace_id"], "key": envelope.idempotency_key},
    )).mappings().first()
    if old:
        if old["input_text"] != payload.text or old["provider_key"] != payload.provider_key or old["model_key"] != payload.model_key or old["voice_key"] != payload.voice_key or old["language"] != payload.language or old["generation_config"] != payload.generation_config:
            raise StepInputError("Voiceover idempotency key conflicts with a different TTS payload")
        child_id = old["id"]
    else:
        child_id = await db.scalar(text("""
            insert into public.audio_generations(
              workspace_id,project_id,requested_by,provider_key,model_key,voice_key,
              input_text,language,generation_config,status,idempotency_key,
              production_run_id,parent_step_id
            ) values(:workspace,:project,:actor,:provider,:model,:voice,:input,:language,
              cast(:config as jsonb),'queued',:key,:run,:step) returning id
        """), {
            "workspace": run["workspace_id"], "project": run["project_id"],
            "actor": run["requested_by"], "provider": payload.provider_key,
            "model": payload.model_key, "voice": payload.voice_key, "input": payload.text,
            "language": payload.language, "config": _canonical(payload.generation_config),
            "key": envelope.idempotency_key, "run": envelope.run_id, "step": envelope.step_id,
        })
    await _attach_child(db, step, "audio_generation", child_id, {
        "provider_key": payload.provider_key, "model_key": payload.model_key,
        "voice_key": payload.voice_key, "idempotency_key": envelope.idempotency_key,
    })
    await db.commit()
    await notify_worker("media", str(child_id))


async def _dispatch_subtitles(
    db: AsyncSession, step: dict[str, Any], envelope: StepEnvelope, run: dict[str, Any]
) -> None:
    config = SubtitleConfiguration.model_validate(envelope.configuration)
    if any(segment.end_ms <= segment.start_ms for segment in config.segments):
        raise StepInputError("Subtitle segment end_ms must be greater than start_ms")
    audio_output = envelope.dependency_outputs.get("audio_processing", {})
    audio_asset_id = audio_output.get("asset_id")
    old = (await db.execute(
        text("select id,version from public.subtitle_tracks where parent_step_id=:step and production_run_id=:run"),
        {"step": envelope.step_id, "run": envelope.run_id},
    )).mappings().first()
    if old:
        track_id = old["id"]
    else:
        track_id = await db.scalar(text("""
            insert into public.subtitle_tracks(
              workspace_id,project_id,language,format,version,style_config,created_by,
              production_run_id,parent_step_id
            ) values(:workspace,:project,:language,:format,1,cast(:style as jsonb),
              :actor,:run,:step) returning id
        """), {
            "workspace": run["workspace_id"], "project": run["project_id"],
            "language": config.language, "format": config.format,
            "style": _canonical(config.style_config), "actor": run["requested_by"],
            "run": envelope.run_id, "step": envelope.step_id,
        })
        for index, segment in enumerate(config.segments):
            await db.execute(text("""
                insert into public.subtitle_segments(
                  track_id,segment_index,start_ms,end_ms,text,speaker,word_timings,
                  style_config,position_config,alignment_metadata,audio_asset_id
                ) values(:track,:index,:start,:end,:text,:speaker,'[]'::jsonb,
                  '{}'::jsonb,'{}'::jsonb,'{}'::jsonb,:audio_asset)
            """), {
                "track": track_id, "index": index, "start": segment.start_ms,
                "end": segment.end_ms, "text": segment.text, "speaker": segment.speaker,
                "audio_asset": audio_asset_id,
            })
    await _finish_without_child(db, step, {
        "subtitle_track_id": str(track_id),
        "segment_count": len(config.segments),
        "language": config.language,
        "format": config.format,
        "audio_asset_id": str(audio_asset_id) if audio_asset_id else None,
    })


async def _load_snapshot(
    db: AsyncSession, step: dict[str, Any], envelope: StepEnvelope, run: dict[str, Any]
) -> tuple[dict[str, Any], UUID | None, int | None]:
    raw = envelope.configuration.get("snapshot")
    if raw is None:
        row = (await db.execute(text("""
            select id,version,snapshot from public.video_timelines
            where project_id=:project and workspace_id=:workspace
            order by version desc limit 1
        """), {"project": run["project_id"], "workspace": run["workspace_id"]})).mappings().first()
        if row is None:
            raise StepInputError("No immutable timeline snapshot is available")
        return dict(row["snapshot"]), row["id"], int(row["version"])
    parsed = SnapshotConfiguration.model_validate(envelope.configuration)
    return dict(parsed.snapshot), None, parsed.expected_version


async def _dispatch_timeline(
    db: AsyncSession, step: dict[str, Any], envelope: StepEnvelope, run: dict[str, Any]
) -> None:
    snapshot, _, expected_version = await _load_snapshot(db, step, envelope, run)
    # Materialize the persisted media/TTS/subtitle outputs into the canonical
    # composition snapshot so the render worker receives the same immutable edit.
    snapshot.setdefault("tracks", [])
    snapshot.setdefault("clips", [])
    snapshot.setdefault("assetRefs", [])
    media_row = (await db.execute(text("""
        select id,asset_id,media_type from public.media_generation_jobs
        where production_run_id=:run and status='completed' and asset_id is not null
        order by created_at desc limit 1
    """), {"run": envelope.run_id})).mappings().first()
    if media_row and not any(
        str(clip.get("assetId") or clip.get("props", {}).get("assetId")) == str(media_row["asset_id"])
        for clip in snapshot["clips"]
    ):
        media_track_id = str(uuid4())
        media_kind = "video" if media_row["media_type"] == "video" else "visual"
        snapshot["tracks"].append({
            "id": media_track_id, "kind": media_kind, "name": "Generated media",
            "zIndex": max([int(track.get("zIndex", 0)) for track in snapshot["tracks"]] + [0]) + 1,
            "visible": True, "locked": False, "muted": False, "volume": 1,
        })
        media_key = "visual.video.v1" if media_row["media_type"] == "video" else "visual.image.v1"
        media_props = {"assetId": str(media_row["asset_id"]), "fit": "cover"}
        if media_row["media_type"] == "video":
            media_props.update({"volume": 0, "playbackRate": 1, "muted": True})
        snapshot["clips"].append({
            "id": str(uuid4()), "trackId": media_track_id, "startFrame": 0,
            "durationFrames": snapshot["durationFrames"], "trimStartFrames": 0,
            "playbackRate": 1, "componentKey": media_key, "componentVersion": "1.0.0",
            "assetId": str(media_row["asset_id"]), "props": media_props,
        })
        snapshot["assetRefs"].append({"assetId": str(media_row["asset_id"]),
                                      "kind": media_row["media_type"], "required": True})
    voice_row = (await db.execute(text("""
        select id,asset_id from public.audio_generations
        where production_run_id=:run and status='completed' and asset_id is not null
        order by created_at desc limit 1
    """), {"run": envelope.run_id})).mappings().first()
    if voice_row and not any(
        str(clip.get("assetId") or clip.get("props", {}).get("assetId")) == str(voice_row["asset_id"])
        for clip in snapshot["clips"]
    ):
        audio_track_id = str(uuid4())
        snapshot["tracks"].append({
            "id": audio_track_id, "kind": "voiceover", "name": "Generated voiceover",
            "zIndex": max([int(track.get("zIndex", 0)) for track in snapshot["tracks"]] + [0]) + 1,
            "visible": True, "locked": False, "muted": False, "volume": 1,
        })
        snapshot["clips"].append({
            "id": str(uuid4()), "trackId": audio_track_id, "startFrame": 0,
            "durationFrames": snapshot["durationFrames"], "trimStartFrames": 0,
            "playbackRate": 1, "componentKey": "audio.clip.v1", "componentVersion": "1.0.0",
            "assetId": str(voice_row["asset_id"]),
            "props": {"assetId": str(voice_row["asset_id"]), "volume": 1,
                      "fadeInFrames": 0, "fadeOutFrames": 0, "playbackRate": 1,
                      "trimStartFrames": 0},
        })
        snapshot["assetRefs"].append({"assetId": str(voice_row["asset_id"]),
                                      "kind": "audio", "required": True})
    subtitle_output = envelope.dependency_outputs.get("subtitle", {})
    subtitle_track_id = subtitle_output.get("subtitle_track_id")
    if subtitle_track_id:
        subtitle_track = (await db.execute(text("""
            select id,language from public.subtitle_tracks
            where id=:track and project_id=:project and workspace_id=:workspace
        """), {"track": subtitle_track_id, "project": run["project_id"],
               "workspace": run["workspace_id"]})).mappings().first()
        if subtitle_track:
            subtitle_track_id = str(subtitle_track["id"])
            timeline_subtitle_track = next((track for track in snapshot["tracks"]
                if track.get("kind") == "subtitle" and track.get("name") == "Graphytion auto subtitles"), None)
            if timeline_subtitle_track is None:
                timeline_subtitle_track = {
                    "id": str(uuid4()), "kind": "subtitle",
                    "name": "Graphytion auto subtitles",
                    "zIndex": max([int(track.get("zIndex", 0)) for track in snapshot["tracks"]] + [0]) + 10,
                    "visible": True, "locked": False, "muted": False, "volume": 1,
                }
                snapshot["tracks"].append(timeline_subtitle_track)
            subtitle_rows = (await db.execute(text("""
                select segment_index,start_ms,end_ms,text from public.subtitle_segments
                where track_id=:track order by segment_index
            """), {"track": subtitle_track_id})).mappings().all()
            for segment in subtitle_rows:
                start_frame = round(int(segment["start_ms"]) * snapshot["fps"] / 1000)
                end_frame = round(int(segment["end_ms"]) * snapshot["fps"] / 1000)
                start_frame = max(0, start_frame)
                end_frame = min(int(snapshot["durationFrames"]), max(start_frame + 1, end_frame))
                if start_frame >= int(snapshot["durationFrames"]):
                    continue
                snapshot["clips"].append({
                    "id": str(uuid4()), "trackId": timeline_subtitle_track["id"],
                    "startFrame": start_frame, "durationFrames": max(1, end_frame-start_frame),
                    "trimStartFrames": 0, "playbackRate": 1,
                    "componentKey": "text.subtitle.v1", "componentVersion": "1.0.0",
                    "props": {"text": segment["text"], "color": "#ffffff",
                              "background": "rgba(0,0,0,.65)", "fontSize": 32,
                              "position": "bottom", "align": "center"},
                })
    brand_row = (await db.execute(text("""
        select bk.brand_config from public.video_projects p
        left join public.brand_kits bk on bk.id=p.brand_kit_id and bk.workspace_id=p.workspace_id
        where p.id=:project and p.workspace_id=:workspace
    """), {"project": run["project_id"], "workspace": run["workspace_id"]})).mappings().first()
    snapshot = apply_brand_tokens(snapshot, dict(brand_row["brand_config"]) if brand_row and brand_row["brand_config"] else None)
    snapshot.pop("contentHash", None)
    digest = validate_snapshot(snapshot)
    snapshot["contentHash"] = digest
    asset_ids = collect_asset_ids(snapshot)
    await resolve_project_assets(
        db, project_id=run["project_id"], workspace_id=run["workspace_id"],
        asset_ids=asset_ids, expires_in=300, snapshot=snapshot,
    )
    await db.execute(text("select pg_advisory_xact_lock(hashtext(:project))"), {"project": str(run["project_id"])})
    current = int(await db.scalar(text("select max(version) from public.video_timelines where project_id=:project"), {"project": run["project_id"]}) or 0)
    if expected_version is not None and expected_version != current:
        raise StepInputError("Timeline changed after the production request was prepared")
    version = current + 1
    timeline_id = await db.scalar(text("""
        insert into public.video_timelines(
          workspace_id,project_id,version,schema_version,fps,width,height,duration_frames,
          snapshot,compiled_hash,created_by,production_run_id,parent_step_id
        ) values(:workspace,:project,:version,2,:fps,:width,:height,:duration,
          cast(:snapshot as jsonb),:hash,:actor,:run,:step) returning id
    """), {
        "workspace": run["workspace_id"], "project": run["project_id"], "version": version,
        "fps": snapshot["fps"], "width": snapshot["width"], "height": snapshot["height"],
        "duration": snapshot["durationFrames"], "snapshot": _canonical(snapshot),
        "hash": digest, "actor": run["requested_by"], "run": envelope.run_id,
        "step": envelope.step_id,
    })
    await _finish_without_child(db, step, {
        "timeline_id": str(timeline_id), "version": version, "compiled_hash": digest,
    })


async def _dispatch_render(
    db: AsyncSession, step: dict[str, Any], envelope: StepEnvelope, run: dict[str, Any]
) -> None:
    timeline_output = envelope.dependency_outputs.get("timeline", {})
    linked_timeline_id = timeline_output.get("timeline_id")
    if linked_timeline_id:
        timeline = (await db.execute(text("""
            select id,version,snapshot from public.video_timelines
            where id=:timeline and production_run_id=:run
              and project_id=:project and workspace_id=:workspace
        """), {"timeline": linked_timeline_id, "run": envelope.run_id,
               "project": run["project_id"], "workspace": run["workspace_id"]})).mappings().first()
        if timeline is None:
            raise StepInputError("Timeline dependency reference is missing or outside this Production Run")
        snapshot, timeline_id, version = dict(timeline["snapshot"]), timeline["id"], int(timeline["version"])
    else:
        snapshot, timeline_id, version = await _load_snapshot(db, step, envelope, run)
    snapshot.pop("contentHash", None)
    digest = _validate_snapshot(snapshot)
    snapshot["contentHash"] = digest
    if timeline_id is None:
        timeline = (await db.execute(text("""
            select id,version from public.video_timelines
            where project_id=:project and workspace_id=:workspace and compiled_hash=:hash
            order by version desc limit 1
        """), {"project": run["project_id"], "workspace": run["workspace_id"], "hash": digest})).mappings().first()
        if timeline is None:
            raise StepInputError("Render requires the exact immutable timeline snapshot to be persisted first")
        timeline_id, version = timeline["id"], int(timeline["version"])
    asset_ids = collect_asset_ids(snapshot)
    await resolve_project_assets(
        db, project_id=run["project_id"], workspace_id=run["workspace_id"],
        asset_ids=asset_ids, expires_in=300, snapshot=snapshot,
    )
    profile = (await db.execute(text("""
        select * from public.render_profiles
        where scope='global' and is_archived=false
          and width=:width and height=:height and fps=:fps
        order by is_default desc,priority desc,name limit 1
    """), {"width": snapshot["width"], "height": snapshot["height"], "fps": snapshot["fps"]})).mappings().first()
    if profile is None:
        raise StepInputError("No active render profile matches the immutable timeline snapshot")
    render_config = {
        "codec": profile["video_codec"], "format": profile["container"],
        "video_crf": profile["video_crf"], "video_bitrate": profile["video_bitrate"],
        "audio_codec": profile["audio_codec"], "audio_bitrate": profile["audio_bitrate"],
        "concurrency": profile["render_concurrency"], "priority": profile["priority"],
        "thumbnail_enabled": profile["thumbnail_enabled"], "preview_enabled": profile["preview_enabled"],
        "profile_key": profile["profile_key"], "profile_version": profile["version"],
    }
    max_attempts = await db.scalar(text("select max_attempts from public.platform_render_settings where singleton_id=1")) or 3
    existing = (await db.execute(
        text("select id,status,timeline_hash from public.render_jobs where workspace_id=:workspace and idempotency_key=:key"),
        {"workspace": run["workspace_id"], "key": envelope.idempotency_key},
    )).mappings().first()
    if existing:
        if existing["timeline_hash"] != digest:
            raise StepInputError("Render idempotency key conflicts with a different timeline snapshot")
        job_id = existing["id"]
    else:
        job_id = await db.scalar(text("""
            insert into public.render_jobs(
              workspace_id,project_id,requested_by,composition_id,composition_version,
              timeline_snapshot,timeline_hash,render_config,idempotency_key,render_profile_id,
              snapshot_version,asset_manifest,timeline_id,max_attempts,production_run_id,parent_step_id
            ) values(:workspace,:project,:actor,'GraphytionTimeline','2.0.0',
              cast(:snapshot as jsonb),:hash,cast(:config as jsonb),:key,:profile,
              :version,cast(:assets as jsonb),:timeline,:attempts,:run,:step) returning id
        """), {
            "workspace": run["workspace_id"], "project": run["project_id"], "actor": run["requested_by"],
            "snapshot": _canonical(snapshot), "hash": digest, "config": _canonical(render_config),
            "key": envelope.idempotency_key, "profile": profile["id"], "version": version or snapshot.get("version"),
            "assets": _canonical([str(asset_id) for asset_id in asset_ids]),
            "timeline": timeline_id, "attempts": max_attempts, "run": envelope.run_id,
            "step": envelope.step_id,
        })
    await _attach_child(db, step, "render_job", job_id, {
        "render_job_id": str(job_id), "timeline_hash": digest,
        "composition_version": "2.0.0", "idempotency_key": envelope.idempotency_key,
    })
    await db.commit()
    await notify_worker("render", str(job_id))


async def _dispatch_step(
    db: AsyncSession, step: dict[str, Any], envelope: StepEnvelope, run: dict[str, Any]
) -> None:
    handlers = {
        "creative": _dispatch_creative_gate,
        "media_generation": _dispatch_media,
        "voiceover": _dispatch_voiceover,
        "subtitle": _dispatch_subtitles,
        "timeline": _dispatch_timeline,
        "render": _dispatch_render,
    }
    handler = handlers.get(step["step_type"])
    if handler is None:
        raise StepInputError(f"Step type {step['step_type']} is derived from persisted artifacts or has no executable handler")
    if step["step_type"] == "creative":
        await handler(db, step, envelope)
    elif step["step_type"] in {"media_generation", "voiceover", "subtitle", "timeline", "render"}:
        await handler(db, step, envelope, run)
    await db.commit()


async def _fail_step(
    step: dict[str, Any], error: Exception, *, retryable: bool
) -> None:
    async with SessionLocal() as db:
        current = (await db.execute(text("""
            select production_run_id,attempt_count,max_attempts,worker_id
            from public.production_run_steps where id=:step for update
        """), {"step": step["id"]})).mappings().first()
        if not current or current["worker_id"] != WORKER_ID:
            await db.rollback()
            return
        retry = retryable and current["attempt_count"] < current["max_attempts"]
        delay = min(300, 2 ** min(int(current["attempt_count"]), 8))
        safe_message = str(error).replace("\n", " ")[:500]
        await db.execute(text("""
            update public.production_run_steps
               set status=:status,worker_id=null,lease_expires_at=null,heartbeat_at=null,
                   retry_count=retry_count+case when :retry then 1 else 0 end,
                   next_retry_at=case when :retry then now()+make_interval(secs=>:delay) else null end,
                   available_at=case when :retry then now()+make_interval(secs=>:delay) else available_at end,
                   error_code=:code,error_message_safe=:message,last_error_class=:class,
                   last_error_at=now(),completed_at=case when :retry then null else now() end,
                   external_operation_state=case when :cancelled then 'failed'
                     when external_operation_state in ('submitted','reconciling','unknown')
                     then 'unknown' else 'failed' end,updated_at=now()
             where id=:step and worker_id=:worker
        """), {
            "status": "cancelled" if cancelled else ("ready" if retry else "failed"),
            "retry": retry, "delay": delay,
            "code": "RUN_CANCELLED" if cancelled else ("STEP_INPUT_INVALID" if isinstance(error, (StepInputError, ValidationError)) else "STEP_EXECUTION_FAILED"),
            "message": safe_message, "class": "cancelled" if cancelled else ("transient" if retry else "permanent"),
            "step": step["id"], "worker": WORKER_ID,
        })
        await _append_event(db, current["production_run_id"],
            "step.cancelled" if cancelled else ("step.retry" if retry else "step.failed"), {
            "step_id": str(step["id"]), "step_key": step["step_key"],
            "worker_id": WORKER_ID, "retryable": retry, "retry_delay_seconds": delay if retry else None,
            "error_code": "STEP_INPUT_INVALID" if isinstance(error, (StepInputError, ValidationError)) else "STEP_EXECUTION_FAILED",
            "error_class": "transient" if retry else "permanent",
        })
        await db.execute(text("select private.graphytion_sync_production_run(:run)"), {"run": current["production_run_id"]})
        await db.commit()


async def _claim_one() -> dict[str, Any] | None:
    async with SessionLocal() as db:
        row = (await db.execute(
            text("select * from private.graphytion_claim_production_step(:worker,:lease)"),
            {"worker": WORKER_ID, "lease": LEASE_SECONDS},
        )).mappings().first()
        if row is None:
            await db.commit()
            return None
        claimed = dict(row)
        await db.commit()
        return claimed


async def _process_one(step: dict[str, Any]) -> None:
    heartbeat_task = asyncio.create_task(_heartbeat(step["id"]))
    try:
        async with SessionLocal() as db:
            envelope, run = await _load_envelope(db, step)
            await _append_event(db, step["production_run_id"], "step.started", {
                "step_id": str(step["id"]), "step_key": step["step_key"],
                "worker_id": WORKER_ID, "attempt_count": step["attempt_count"],
                "schema_version": envelope.schema_version,
            })
            await db.commit()
            await _dispatch_step(db, step, envelope, run)
    except asyncio.CancelledError:
        raise
    except Exception as exc:
        logger.exception("production_step_dispatch_failed", extra={
            "run_id": str(step["production_run_id"]), "step_id": str(step["id"]),
            "step_type": step["step_type"],
        })
        retryable = isinstance(exc, DBAPIError) and bool(getattr(exc, "connection_invalidated", False))
        await _fail_step(step, exc, retryable=retryable)
    finally:
        heartbeat_task.cancel()
        await asyncio.gather(heartbeat_task, return_exceptions=True)


async def _reconcile_runs() -> None:
    async with SessionLocal() as db:
        rows = (await db.execute(text("""
            select id,requested_by from public.production_runs
            where status in ('queued','planning','ready_for_review','cancel_requested')
            order by updated_at limit 50
        """))).mappings().all()
        for row in rows:
            await set_rls_subject(db, str(row["requested_by"]))
            await db.execute(text("select private.graphytion_sync_production_run(:run)"), {"run": row["id"]})
        await db.commit()


async def run_dispatcher() -> None:
    logger.info("production_orchestrator_dispatcher_started", extra={
        "worker_id": WORKER_ID, "lease_seconds": LEASE_SECONDS,
        "persistence": "supabase_postgresql", "schema_version": SCHEMA_VERSION,
    })
    while True:
        try:
            await _reconcile_runs()
            step = await _claim_one()
            if step is None:
                await asyncio.sleep(POLL_SECONDS)
                continue
            await _process_one(step)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("production_orchestrator_poll_failed")
            await asyncio.sleep(POLL_SECONDS)
