#!/usr/bin/env python3
"""Analyze a YouTube how-to video into normalized steps and visual guides.

Usage:
    py -3.11 analyze.py URL [--profile generic] [--language ko] [--max-guides 5]

The caller supplies the user-profile language. Results are cached per
video/profile/language under work/analyses/.
"""
import argparse
import json
import os
import re
import time
from urllib.error import HTTPError
import subprocess
import sys
import urllib.request
from pathlib import Path
from .common import analysis_file, data_root
from .contract import validate
sys.stdout.reconfigure(encoding="utf-8")  # Windows cp949 콘솔 대응

PKG = Path(__file__).parent
RULES = (PKG / "skill-core" / "engine" / "rules.md").read_text(encoding="utf-8")
TYPE_ALIASES = {
    "shape": "state",
    "pattern": "texture",
    "direction": "position",
    "setting": "position",
    "location": "position",
    "length": "size",
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


def load_prompt(profile: str, duration_hms: str, language: str, max_guides: int) -> str:
    p = PKG / "skill-core" / "profiles" / profile / "prompt.md"
    if not p.exists():
        sys.exit(f"알 수 없는 프로파일: {profile} ({p} 없음)")
    return (p.read_text(encoding="utf-8")
            .replace("{{RULES}}", RULES)
            .replace("{DURATION}", duration_hms)
            .replace("{OUTPUT_LANGUAGE}", language)
            .replace("{MAX_VISUAL_GUIDES}", str(max_guides)))

API = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"


def video_id(url: str) -> str:
    m = re.search(r"(?:v=|youtu\.be/|shorts/)([\w-]{11})", url)
    if not m:
        sys.exit(f"유튜브 URL에서 video id를 못 찾음: {url}")
    return m.group(1)


def fetch_duration(url: str) -> int:
    r = subprocess.run([sys.executable, "-m", "yt_dlp", "--skip-download",
                        "--print", "duration", url],
                       capture_output=True, text=True)
    if r.returncode != 0 or not r.stdout.strip().isdigit():
        sys.exit(f"영상 길이 조회 실패:\n{r.stderr[-1000:]}")
    return int(r.stdout.strip())


def mmss_to_sec(v):
    """'MM:SS' 또는 'H:MM:SS' -> 초. 이미 숫자면 그대로."""
    if v is None or isinstance(v, int):
        return v
    parts = [int(p) for p in str(v).split(":")]
    sec = 0
    for p in parts:
        sec = sec * 60 + p
    return sec


def hms(sec: int) -> str:
    return f"{sec // 60}:{sec % 60:02d}"


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


def normalize(data: dict) -> dict:
    normalization_warnings = []
    for step in data.get("steps", []):
        step["t_start"] = mmss_to_sec(step.get("t_start"))
        step["t_end"] = mmss_to_sec(step.get("t_end"))
        step.pop("ambiguity", None)
    for index, guide in enumerate(data.get("visual_guides", [])):
        guide["best_visual_timestamp"] = mmss_to_sec(
            guide.get("best_visual_timestamp"))
        if not guide.get("source_phrase") and guide.get("phrase"):
            guide["source_phrase"] = guide["phrase"]
            normalization_warnings.append(
                f"{guide.get('id', index)}: source_phrase를 phrase로 보완")
        if not guide.get("importance"):
            guide["importance"] = max(0.5, 1.0 - index * 0.1)
            normalization_warnings.append(
                f"{guide.get('id', index)}: importance 자동 보완")
        guide_type = guide.get("type")
        if guide_type in TYPE_ALIASES:
            guide["type"] = TYPE_ALIASES[guide_type]
            normalization_warnings.append(
                f"{guide.get('id', index)}: type {guide_type}→{guide['type']}")
    if normalization_warnings:
        data["_normalization_warnings"] = normalization_warnings
    return data


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
    ap.add_argument("--force", action="store_true", help="캐시 무시하고 재분석")
    args = ap.parse_args()
    if args.max_guides < 0:
        ap.error("--max-guides는 0 이상이어야 합니다.")

    vid = video_id(args.url)
    out_file = analysis_file(data_root(), vid, args.profile, args.language)
    out_file.parent.mkdir(parents=True, exist_ok=True)

    duration = fetch_duration(args.url)
    print(f"영상 길이: {hms(duration)} ({duration}s)")

    if out_file.exists() and not args.force:
        print(f"[cache] {out_file} 사용 (재분석은 --force)")
        data = json.loads(out_file.read_text(encoding="utf-8"))
        if data.get("_max_visual_guides") != args.max_guides:
            sys.exit(
                f"캐시의 max-guides={data.get('_max_visual_guides')}가 "
                f"요청값 {args.max_guides}와 다릅니다. --force로 재분석하세요.")
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
            args.profile, hms(duration), args.language, args.max_guides)
        print(f"[1/2] Gemini({args.model}) 영상 분석 중... (수십 초~수 분)")
        try:
            data = normalize(call_gemini(
                args.url, prompt, args.model, key, load_schema(args.profile)))
        except RateLimitError as error:
            print("Gemini 무료 티어/속도 한도에 도달했습니다.")
            print(str(error))
            sys.exit(75)
        data["_duration"] = duration
        data["_profile"] = args.profile
        data["_output_language"] = args.language
        data["_max_visual_guides"] = args.max_guides
        data["_model"] = args.model
        errors, warnings = validate(data)
        if errors:
            sys.exit("분석 결과 계약 위반:\n- " + "\n- ".join(errors))
        for warning in warnings:
            print(f"[경고] {warning}")
        out_file.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"[2/2] 저장: {out_file}\n")

    print(f"== {data.get('title', '?')} ==")
    print(f"준비물 {len(data.get('materials') or data.get('ingredients') or [])}종 / 단계 {len(data.get('steps', []))}개\n")

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

    print(f"시각 가이드 {len(guides)}개 (범위 밖 {bad}개).")
    print("통과 기준: 범위 밖 0개 + 상위 3개 후보 중 적합한 장면 포함률 90% 이상.")


if __name__ == "__main__":
    main()
