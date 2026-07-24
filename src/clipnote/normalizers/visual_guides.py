"""Preserve the existing how-to normalization behavior."""
from .common import mmss_to_sec

TYPE_ALIASES = {
    "shape": "state",
    "pattern": "texture",
    "direction": "position",
    "setting": "position",
    "location": "position",
    "length": "size",
}


def normalize_visual_guides(data: dict) -> dict:
    warnings = []
    for step in data.get("steps", []):
        step["t_start"] = mmss_to_sec(step.get("t_start"))
        step["t_end"] = mmss_to_sec(step.get("t_end"))
        step.pop("ambiguity", None)
    for index, guide in enumerate(data.get("visual_guides", [])):
        guide["best_visual_timestamp"] = mmss_to_sec(
            guide.get("best_visual_timestamp"))
        if not guide.get("source_phrase") and guide.get("phrase"):
            guide["source_phrase"] = guide["phrase"]
            warnings.append(
                f"{guide.get('id', index)}: source_phrase를 phrase로 보완")
        if guide.get("importance") is None:
            guide["importance"] = max(0.5, 1.0 - index * 0.1)
            warnings.append(
                f"{guide.get('id', index)}: importance 자동 보완")
        guide_type = guide.get("type")
        if guide_type in TYPE_ALIASES:
            guide["type"] = TYPE_ALIASES[guide_type]
            warnings.append(
                f"{guide.get('id', index)}: type {guide_type}→{guide['type']}")
    if warnings:
        data["_normalization_warnings"] = warnings
    return data

