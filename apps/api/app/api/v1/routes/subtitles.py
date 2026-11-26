from __future__ import annotations

import json
import re
from typing import Any
from uuid import UUID

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import AuthenticatedClaims, DbSession
from app.core.database import set_rls_subject
from app.services.workspace_authorization import WorkspacePermissionResolver

router = APIRouter()
permissions = WorkspacePermissionResolver()


class SubtitleSegmentInput(BaseModel):
    id: UUID | None = None
    segment_index: int = Field(ge=0)
    start_ms: int = Field(ge=0)
    end_ms: int = Field(gt=0)
    text: str = Field(min_length=1, max_length=4000)
    speaker: str | None = Field(default=None, max_length=120)
    word_timings: list[dict[str, Any]] = Field(default_factory=list, max_length=500)
    style_config: dict[str, Any] = Field(default_factory=dict)
    position_config: dict[str, Any] = Field(default_factory=dict)
    alignment_metadata: dict[str, Any] = Field(default_factory=dict)
    audio_asset_id: UUID | None = None


class SubtitleTrackInput(BaseModel):
    language: str = Field(default="id-ID", min_length=2, max_length=16)
    format: str = Field(default="webvtt", pattern=r"^(webvtt|srt)$")
    style_config: dict[str, Any] = Field(default_factory=dict)
    segments: list[SubtitleSegmentInput] = Field(default_factory=list, max_length=5000)


class SubtitleImport(BaseModel):
    language: str = Field(default="id-ID", min_length=2, max_length=16)
    format: str = Field(pattern=r"^(webvtt|srt)$")
    content: str = Field(min_length=1, max_length=2_000_000)
    style_config: dict[str, Any] = Field(default_factory=dict)


class SegmentPatch(BaseModel):
    segment_index: int | None = Field(default=None, ge=0)
    start_ms: int | None = Field(default=None, ge=0)
    end_ms: int | None = Field(default=None, gt=0)
    text: str | None = Field(default=None, min_length=1, max_length=4000)
    speaker: str | None = Field(default=None, max_length=120)
    word_timings: list[dict[str, Any]] | None = Field(default=None, max_length=500)
    style_config: dict[str, Any] | None = None
    position_config: dict[str, Any] | None = None
    alignment_metadata: dict[str, Any] | None = None
    audio_asset_id: UUID | None = None


class SegmentSplit(BaseModel):
    split_at_ms: int = Field(gt=0)
    second_text: str | None = Field(default=None, min_length=1, max_length=4000)


class SegmentMerge(BaseModel):
    segment_ids: list[UUID] = Field(min_length=2, max_length=100)
    separator: str = " "


class SegmentReorder(BaseModel):
    segment_ids: list[UUID] = Field(min_length=1, max_length=5000)


def _actor(claims: dict[str, Any]) -> UUID:
    try:
        return UUID(str(claims["sub"]))
    except (KeyError, ValueError, TypeError) as exc:
        raise HTTPException(401, "Invalid authenticated subject") from exc


async def _scope(db: AsyncSession, project: UUID, actor: UUID, permission: str) -> UUID:
    workspace = await db.scalar(
        text("select workspace_id from public.video_projects where id=:id and status<>'deleted'"),
        {"id": project},
    )
    if not workspace:
        raise HTTPException(404, "Project not found")
    await permissions.require_permission(
        session=db, user_id=str(actor), workspace_id=str(workspace), permission=permission
    )
    await set_rls_subject(db, str(actor))
    return workspace


def _validate_segment_values(start: int, end: int, words: list[dict[str, Any]]) -> None:
    if end <= start:
        raise HTTPException(422, "Subtitle segment end_ms must exceed start_ms")
    if len(words) > 500:
        raise HTTPException(422, "Too many word timing entries")
    for word in words:
        if (
            not isinstance(word, dict)
            or not isinstance(word.get("start_ms"), int)
            or not isinstance(word.get("end_ms"), int)
            or not isinstance(word.get("text"), str)
            or not start <= word["start_ms"] < word["end_ms"] <= end
        ):
            raise HTTPException(422, "Word timings must be contained within their segment")


def _validate_segments(segments: list[SubtitleSegmentInput]) -> None:
    previous = -1
    for item in segments:
        _validate_segment_values(item.start_ms, item.end_ms, item.word_timings)
        if item.start_ms < previous:
            raise HTTPException(422, "Subtitle segments must be ordered by start time")
        previous = item.start_ms


def _snapshot(row: Any) -> dict[str, Any]:
    return {
        "id": str(row["id"]),
        "segment_index": row["segment_index"],
        "start_ms": row["start_ms"],
        "end_ms": row["end_ms"],
        "text": row["text"],
        "speaker": row["speaker"],
        "word_timings": row["word_timings"] or [],
        "style_config": row.get("style_config") or {},
        "position_config": row.get("position_config") or {},
        "alignment_metadata": row.get("alignment_metadata") or {},
        "audio_asset_id": str(row["audio_asset_id"]) if row.get("audio_asset_id") else None,
        "version": row.get("version", 1),
    }


async def _revision(
    db: AsyncSession,
    track_id: UUID,
    segment_id: UUID,
    operation: str,
    snapshot: dict[str, Any],
    actor: UUID,
    request: Request,
) -> None:
    revision = await db.scalar(
        text("select coalesce(max(revision),0)+1 from public.subtitle_segment_revisions where segment_id=:id"),
        {"id": segment_id},
    )
    await db.execute(
        text("""insert into public.subtitle_segment_revisions
        (track_id,segment_id,revision,operation,snapshot,actor_user_id,request_id)
        values(:track,:segment,:revision,:operation,cast(:snapshot as jsonb),:actor,:request)"""),
        {
            "track": track_id,
            "segment": segment_id,
            "revision": revision,
            "operation": operation,
            "snapshot": json.dumps(snapshot),
            "actor": actor,
            "request": getattr(request.state, "request_id", None),
        },
    )


async def _audit(
    db: AsyncSession, workspace: UUID, actor: UUID, action: str, resource: UUID, request: Request
) -> None:
    await db.execute(
        text("""insert into public.audit_logs
        (actor_user_id,workspace_id,action,resource_type,resource_id,request_id)
        values(:actor,:workspace,:action,'subtitle_segment',:resource,:request)"""),
        {
            "actor": actor,
            "workspace": workspace,
            "action": action,
            "resource": resource,
            "request": getattr(request.state, "request_id", None),
        },
    )


async def _bump_track(db: AsyncSession, track_id: UUID) -> None:
    await db.execute(
        text("update public.subtitle_tracks set version=version+1 where id=:id"),
        {"id": track_id},
    )


async def _insert_segment(
    db: AsyncSession,
    track_id: UUID,
    item: SubtitleSegmentInput,
    actor: UUID,
    request: Request,
    operation: str = "created",
) -> dict[str, Any]:
    _validate_segment_values(item.start_ms, item.end_ms, item.word_timings)
    row = (
        await db.execute(
            text("""insert into public.subtitle_segments
            (track_id,segment_index,start_ms,end_ms,text,speaker,word_timings,style_config,
             position_config,alignment_metadata,audio_asset_id)
            values(:track,:idx,:start,:end,:text,:speaker,cast(:words as jsonb),
             cast(:style as jsonb),cast(:position as jsonb),cast(:alignment as jsonb),:audio)
            returning id,segment_index,start_ms,end_ms,text,speaker,word_timings,style_config,
                      position_config,alignment_metadata,audio_asset_id,version"""),
            {
                "track": track_id, "idx": item.segment_index, "start": item.start_ms,
                "end": item.end_ms, "text": item.text, "speaker": item.speaker,
                "words": json.dumps(item.word_timings), "style": json.dumps(item.style_config),
                "position": json.dumps(item.position_config),
                "alignment": json.dumps(item.alignment_metadata), "audio": item.audio_asset_id,
            },
        )
    ).mappings().one()
    result = _snapshot(row)
    await _revision(db, track_id, row["id"], operation, result, actor, request)
    return result


def _timestamp(ms: int, comma: bool) -> str:
    hours, rem = divmod(ms, 3_600_000)
    minutes, rem = divmod(rem, 60_000)
    seconds, millis = divmod(rem, 1000)
    return f"{hours:02d}:{minutes:02d}:{seconds:02d}{',' if comma else '.'}{millis:03d}"


def _parse_timestamp(value: str) -> int:
    match = re.fullmatch(r"(?:(\d{2}):)?(\d{2}):(\d{2})[,.](\d{1,3})", value.strip())
    if not match:
        raise HTTPException(422, "Invalid subtitle timestamp")
    hours, minutes, seconds, millis = match.groups()
    return ((int(hours or 0) * 60 + int(minutes)) * 60 + int(seconds)) * 1000 + int(millis.ljust(3, "0"))


def _parse(content: str, fmt: str) -> list[SubtitleSegmentInput]:
    raw = content.replace("\r\n", "\n").replace("\r", "\n").strip()
    if fmt == "webvtt":
        if not raw.startswith("WEBVTT"):
            raise HTTPException(422, "WebVTT header is required")
        raw = raw.split("\n", 1)[1] if "\n" in raw else ""
    segments: list[SubtitleSegmentInput] = []
    for block in re.split(r"\n\s*\n", raw):
        lines = [line.strip("\ufeff") for line in block.strip().split("\n") if line.strip()]
        timing = next((index for index, line in enumerate(lines) if "-->" in line), None)
        if timing is None:
            continue
        left, right = [part.strip().split(" ")[0] for part in lines[timing].split("-->", 1)]
        start, end = _parse_timestamp(left), _parse_timestamp(right)
        value = "\n".join(lines[timing + 1:]).strip()
        if value:
            segments.append(SubtitleSegmentInput(
                segment_index=len(segments), start_ms=start, end_ms=end,
                text=re.sub(r"<[^>]+>", "", value),
            ))
    if not segments:
        raise HTTPException(422, "No valid subtitle segments were found")
    _validate_segments(segments)
    return segments


def _export(segments: list[dict[str, Any]], fmt: str) -> str:
    rows = ["WEBVTT"] if fmt == "webvtt" else []
    for index, item in enumerate(segments):
        if fmt == "srt":
            rows.append(str(index + 1))
        rows.append(_timestamp(item["start_ms"], fmt == "srt") + " --> " + _timestamp(item["end_ms"], fmt == "srt"))
        rows.extend([item["text"], ""])
    return "\n".join(rows).strip() + "\n"


async def _create_track(
    db: AsyncSession, project: UUID, workspace: UUID, actor: UUID,
    payload: SubtitleTrackInput, request: Request,
) -> Any:
    _validate_segments(payload.segments)
    track = (
        await db.execute(
            text("""insert into public.subtitle_tracks
            (workspace_id,project_id,language,format,style_config,created_by)
            values(:workspace,:project,:language,:format,cast(:style as jsonb),:actor)
            returning id,version,created_at"""),
            {
                "workspace": workspace, "project": project, "language": payload.language,
                "format": payload.format, "style": json.dumps(payload.style_config), "actor": actor,
            },
        )
    ).mappings().one()
    for segment in payload.segments:
        await _insert_segment(db, track["id"], segment, actor, request)
    await db.execute(
        text("""insert into public.audit_logs
        (actor_user_id,workspace_id,action,resource_type,resource_id,request_id)
        values(:actor,:workspace,'subtitle_track.created','subtitle_track',:id,:request)"""),
        {"actor": actor, "workspace": workspace, "id": track["id"],
         "request": getattr(request.state, "request_id", None)},
    )
    await db.commit()
    return track


async def _get_track(
    db: AsyncSession, project: UUID, workspace: UUID, track_id: UUID, lock: bool = False
) -> Any:
    suffix = " for update" if lock else ""
    track = (await db.execute(
        text("select id,language,format,version,style_config from public.subtitle_tracks "
             "where id=:id and project_id=:project and workspace_id=:workspace" + suffix),
        {"id": track_id, "project": project, "workspace": workspace},
    )).mappings().first()
    if not track:
        raise HTTPException(404, "Subtitle track not found")
    return track


async def _get_segment(db: AsyncSession, track_id: UUID, segment_id: UUID, lock: bool = False) -> Any:
    suffix = " for update" if lock else ""
    row = (await db.execute(
        text("""select id,track_id,segment_index,start_ms,end_ms,text,speaker,word_timings,
        style_config,position_config,alignment_metadata,audio_asset_id,version
        from public.subtitle_segments where id=:id and track_id=:track""" + suffix),
        {"id": segment_id, "track": track_id},
    )).mappings().first()
    if not row:
        raise HTTPException(404, "Subtitle segment not found")
    return row


@router.get("/projects/{project_id}/subtitles")
async def list_subtitle_tracks(project_id: UUID, claims: AuthenticatedClaims, db: AsyncSession = DbSession):
    actor = _actor(claims)
    workspace = await _scope(db, project_id, actor, "project.read")
    tracks = (await db.execute(
        text("""select id,language,format,version,style_config,created_at from public.subtitle_tracks
        where project_id=:project and workspace_id=:workspace order by created_at desc"""),
        {"project": project_id, "workspace": workspace},
    )).mappings().all()
    result = []
    for track in tracks:
        rows = (await db.execute(
            text("""select id,segment_index,start_ms,end_ms,text,speaker,word_timings,style_config,
            position_config,alignment_metadata,audio_asset_id,version from public.subtitle_segments
            where track_id=:id order by segment_index"""),
            {"id": track["id"]},
        )).mappings().all()
        result.append({**dict(track), "segments": [_snapshot(row) for row in rows]})
    return {"data": result}


@router.post("/projects/{project_id}/subtitles", status_code=201)
async def create_subtitle_track(
    project_id: UUID, payload: SubtitleTrackInput, request: Request,
    claims: AuthenticatedClaims, db: AsyncSession = DbSession,
):
    actor = _actor(claims)
    workspace = await _scope(db, project_id, actor, "project.update")
    track = await _create_track(db, project_id, workspace, actor, payload, request)
    return {"data": {"id": str(track["id"]), "version": track["version"], "created_at": track["created_at"]}}


@router.put("/projects/{project_id}/subtitles/{track_id}")
async def update_subtitle_track(
    project_id: UUID, track_id: UUID, payload: SubtitleTrackInput, request: Request,
    claims: AuthenticatedClaims, db: AsyncSession = DbSession,
):
    """Update track metadata and upsert only supplied segments; omitted IDs are never deleted."""
    actor = _actor(claims)
    workspace = await _scope(db, project_id, actor, "project.update")
    _validate_segments(payload.segments)
    await _get_track(db, project_id, workspace, track_id, lock=True)
    await db.execute(
        text("""update public.subtitle_tracks set language=:language,format=:format,
        style_config=cast(:style as jsonb),version=version+1 where id=:id"""),
        {"language": payload.language, "format": payload.format,
         "style": json.dumps(payload.style_config), "id": track_id},
    )
    saved = []
    for item in payload.segments:
        if item.id:
            existing = await _get_segment(db, track_id, item.id, lock=True)
            _validate_segment_values(item.start_ms, item.end_ms, item.word_timings)
            await db.execute(
                text("""update public.subtitle_segments set segment_index=:idx,start_ms=:start,end_ms=:end,
                text=:text,speaker=:speaker,word_timings=cast(:words as jsonb),
                style_config=cast(:style as jsonb),position_config=cast(:position as jsonb),
                alignment_metadata=cast(:alignment as jsonb),audio_asset_id=:audio,
                version=version+1,updated_at=now() where id=:id"""),
                {"idx": item.segment_index, "start": item.start_ms, "end": item.end_ms,
                 "text": item.text, "speaker": item.speaker, "words": json.dumps(item.word_timings),
                 "style": json.dumps(item.style_config), "position": json.dumps(item.position_config),
                 "alignment": json.dumps(item.alignment_metadata), "audio": item.audio_asset_id,
                 "id": existing["id"]},
            )
            row = await _get_segment(db, track_id, item.id)
            saved.append(_snapshot(row))
            await _revision(db, track_id, item.id, "updated", _snapshot(row), actor, request)
        else:
            saved.append(await _insert_segment(db, track_id, item, actor, request))
    await _audit(db, workspace, actor, "subtitle_track.updated", track_id, request)
    await db.commit()
    return {"data": {"id": str(track_id), "status": "updated", "segments": saved}}


@router.post("/projects/{project_id}/subtitles/{track_id}/segments", status_code=201)
async def create_subtitle_segment(
    project_id: UUID, track_id: UUID, payload: SubtitleSegmentInput, request: Request,
    claims: AuthenticatedClaims, db: AsyncSession = DbSession,
):
    actor = _actor(claims)
    workspace = await _scope(db, project_id, actor, "project.update")
    await _get_track(db, project_id, workspace, track_id, lock=True)
    result = await _insert_segment(db, track_id, payload, actor, request)
    await _bump_track(db, track_id)
    await _audit(db, workspace, actor, "subtitle_segment.created", UUID(result["id"]), request)
    await db.commit()
    return {"data": result}


@router.patch("/projects/{project_id}/subtitles/{track_id}/segments/{segment_id}")
async def update_subtitle_segment(
    project_id: UUID, track_id: UUID, segment_id: UUID, payload: SegmentPatch,
    request: Request, claims: AuthenticatedClaims, db: AsyncSession = DbSession,
):
    actor = _actor(claims)
    workspace = await _scope(db, project_id, actor, "project.update")
    await _get_track(db, project_id, workspace, track_id, lock=True)
    existing = await _get_segment(db, track_id, segment_id, lock=True)
    changes = payload.model_dump(exclude_unset=True)
    merged = {**_snapshot(existing), **changes}
    _validate_segment_values(merged["start_ms"], merged["end_ms"], merged.get("word_timings") or [])
    await db.execute(
        text("""update public.subtitle_segments set segment_index=:idx,start_ms=:start,end_ms=:end,
        text=:text,speaker=:speaker,word_timings=cast(:words as jsonb),
        style_config=cast(:style as jsonb),position_config=cast(:position as jsonb),
        alignment_metadata=cast(:alignment as jsonb),audio_asset_id=:audio,
        version=version+1,updated_at=now() where id=:id"""),
        {"idx": merged["segment_index"], "start": merged["start_ms"], "end": merged["end_ms"],
         "text": merged["text"], "speaker": merged.get("speaker"),
         "words": json.dumps(merged.get("word_timings") or []),
         "style": json.dumps(merged.get("style_config") or {}),
         "position": json.dumps(merged.get("position_config") or {}),
         "alignment": json.dumps(merged.get("alignment_metadata") or {}),
         "audio": merged.get("audio_asset_id"), "id": segment_id},
    )
    row = await _get_segment(db, track_id, segment_id)
    result = _snapshot(row)
    await _revision(db, track_id, segment_id, "updated", result, actor, request)
    await _bump_track(db, track_id)
    await _audit(db, workspace, actor, "subtitle_segment.updated", segment_id, request)
    await db.commit()
    return {"data": result}


@router.delete("/projects/{project_id}/subtitles/{track_id}/segments/{segment_id}")
async def delete_subtitle_segment(
    project_id: UUID, track_id: UUID, segment_id: UUID, request: Request,
    claims: AuthenticatedClaims, db: AsyncSession = DbSession,
):
    actor = _actor(claims)
    workspace = await _scope(db, project_id, actor, "project.update")
    await _get_track(db, project_id, workspace, track_id, lock=True)
    row = await _get_segment(db, track_id, segment_id, lock=True)
    await _revision(db, track_id, segment_id, "deleted", _snapshot(row), actor, request)
    await db.execute(text("delete from public.subtitle_segments where id=:id"), {"id": segment_id})
    await _bump_track(db, track_id)
    await _audit(db, workspace, actor, "subtitle_segment.deleted", segment_id, request)
    await db.commit()
    return {"data": {"id": str(segment_id), "status": "deleted"}}


@router.post("/projects/{project_id}/subtitles/{track_id}/segments/{segment_id}/split")
async def split_subtitle_segment(
    project_id: UUID, track_id: UUID, segment_id: UUID, payload: SegmentSplit,
    request: Request, claims: AuthenticatedClaims, db: AsyncSession = DbSession,
):
    actor = _actor(claims)
    workspace = await _scope(db, project_id, actor, "project.update")
    await _get_track(db, project_id, workspace, track_id, lock=True)
    row = await _get_segment(db, track_id, segment_id, lock=True)
    if not row["start_ms"] < payload.split_at_ms < row["end_ms"]:
        raise HTTPException(422, "split_at_ms must be inside the segment")
    old = _snapshot(row)
    first_text, second_text = old["text"], payload.second_text
    if second_text is None:
        words = old["text"].split()
        if len(words) < 2:
            raise HTTPException(422, "second_text is required when the segment has fewer than two words")
        midpoint = max(1, len(words) // 2)
        first_text, second_text = " ".join(words[:midpoint]), " ".join(words[midpoint:])
    await db.execute(
        text("""update public.subtitle_segments set end_ms=:end,text=:text,word_timings='[]'::jsonb,
        version=version+1,updated_at=now() where id=:id"""),
        {"end": payload.split_at_ms, "text": first_text, "id": segment_id},
    )
    first = _snapshot(await _get_segment(db, track_id, segment_id))
    second_index = int(old["segment_index"]) + 1
    await db.execute(
        text("update public.subtitle_segments set segment_index=segment_index+10000 where track_id=:track and segment_index>=:idx"),
        {"track": track_id, "idx": second_index},
    )
    await db.execute(
        text("update public.subtitle_segments set segment_index=segment_index-9999 where track_id=:track and segment_index>=:offset"),
        {"track": track_id, "offset": second_index + 10000},
    )
    created = await _insert_segment(
        db, track_id,
        SubtitleSegmentInput(segment_index=second_index, start_ms=payload.split_at_ms,
                             end_ms=old["end_ms"], text=second_text, speaker=old["speaker"]),
        actor, request, "split",
    )
    await _revision(db, track_id, segment_id, "split", first, actor, request)
    await _bump_track(db, track_id)
    await _audit(db, workspace, actor, "subtitle_segment.split", segment_id, request)
    await db.commit()
    return {"data": {"segments": [first, created]}}


@router.post("/projects/{project_id}/subtitles/{track_id}/segments/merge")
async def merge_subtitle_segments(
    project_id: UUID, track_id: UUID, payload: SegmentMerge, request: Request,
    claims: AuthenticatedClaims, db: AsyncSession = DbSession,
):
    actor = _actor(claims)
    workspace = await _scope(db, project_id, actor, "project.update")
    await _get_track(db, project_id, workspace, track_id, lock=True)
    if len(set(payload.segment_ids)) != len(payload.segment_ids):
        raise HTTPException(422, "segment_ids must be unique")
    rows = (await db.execute(
        text("""select id,track_id,segment_index,start_ms,end_ms,text,speaker,word_timings,
        style_config,position_config,alignment_metadata,audio_asset_id,version
        from public.subtitle_segments where track_id=:track and id=any(:ids)
        order by segment_index for update"""),
        {"track": track_id, "ids": payload.segment_ids},
    )).mappings().all()
    if len(rows) != len(payload.segment_ids):
        raise HTTPException(404, "One or more subtitle segments were not found")
    ordered_ids = [row["id"] for row in rows]
    if set(ordered_ids) != set(payload.segment_ids):
        raise HTTPException(422, "Segments do not belong to this track")
    if any(rows[i]["end_ms"] > rows[i + 1]["start_ms"] for i in range(len(rows) - 1)):
        raise HTTPException(422, "Overlapping segments cannot be merged")
    survivor = rows[0]
    if len({str(row["audio_asset_id"]) for row in rows}) > 1:
        raise HTTPException(422, "Segments linked to different audio assets cannot be merged")
    for row in rows:
        await _revision(db, track_id, row["id"], "merged", _snapshot(row), actor, request)
    merged_text = payload.separator.join(row["text"] for row in rows)
    merged_words = [word for row in rows for word in (row["word_timings"] or [])]
    await db.execute(
        text("""update public.subtitle_segments set end_ms=:end,text=:text,word_timings=cast(:words as jsonb),
        version=version+1,updated_at=now() where id=:id"""),
        {"end": rows[-1]["end_ms"], "text": merged_text, "words": json.dumps(merged_words), "id": survivor["id"]},
    )
    await db.execute(
        text("delete from public.subtitle_segments where track_id=:track and id=any(:ids) and id<>:keep"),
        {"track": track_id, "ids": payload.segment_ids, "keep": survivor["id"]},
    )
    result = _snapshot(await _get_segment(db, track_id, survivor["id"]))
    await _revision(db, track_id, survivor["id"], "merged", result, actor, request)
    await _bump_track(db, track_id)
    await _audit(db, workspace, actor, "subtitle_segment.merged", survivor["id"], request)
    await db.commit()
    return {"data": result}


@router.put("/projects/{project_id}/subtitles/{track_id}/segments/reorder")
async def reorder_subtitle_segments(
    project_id: UUID, track_id: UUID, payload: SegmentReorder, request: Request,
    claims: AuthenticatedClaims, db: AsyncSession = DbSession,
):
    actor = _actor(claims)
    workspace = await _scope(db, project_id, actor, "project.update")
    await _get_track(db, project_id, workspace, track_id, lock=True)
    rows = (await db.execute(
        text("select id,segment_index,start_ms,end_ms,text,speaker,word_timings,style_config,position_config,alignment_metadata,audio_asset_id,version "
             "from public.subtitle_segments where track_id=:track for update"),
        {"track": track_id},
    )).mappings().all()
    existing_ids = {row["id"] for row in rows}
    if len(set(payload.segment_ids)) != len(payload.segment_ids) or set(payload.segment_ids) != existing_ids:
        raise HTTPException(422, "Reorder must contain every existing segment exactly once")
    by_id = {row["id"]: row for row in rows}
    await db.execute(
        text("update public.subtitle_segments set segment_index=segment_index+10000 where track_id=:track"),
        {"track": track_id},
    )
    for index, segment_id in enumerate(payload.segment_ids):
        row = by_id[segment_id]
        await db.execute(
            text("update public.subtitle_segments set segment_index=:idx,version=version+1,updated_at=now() where id=:id"),
            {"idx": index, "id": segment_id},
        )
        updated = _snapshot({**dict(row), "segment_index": index, "version": row["version"] + 1})
        await _revision(db, track_id, segment_id, "reordered", updated, actor, request)
    await _bump_track(db, track_id)
    await _audit(db, workspace, actor, "subtitle_segment.reordered", track_id, request)
    await db.commit()
    return {"data": {"segment_ids": [str(item) for item in payload.segment_ids], "status": "reordered"}}


@router.get("/projects/{project_id}/subtitles/{track_id}/segments/{segment_id}/revisions")
async def list_subtitle_segment_revisions(
    project_id: UUID, track_id: UUID, segment_id: UUID,
    claims: AuthenticatedClaims, db: AsyncSession = DbSession,
):
    actor = _actor(claims)
    workspace = await _scope(db, project_id, actor, "project.read")
    await _get_track(db, project_id, workspace, track_id)
    await _get_segment(db, track_id, segment_id)
    rows = (await db.execute(
        text("""select id,revision,operation,snapshot,actor_user_id,request_id,created_at
        from public.subtitle_segment_revisions where track_id=:track and segment_id=:segment
        order by revision"""),
        {"track": track_id, "segment": segment_id},
    )).mappings().all()
    return {"data": [dict(row) for row in rows]}


@router.post("/projects/{project_id}/subtitles/import", status_code=201)
async def import_subtitles(
    project_id: UUID, payload: SubtitleImport, request: Request,
    claims: AuthenticatedClaims, db: AsyncSession = DbSession,
):
    actor = _actor(claims)
    workspace = await _scope(db, project_id, actor, "project.update")
    segments = _parse(payload.content, payload.format)
    track = await _create_track(
        db, project_id, workspace, actor,
        SubtitleTrackInput(language=payload.language, format=payload.format,
                           style_config=payload.style_config, segments=segments),
        request,
    )
    return {"data": {"id": str(track["id"]), "version": track["version"], "segment_count": len(segments)}}


@router.get("/projects/{project_id}/subtitles/{track_id}/export")
async def export_subtitles(
    project_id: UUID, track_id: UUID, claims: AuthenticatedClaims, db: AsyncSession = DbSession,
):
    actor = _actor(claims)
    workspace = await _scope(db, project_id, actor, "project.read")
    track = await _get_track(db, project_id, workspace, track_id)
    rows = (await db.execute(
        text("select start_ms,end_ms,text from public.subtitle_segments where track_id=:id order by segment_index"),
        {"id": track_id},
    )).mappings().all()
    return {"data": {"format": track["format"], "language": track["language"],
                     "content": _export([dict(row) for row in rows], track["format"])}}
