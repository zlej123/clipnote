"""Validate source-anchored investment claims without deciding truth."""
import re

CLAIM_TYPES = {
    "factual_claim", "inference", "prediction",
    "opinion", "rumor", "recommendation",
}
EPISTEMIC_MODES = {"asserted", "speculated", "quoted_third_party"}
FORBIDDEN_MODEL_FIELDS = {
    "verification_status", "review_status", "source_grade",
    "counterarguments", "counterevidence", "counter_evidence",
}


def _string_list(value, require_items=False):
    return (
        isinstance(value, list)
        and (bool(value) or not require_items)
        and all(isinstance(item, str) and item.strip() for item in value)
    )


def validate_investment_claims(data: dict):
    errors, warnings = [], []
    duration = data.get("_duration")
    claims = data.get("claims")
    if not isinstance(claims, list) or not claims:
        return ["claims가 비어 있거나 배열이 아님"], warnings
    max_claims = data.get("_max_claims", 20)
    if len(claims) > max_claims:
        errors.append(f"claims {len(claims)}개 (설정 상한 {max_claims})")

    claim_ids = set()
    for index, claim in enumerate(claims):
        tag = f"claim[{index}] id={claim.get('id')}"
        claim_id = claim.get("id")
        if not isinstance(claim_id, str) or not re.fullmatch(
                r"claim-[1-9][0-9]*", claim_id):
            errors.append(f"{tag}: id 형식 오류")
        elif claim_id in claim_ids:
            errors.append(f"{tag}: id 중복")
        else:
            claim_ids.add(claim_id)
        for forbidden in FORBIDDEN_MODEL_FIELDS.intersection(claim):
            errors.append(f"{tag}: 모델 출력 금지 필드 {forbidden}")
        for field in ("statement", "speaker"):
            value = claim.get(field)
            if not isinstance(value, str) or not value.strip():
                errors.append(f"{tag}: {field} 비어 있음")
        if claim.get("claim_type") not in CLAIM_TYPES:
            errors.append(f"{tag}: claim_type 부적합 ({claim.get('claim_type')})")
        if claim.get("epistemic_mode") not in EPISTEMIC_MODES:
            errors.append(
                f"{tag}: epistemic_mode 부적합 ({claim.get('epistemic_mode')})")
        entities = claim.get("entities")
        if not _string_list(entities):
            errors.append(f"{tag}: entities가 문자열 배열이 아님")
        for field in ("verification_questions", "falsification_questions"):
            if not _string_list(claim.get(field), require_items=True):
                errors.append(f"{tag}: {field}가 비어 있거나 문자열 배열이 아님")
        for field in ("decision_impact", "verification_feasibility"):
            value = claim.get(field)
            if type(value) is not int or not 1 <= value <= 3:
                errors.append(f"{tag}: {field} 범위 오류 ({value})")
        time_horizon = claim.get("time_horizon")
        if time_horizon is not None and (
                not isinstance(time_horizon, str) or not time_horizon.strip()):
            errors.append(f"{tag}: time_horizon은 문자열 또는 null이어야 함")

        anchor = claim.get("source_anchor")
        if not isinstance(anchor, dict):
            errors.append(f"{tag}: source_anchor가 객체가 아님")
            continue
        quote = anchor.get("quote")
        if not isinstance(quote, str) or not quote.strip():
            errors.append(f"{tag}: source_anchor.quote 비어 있음")
        elif len(quote.strip()) < 4:
            warnings.append(f"{tag}: source_anchor.quote가 너무 짧음")
        start = anchor.get("timestamp_start")
        end = anchor.get("timestamp_end")
        if type(start) is not int or type(end) is not int:
            errors.append(f"{tag}: source_anchor 타임스탬프가 정수 아님")
        elif start < 0 or start > end:
            errors.append(f"{tag}: source_anchor 구간 오류 ({start}-{end})")
        elif duration is not None and end > duration:
            errors.append(f"{tag}: source_anchor가 영상 길이 초과 ({end}>{duration})")
    return errors, warnings
