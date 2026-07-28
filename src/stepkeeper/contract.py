#!/usr/bin/env python3
"""Validate normalized analysis against the core visual-guide contract."""

# 분석 JSON의 계약 버전 (외부 리뷰 #6). 스키마·의미가 호환 불가하게 바뀔 때만 올린다.
# normalize()가 _contract_version으로 스탬프하고, 소비자는 자기가 아는 버전과 대조해
# "모르는 미래 버전"을 조용히 잘못 해석하는 대신 감지할 수 있다.
CONTRACT_VERSION = "1"

AMBIGUITY_TYPES = {"size", "thickness", "color", "state", "amount",
                   "position", "angle", "action", "texture"}
# Multilingual vague fillers that defeat the purpose of guide_text.
# 안전 결정이 필요한 고위험 도메인 신호 (외부 리뷰 #10). SKILL.md는 이런 영상을 제외하지만
# 소비자 클라이언트의 자동 감지에는 상응하는 차단이 없었다. 계약 검증은 결정적이므로 여기서
# 감지해 경고 채널로 올린다 — 클라이언트는 이 경고를 문서 상단 고지로 노출해야 한다.
HIGH_RISK = [
    # ko
    "전기 배선", "누전", "차단기", "감전", "가스관", "가스 밸브", "가스레인지 설치",
    "의료", "치료", "복용", "부상", "응급처치", "브레이크 수리", "전동 공구 개조",
    # en
    "electrical wiring", "circuit breaker", "mains power", "gas line", "gas valve",
    "medical", "medication", "first aid", "brake repair", "chainsaw",
    # ja
    "電気配線", "ガス管", "医療", "応急処置",
]

VAGUE = [
    # ko
    "적당히", "적당량", "알맞게", "대충", "적절히", "먹기 좋게",
    # en
    "appropriately", "suitably", "roughly", "about right", "as needed",
    "to taste", "until done", "just enough",
    # ja
    "適度", "適当", "ほどよく", "いい感じ",
]


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

    # 고위험 도메인 감지 — 오탐을 감수하고 넓게 잡는다 (경고는 문서를 막지 않는다)
    blob = " ".join([str(data.get("title", "")), str(data.get("category", "")),
                     str(data.get("summary", ""))]).lower()
    risk_hits = [kw for kw in HIGH_RISK if kw.lower() in blob]
    if risk_hits:
        warnings.append(
            f"고위험 도메인 감지({', '.join(risk_hits[:3])}) — 이 문서는 참고용이며 "
            "전문가 확인 없이 따라 하지 마세요. 클라이언트는 이 경고를 사용자에게 노출해야 합니다.")

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
