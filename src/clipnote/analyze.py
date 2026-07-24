#!/usr/bin/env python3
"""Analyze a YouTube video with a selected Clipnote profile.

Usage:
    py -3.11 analyze.py URL [--profile generic] [--language ko] [--max-guides 5]

The caller supplies the user-profile language. Results are cached per
video/profile/language under work/analyses/.
"""
import argparse
import json
import os
import time
from urllib.error import HTTPError
import subprocess
import sys
import urllib.request
from pathlib import Path
from .common import analysis_file, data_root, hms, video_id as parse_video_id
from .contract import validate
from .normalizers.common import mmss_to_sec  # Backward-compatible public import.
from .normalizers.investment_claims import normalize_investment_claims
from .normalizers.visual_guides import normalize_visual_guides
from .profiles import load_profile
sys.stdout.reconfigure(encoding="utf-8")  # Windows cp949 콘솔 대응

PKG = Path(__file__).parent
RULES = (PKG / "skill-core" / "engine" / "rules.md").read_text(encoding="utf-8")
NORMALIZERS = {
    "visual_guides": normalize_visual_guides,
    "investment_claims": normalize_investment_claims,
}


class RateLimitError(RuntimeError):
    pass


def load_schema(profile: str) -> dict:
    path = PKG / "skill-core" / "profiles" / profile / "schema.json"
    if not path.exists():
        sys.exit(f"알 수 없는 프로파일 스키마: {profile} ({path} 없음)")
    schema = json.loads(path.read_text(encoding="utf-8"))
    for metadata_key in ("$schema", "$comment", "title"):
        schema.pop(metadata_key, None)
    return schema


def load_prompt(profile: str, duration_hms: str, language: str,
                max_guides: int, max_claims: int = 20) -> str:
    p = PKG / "skill-core" / "profiles" / profile / "prompt.md"
    if not p.exists():
        sys.exit(f"알 수 없는 프로파일: {profile} ({p} 없음)")
    return (p.read_text(encoding="utf-8")
            .replace("{{RULES}}", RULES)
            .replace("{DURATION}", duration_hms)
            .replace("{OUTPUT_LANGUAGE}", language)
            .replace("{MAX_VISUAL_GUIDES}", str(max_guides))
            .replace("{MAX_CLAIMS}", str(max_claims)))

API = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"


def video_id(url: str) -> str:
    """CLI helper: parse YouTube id or exit with a message."""
    try:
        return parse_video_id(url)
    except ValueError as error:
        sys.exit(str(error))


def normalize_video_metadata(payload: dict, url: str) -> dict:
    """Keep only stable source fields from yt-dlp's much larger response."""
    duration = payload.get("duration")
    if not isinstance(duration, (int, float)) or duration <= 0:
        raise ValueError("영상 길이가 없거나 유효하지 않음")
    upload_date = payload.get("upload_date")
    published_at = None
    if isinstance(upload_date, str) and len(upload_date) == 8:
        published_at = (
            f"{upload_date[:4]}-{upload_date[4:6]}-{upload_date[6:8]}")
    return {
        "type": "youtube",
        "url": url,
        "video_id": payload.get("id"),
        "title": payload.get("title"),
        "author": payload.get("uploader") or payload.get("channel"),
        "published_at": published_at,
        "duration_seconds": int(duration),
    }


def fetch_video_metadata(url: str) -> dict:
    result = subprocess.run(
        [
            sys.executable, "-m", "yt_dlp",
            "--skip-download", "--no-playlist", "--dump-single-json", url,
        ],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        sys.exit(f"영상 메타데이터 조회 실패:\n{result.stderr[-1000:]}")
    try:
        payload = json.loads(result.stdout)
        return normalize_video_metadata(payload, url)
    except (json.JSONDecodeError, ValueError) as error:
        sys.exit(f"영상 메타데이터 해석 실패: {error}")


def fetch_duration(url: str) -> int:
    """Compatibility wrapper retained for existing callers."""
    return fetch_video_metadata(url)["duration_seconds"]


def generate_json(parts: list, model: str, key: str,
                  schema: dict, retries: int = 2) -> dict:
    """Call Gemini generateContent with arbitrary parts, returning parsed JSON."""
    body = {
        "contents": [{"parts": parts}],
        "generationConfig": {
            "response_mime_type": "application/json",
            "response_json_schema": schema,
            "temperature": 0.2,
        },
    }
    request = urllib.request.Request(
        API.format(model=model),
        data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json", "x-goog-api-key": key},
    )
    for attempt in range(retries + 1):
        try:
            with urllib.request.urlopen(request, timeout=600) as response:
                payload = json.loads(response.read().decode())
            break
        except HTTPError as error:
            detail = error.read().decode("utf-8", errors="replace")
            if error.code != 429:
                raise RuntimeError(
                    f"Gemini HTTP {error.code}: {detail[-2000:]}") from error
            if attempt >= retries:
                raise RateLimitError(detail[-2000:]) from error
            retry_after = error.headers.get("Retry-After")
            delay = (int(retry_after) if retry_after and retry_after.isdigit()
                     else 5 * (2 ** attempt))
            print(f"[429] {delay}초 후 재시도 ({attempt + 1}/{retries})")
            time.sleep(delay)
    try:
        text = payload["candidates"][0]["content"]["parts"][0]["text"]
    except (KeyError, IndexError):
        raise RuntimeError(
            "응답 파싱 실패:\n" +
            json.dumps(payload, ensure_ascii=False, indent=2))
    return json.loads(text)


def call_gemini(url: str, prompt: str, model: str, key: str,
                schema: dict, retries: int = 2) -> dict:
    return generate_json(
        [{"file_data": {"file_uri": url}}, {"text": prompt}],
        model, key, schema, retries)


def normalize(data: dict, profile: str = None) -> dict:
    profile = profile or data.get("_profile") or "generic"
    normalizer_name = load_profile(profile)["normalizer"]
    normalizer = NORMALIZERS.get(normalizer_name)
    if normalizer is None:
        raise ValueError(f"알 수 없는 normalizer: {normalizer_name}")
    return normalizer(data)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("url")
    ap.add_argument("--model", default="gemini-flash-lite-latest")
    ap.add_argument("--profile", default="generic", help="분석 프로파일 (generic|recipe|...)")
    ap.add_argument(
        "--language",
        default=os.environ.get("CLIPNOTE_LANGUAGE", "ko"),
        help="사용자 프로파일 출력 언어(BCP-47, 예: ko, en, ja)")
    ap.add_argument("--max-guides", type=int, default=5, help="최대 시각 가이드 수")
    ap.add_argument("--max-claims", type=int, default=20, help="최대 투자 주장 수")
    ap.add_argument(
        "--max-duration",
        type=int,
        help="허용 영상 길이(초). 프로필 기본값보다 우선")
    ap.add_argument("--force", action="store_true", help="캐시 무시하고 재분석")
    args = ap.parse_args()
    if args.max_guides < 0:
        ap.error("--max-guides는 0 이상이어야 합니다.")
    if args.max_claims < 1:
        ap.error("--max-claims는 1 이상이어야 합니다.")
    if args.max_duration is not None and args.max_duration < 1:
        ap.error("--max-duration은 1초 이상이어야 합니다.")

    vid = video_id(args.url)
    profile_config = load_profile(args.profile)
    out_file = analysis_file(data_root(), vid, args.profile, args.language)
    out_file.parent.mkdir(parents=True, exist_ok=True)

    source_metadata = fetch_video_metadata(args.url)
    duration = source_metadata["duration_seconds"]
    print(f"영상 길이: {hms(duration)} ({duration}s)")
    max_duration = args.max_duration or profile_config.get(
        "default_max_duration_seconds")
    if max_duration and duration > max_duration:
        sys.exit(
            f"영상이 프로파일 길이 상한을 초과했습니다 "
            f"({duration}s>{max_duration}s). --max-duration으로 명시적으로 조정하세요.")

    if out_file.exists() and not args.force:
        print(f"[cache] {out_file} 사용 (재분석은 --force)")
        data = json.loads(out_file.read_text(encoding="utf-8"))
        if not data.get("_source"):
            data["_source"] = source_metadata
            out_file.write_text(
                json.dumps(data, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        if data.get("_max_visual_guides") != args.max_guides:
            if profile_config["uses_visual_guides"]:
                sys.exit(
                    f"캐시의 max-guides={data.get('_max_visual_guides')}가 "
                    f"요청값 {args.max_guides}와 다릅니다. --force로 재분석하세요.")
        if not profile_config["uses_visual_guides"] and \
                data.get("_max_claims") != args.max_claims:
            sys.exit(
                f"캐시의 max-claims={data.get('_max_claims')}가 "
                f"요청값 {args.max_claims}와 다릅니다. --force로 재분석하세요.")
        if data.get("_model") and data["_model"] != args.model:
            sys.exit(
                f"캐시 모델 {data['_model']}이 요청 모델 {args.model}과 다릅니다. "
                "--force로 재분석하세요.")
        errors, _ = validate(data)
        if errors:
            sys.exit("캐시 계약 위반:\n- " + "\n- ".join(errors) +
                     "\n--force로 재분석하세요.")
    else:
        key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
        if not key:
            sys.exit("GEMINI_API_KEY 환경변수가 없습니다.")
        prompt = load_prompt(
            args.profile, hms(duration), args.language,
            args.max_guides, args.max_claims)
        print(f"[1/2] Gemini({args.model}) 영상 분석 중... (수십 초~수 분)")
        try:
            data = normalize(call_gemini(
                args.url, prompt, args.model, key, load_schema(args.profile)),
                args.profile)
        except RateLimitError as error:
            print("Gemini 무료 티어/속도 한도에 도달했습니다.")
            print(str(error))
            sys.exit(75)
        data["_duration"] = duration
        data["_source"] = source_metadata
        data["_profile"] = args.profile
        data["_output_language"] = args.language
        if profile_config["uses_visual_guides"]:
            data["_max_visual_guides"] = args.max_guides
        else:
            data["_max_claims"] = args.max_claims
        data["_model"] = args.model
        errors, warnings = validate(data)
        if errors:
            sys.exit("분석 결과 계약 위반:\n- " + "\n- ".join(errors))
        for warning in warnings:
            print(f"[경고] {warning}")
        out_file.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"[2/2] 저장: {out_file}\n")

    print(f"== {data.get('title', '?')} ==")
    if profile_config["uses_visual_guides"]:
        print(
            f"준비물 {len(data.get('materials') or data.get('ingredients') or [])}종 "
            f"/ 단계 {len(data.get('steps', []))}개\n")
    else:
        print(f"투자 주장 {len(data.get('claims', []))}개\n")

    guides = data.get("visual_guides", [])
    guides_by_step = {}
    for guide in guides:
        guides_by_step.setdefault(guide.get("step_id"), []).append(guide)

    bad = 0
    for s in data.get("steps", []):
        step_guides = guides_by_step.get(s.get("id"), [])
        mark = f" [시각 가이드 {len(step_guides)}]" if step_guides else ""
        print(f"  {s['id']}. [{hms(s['t_start'])}-{hms(s['t_end'])}] {s['summary']}{mark}")
        for guide in step_guides:
            ts = guide.get("best_visual_timestamp")
            print(f"       {guide['id']}: '{guide['phrase']}' ({guide['type']}, 중요도 {guide['importance']})")
            print(f"       가이드: {guide['guide_text']}")
            if ts is None:
                print("       장면: (적합한 장면 없음 -> 텍스트 가이드만)")
            elif ts >= duration:
                bad += 1
                print(f"       장면: {hms(ts)} [범위밖! 영상 길이 {hms(duration)}]")
            else:
                print(f"       검증 링크: https://youtu.be/{vid}?t={ts}  ({hms(ts)})")
        print()

    if profile_config["uses_visual_guides"]:
        print(f"시각 가이드 {len(guides)}개 (범위 밖 {bad}개).")
        print("통과 기준: 범위 밖 0개 + 상위 3개 후보 중 적합한 장면 포함률 90% 이상.")
    else:
        for claim in data.get("claims", []):
            anchor = claim.get("source_anchor", {})
            start = anchor.get("timestamp_start")
            print(
                f"  {claim.get('id')}: [{claim.get('claim_type')}] "
                f"{claim.get('statement')} → {hms(start)}")
        print("모든 주장은 미검증 상태이며 Project 2035 검토 전 투자 판단에 사용하지 않습니다.")


if __name__ == "__main__":
    main()
