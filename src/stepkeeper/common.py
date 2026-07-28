"""Shared artifact paths, identifiers, and small utilities."""
import os
import re
from pathlib import Path

TOKEN = re.compile(r"^[A-Za-z0-9._-]+$")
VIDEO_ID = re.compile(r"(?:v=|youtu\.be/|shorts/)([\w-]{11})")


class UnknownProfileError(ValueError):
    """존재하지 않는 프로파일. 라이브러리 계층은 sys.exit 대신 이걸 던진다 —
    CLI는 main()에서 잡아 종료하고, 서버는 422로 변환한다 (SystemExit는 FastAPI를 뚫고 나간다)."""


def data_root() -> Path:
    """Artifact root (work/, output/, exports/). Env STEPKEEPER_DATA or cwd."""
    return Path(os.environ.get("STEPKEEPER_DATA", Path.cwd()))


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
