#!/usr/bin/env python3
"""Validate normalized analysis against the core visual-guide contract."""

AMBIGUITY_TYPES = {"size", "thickness", "color", "state", "amount",
                   "position", "angle", "action", "texture"}
VAGUE = ["적당히", "적당량", "알맞게", "대충", "적절히", "먹기 좋게"]


def validate(data: dict):
    """Return (errors, warnings). Errors are contract violations."""
    errors, warnings = [], []
    duration = data.get("_duration")

    for field in ("_profile", "_output_language"):
        if not data.get(field):
            errors.append(f"{field} 메타데이터 없음")
    if not (data.get("title") or "").strip():
        errors.append("title 비어 있음")

    steps = data.get("steps")
    if not isinstance(steps, list) or not steps:
        errors.append("steps가 비어 있거나 배열이 아님")
        return errors, warnings
    if not isinstance(data.get("visual_guides"), list):
        errors.append("visual_guides가 배열이 아님")
        return errors, warnings
    if not data.get("materials"):
        warnings.append("materials 비어 있음 (준비물 없는 영상이면 정상)")

    step_ids, previous_start = set(), -1
    for index, step in enumerate(steps):
        tag = f"step[{index}] id={step.get('id')}"
        if "ambiguity" in step:
            errors.append(f"{tag}: legacy ambiguity 필드 금지")
        step_id = step.get("id")
        if not isinstance(step_id, int):
            errors.append(f"{tag}: id가 정수 아님")
        elif step_id in step_ids:
            errors.append(f"{tag}: id 중복")
        else:
            step_ids.add(step_id)
        for field in ("summary", "detail"):
            if not (step.get(field) or "").strip():
                errors.append(f"{tag}: {field} 비어 있음")
        start, end = step.get("t_start"), step.get("t_end")
        if not isinstance(start, int) or not isinstance(end, int):
            errors.append(f"{tag}: t_start/t_end가 정수 아님 ({start},{end})")
            continue
        if start < 0 or start > end:
            errors.append(f"{tag}: 잘못된 구간 ({start}-{end})")
        if duration is not None and end > duration:
            errors.append(f"{tag}: t_end가 영상 길이 초과 ({end}>{duration})")
        if start < previous_start:
            warnings.append(f"{tag}: 시작 시간이 이전 단계보다 앞섬 ({start}<{previous_start})")
        previous_start = start

    guides = data["visual_guides"]
    max_guides = data.get("_max_visual_guides", 5)
    if len(guides) > max_guides:
        errors.append(f"visual_guides {len(guides)}개 (설정 상한 {max_guides})")
    if not guides:
        warnings.append("visual_guides 0개 (시각 가이드 없음)")

    guide_ids = set()
    for index, guide in enumerate(guides):
        tag = f"visual_guide[{index}] id={guide.get('id')}"
        guide_id = guide.get("id")
        if not isinstance(guide_id, str) or not guide_id.startswith("vg-"):
            errors.append(f"{tag}: id 형식 오류")
        elif guide_id in guide_ids:
            errors.append(f"{tag}: id 중복")
        else:
            guide_ids.add(guide_id)
        if guide.get("step_id") not in step_ids:
            errors.append(f"{tag}: 없는 step_id 참조 ({guide.get('step_id')})")
        for field in ("source_phrase", "phrase", "what_to_show", "guide_text"):
            if not (guide.get(field) or "").strip():
                errors.append(f"{tag}: {field} 비어 있음")
        if guide.get("type") not in AMBIGUITY_TYPES:
            errors.append(f"{tag}: type 부적합 ({guide.get('type')})")
        importance = guide.get("importance")
        if not isinstance(importance, (int, float)) or not 0 <= importance <= 1:
            errors.append(f"{tag}: importance 범위 오류 ({importance})")
        guide_text = (guide.get("guide_text") or "").strip()
        if len(guide_text) < 10:
            warnings.append(f"{tag}: guide_text가 너무 짧음")
        vague_hits = [word for word in VAGUE if word in guide_text]
        if vague_hits:
            warnings.append(f"{tag}: guide_text에 막연 표현 {vague_hits}")
        timestamp = guide.get("best_visual_timestamp")
        if timestamp is None:
            warnings.append(f"{tag}: best_visual_timestamp null")
        elif not isinstance(timestamp, int):
            errors.append(f"{tag}: best_visual_timestamp가 정수/null 아님")
        elif timestamp < 0 or (duration is not None and timestamp >= duration):
            errors.append(f"{tag}: best_visual_timestamp 범위 밖 ({timestamp}/{duration})")

    for repair in data.get("_normalization_warnings", []):
        warnings.append(f"모델 출력 자동 보완: {repair}")
    return errors, warnings
