"""Build the stable JSON boundary consumed by Project 2035."""
import json
from pathlib import Path


def verification_priority(claim: dict) -> dict:
    """Derive review order without asking the model to assign final priority."""
    impact = claim["decision_impact"]
    feasibility = claim["verification_feasibility"]
    score = impact * feasibility
    if score >= 6:
        band = "high"
    elif score >= 3:
        band = "medium"
    else:
        band = "low"
    return {
        "claim_id": claim["id"],
        "verification_status": "unverified",
        "priority_score": score,
        "priority_band": band,
    }


def build_claim_packet(video_id: str, data: dict) -> dict:
    source = data.get("_source") or {}
    return {
        "contract_version": 1,
        "source": {
            "type": "youtube",
            "url": source.get("url") or f"https://youtu.be/{video_id}",
            "video_id": video_id,
            "title": source.get("title") or data.get("title"),
            "author": source.get("author"),
            "published_at": source.get("published_at"),
        },
        "extraction": {
            "profile": data.get("_profile"),
            "model": data.get("_model"),
            "output_language": data.get("_output_language"),
        },
        "title": data.get("title"),
        "summary": data.get("summary"),
        "claims": data.get("claims", []),
        "review_queue": [
            verification_priority(claim)
            for claim in data.get("claims", [])
        ],
    }


def write_claim_packet(path: Path, video_id: str, data: dict) -> Path:
    path.write_text(
        json.dumps(build_claim_packet(video_id, data), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return path
