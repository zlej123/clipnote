"""Load profile capabilities without coupling the shared pipeline to a domain."""
import json
from pathlib import Path

PKG = Path(__file__).parent
PROFILES = PKG / "skill-core" / "profiles"

DEFAULT_CAPABILITIES = {
    "contract": "visual_guides",
    "normalizer": "visual_guides",
    "uses_visual_guides": True,
    "requires_duration": True,
}


def load_profile(profile: str) -> dict:
    profile_dir = PROFILES / profile
    if not profile_dir.exists():
        raise ValueError(f"알 수 없는 프로파일: {profile}")
    config_path = profile_dir / "profile.json"
    if not config_path.exists():
        return {"id": profile, **DEFAULT_CAPABILITIES}
    configured = json.loads(config_path.read_text(encoding="utf-8"))
    return {"id": profile, **DEFAULT_CAPABILITIES, **configured}

