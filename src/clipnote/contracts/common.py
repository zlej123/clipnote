"""Contract checks shared by every Clipnote analysis profile."""


def validate_common(data: dict):
    errors, warnings = [], []
    for field in ("_profile", "_output_language"):
        if not data.get(field):
            errors.append(f"{field} 메타데이터 없음")
    title = data.get("title")
    if not isinstance(title, str) or not title.strip():
        errors.append("title 비어 있음")
    return errors, warnings
