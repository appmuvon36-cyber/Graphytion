from __future__ import annotations

from copy import deepcopy
from typing import Any


def apply_brand_tokens(snapshot: dict[str, Any], config: dict[str, Any] | None) -> dict[str, Any]:
    """Apply workspace Brand Kit tokens to allowlisted composition props before validation/render."""
    result = deepcopy(snapshot)
    if not config:
        return result
    colors = config.get("colors") or {}
    typography = config.get("typography") or {}
    for clip in result.get("clips", []):
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
    return result
