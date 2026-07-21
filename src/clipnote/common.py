"""Shared artifact paths, identifiers, and small utilities."""
import os
import re
from pathlib import Path

TOKEN = re.compile(r"^[A-Za-z0-9._-]+$")
VIDEO_ID = re.compile(r"(?:v=|youtu\.be/|shorts/)([\w-]{11})")


def data_root() -> Path:
    """Artifact root (work/, output/, exports/). Env CLIPNOTE_DATA or cwd."""
    return Path(os.environ.get("CLIPNOTE_DATA", Path.cwd()))


def validate_token(value: str, label: str) -> str:
    if not value or not TOKEN.fullmatch(value):
        raise ValueError(f"잘못된 {label}: {value!r}")
    return value


def video_id(url: str) -> str:
    match = VIDEO_ID.search(url)
    if not match:
        raise ValueError(f"유튜브 URL에서 video id를 찾지 못함: {url}")
    return match.group(1)


def hms(sec: int) -> str:
    """Seconds -> M:SS (or H:MM:SS when >= 1 hour)."""
    if sec is None:
        return ""
    sec = int(sec)
    if sec < 0:
        sec = 0
    hours, rem = divmod(sec, 3600)
    minutes, seconds = divmod(rem, 60)
    if hours:
        return f"{hours}:{minutes:02d}:{seconds:02d}"
    return f"{minutes}:{seconds:02d}"


def variant_key(profile: str, language: str) -> str:
    return f"{validate_token(profile, 'profile')}.{validate_token(language, 'language')}"


def analysis_file(root: Path, video_id: str, profile: str, language: str) -> Path:
    return root / "work" / "analyses" / video_id / f"{variant_key(profile, language)}.json"


def frames_dir(root: Path, video_id: str, profile: str, language: str) -> Path:
    return root / "work" / "frames" / video_id / variant_key(profile, language)


def output_dir(root: Path, video_id: str, profile: str, language: str) -> Path:
    return root / "output" / video_id / variant_key(profile, language)
