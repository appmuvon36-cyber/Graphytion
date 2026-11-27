from __future__ import annotations

from copy import deepcopy
from typing import Any
from uuid import uuid4


def apply_brand_tokens(snapshot: dict[str, Any], config: dict[str, Any] | None) -> dict[str, Any]:
    """Apply immutable Brand Kit tokens and materialize its logo as a real timeline clip."""
    result = deepcopy(snapshot)
    if not config:
        return result
    colors = config.get("colors") or {}
    typography = config.get("typography") or {}
    for clip in result.get("clips", []):
        if clip.get("brandKitLogo") is True:
            continue
        key = clip.get("componentKey")
        props = clip.setdefault("props", {})
        if key == "core.title-card.v1":
            if colors.get("primary"):
                props["background"] = colors["primary"]
        elif key == "text.basic.v1":
            if colors.get("text"):
                props["color"] = colors["text"]
            if typography.get("body_font_family"):
                props["fontFamily"] = typography["body_font_family"]
            if typography.get("font_weight"):
                try:
                    props["fontWeight"] = int(typography["font_weight"])
                except (TypeError, ValueError):
                    pass
        elif key == "text.subtitle.v1":
            if colors.get("text"):
                props["color"] = colors["text"]
            if colors.get("surface"):
                props["background"] = colors["surface"]
        elif key == "visual.shape.v1":
            if colors.get("accent"):
                props["fill"] = colors["accent"]
    if colors.get("background"):
        result["background"] = colors["background"]

    # A logo is not metadata: it is an allowlisted image layer in the immutable
    # composition snapshot, resolved through the normal private asset pipeline.
    logo_asset_id = config.get("logo_asset_id")
    if logo_asset_id:
        clips = result.setdefault("clips", [])
        clips[:] = [clip for clip in clips if clip.get("brandKitLogo") is not True]
        tracks = result.setdefault("tracks", [])
        if not tracks:
            raise ValueError("Brand Kit logo requires a valid composition track")
        top_z = max(int(track.get("zIndex", 0)) for track in tracks)
        visual_tracks = [track for track in tracks if track.get("kind") == "visual"]
        if visual_tracks:
            track = max(visual_tracks, key=lambda item: int(item.get("zIndex", 0)))
            track["zIndex"] = top_z + 1
        else:
            if len(tracks) >= 32:
                raise ValueError("Brand Kit logo cannot be added: composition has reached the 32-track limit")
            track = {
                "id": str(uuid4()), "kind": "visual", "name": "Brand Logo",
                "zIndex": top_z + 1, "visible": True, "locked": True,
                "muted": False, "volume": 1.0,
            }
            tracks.append(track)
        asset_id = str(logo_asset_id)
        clips.append({
            "id": str(uuid4()), "trackId": track["id"], "startFrame": 0,
            "durationFrames": int(result["durationFrames"]), "trimStartFrames": 0,
            "playbackRate": 1, "componentKey": "visual.image.v1",
            "componentVersion": "1.0.0", "assetId": asset_id,
            "brandKitLogo": True,
            "props": {
                "assetId": asset_id, "fit": "contain", "position": "center",
                "opacity": 1, "widthPercent": 16, "heightPercent": 12,
                "anchor": "top-right", "marginPercent": 4,
            },
        })
        refs = result.setdefault("assetRefs", [])
        if not any(str(ref.get("assetId")) == asset_id for ref in refs):
            refs.append({"assetId": asset_id, "kind": "image", "required": True})
    return result
