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
import time
from urllib.error import HTTPError
import subprocess
import sys
import urllib.request
from pathlib import Path
from .common import UnknownProfileError, analysis_file, data_root, hms, video_id as parse_video_id
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
        raise UnknownProfileError(f"알 수 없는 프로파일 스키마: {profile} ({path} 없음)")
    schema = json.loads(path.read_text(encoding="utf-8"))
    for metadata_key in ("$schema", "$comment", "title"):
        schema.pop(metadata_key, None)
    return schema


def asset_digest(profile: str) -> str:
    """rules.md + prompt.md + schema.json의 sha256 앞 12자리 (외부 리뷰 #6).

    분석 JSON에 _asset_digest로 스탬프된다 — "이 결과가 어떤 프롬프트·스키마로
    만들어졌는가"를 추적할 수 있어, 품질 지표를 자산 버전별로 분리할 근거가 된다.
    """
    import hashlib
    digest = hashlib.sha256()
    digest.update((PKG / "skill-core" / "engine" / "rules.md").read_bytes())
    for name in ("prompt.md", "schema.json"):
        path = PKG / "skill-core" / "profiles" / profile / name
        if path.exists():
            digest.update(path.read_bytes())
    return digest.hexdigest()[:12]


def load_prompt(profile: str, duration_hms: str, language: str, max_guides: int) -> str:
    p = PKG / "skill-core" / "profiles" / profile / "prompt.md"
    if not p.exists():
        raise UnknownProfileError(f"알 수 없는 프로파일: {profile} ({p} 없음)")
    return (p.read_text(encoding="utf-8")
            .replace("{{RULES}}", RULES)
            .replace("{DURATION}", duration_hms)
            .replace("{OUTPUT_LANGUAGE}", language)
            .replace("{MAX_VISUAL_GUIDES}", str(max_guides)))

API = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"


def video_id(url: str) -> str:
    """CLI helper: parse YouTube id or exit with a message."""
    try:
        return parse_video_id(url)
    except ValueError as error:
        sys.exit(str(error))


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


# 같은 프롬프트를 두 번 돌리면 **서로 다른 가이드**가 나온다 (모델 서빙 비결정성 실측:
# 기준선 재실행만으로 가이드 수가 ±0.95개 흔들린다). 프롬프트를 고쳐 더 뽑으려던 시도는
# 두 번 다 노이즈에 묻혔지만, 여러 번 돌려 **합집합**을 취하면 2.8개 → 5.2개로 늘었다.
# 노이즈와 싸우는 대신 이용하는 쪽이다.
MERGE_SECONDS = 2          # 이보다 가까운 같은 단계의 가이드는 같은 순간으로 본다


def _step_for(timestamp: int, steps: list) -> int | None:
    """타임스탬프가 속한 단계 id. 실행마다 단계 구조가 달라지므로 시간으로 다시 잇는다."""
    if not steps:
        return None
    for step in steps:
        start, end = step.get("t_start"), step.get("t_end")
        if start is not None and end is not None and start <= timestamp <= end:
            return step["id"]
    return min(steps, key=lambda s: min(
        abs(timestamp - (s.get("t_start") or 0)),
        abs(timestamp - (s.get("t_end") or 0))))["id"]


# 같은 내용을 다르게 쓴 가이드를 걸러내는 문턱. 실측: 합집합에서 "windowpane test showing
# translucent dough"와 "translucent windowpane test"가 둘 다 남아 거의 같은 사진이 두 장
# 들어갔다. 짧은 쪽이 긴 쪽에 얼마나 담기는지(포함률)로 재야 이런 재진술이 잡힌다.
MERGE_CONTAINMENT = 0.6
_STOPWORDS = {"the", "a", "an", "and", "or", "of", "on", "in", "to", "with", "for",
              "은", "는", "이", "가", "을", "를", "의", "에", "와", "과", "로"}


def _tokens(guide: dict) -> set:
    text = f"{guide.get('phrase', '')} {guide.get('what_to_show', '')}".lower()
    words = "".join(ch if ch.isalnum() else " " for ch in text).split()
    return {w for w in words if w not in _STOPWORDS and len(w) > 1}


def _same_guide(a: dict, b: dict) -> bool:
    if a.get("step_id") != b.get("step_id"):
        return False
    if abs((a.get("best_visual_timestamp") or 0)
           - (b.get("best_visual_timestamp") or 0)) <= MERGE_SECONDS:
        return True
    first, second = _tokens(a), _tokens(b)
    if not first or not second:
        return False
    return len(first & second) / min(len(first), len(second)) >= MERGE_CONTAINMENT


def trim_guides(guides: list, max_guides: int) -> list:
    """상한이 있으면 importance 높은 순으로만 남긴다. 0이면 그대로 (기본)."""
    if not max_guides or len(guides) <= max_guides:
        return guides
    return sorted(guides, key=lambda g: (-(g.get("importance") or 0),
                                         g.get("best_visual_timestamp") or 0))[:max_guides]


def merge_runs(runs: list, max_guides: int) -> dict:
    """여러 분석 결과를 첫 실행의 단계 구조 위로 합친다.

    가이드는 시간으로 단계에 다시 매달고, 같은 순간이 중복되면 버리며,
    마지막에 importance 순으로 상한까지만 남긴다 (상한의 의미를 지킨다).
    """
    merged = runs[0]
    steps = merged.get("steps", [])
    guides = []
    for run in runs:
        for guide in run.get("visual_guides", []):
            timestamp = guide.get("best_visual_timestamp")
            if timestamp is None:
                continue
            guide = dict(guide)
            guide["step_id"] = _step_for(timestamp, steps)
            if any(_same_guide(guide, kept) for kept in guides):
                continue
            guides.append(guide)
    guides.sort(key=lambda g: (-(g.get("importance") or 0),
                               g.get("best_visual_timestamp") or 0))
    guides = trim_guides(guides, max_guides)
    for index, guide in enumerate(guides, start=1):
        guide["id"] = f"vg-{index}"
    merged["visual_guides"] = guides
    merged["_analysis_passes"] = len(runs)
    return merged


def call_gemini(url: str, prompt: str, model: str, key: str,
                schema: dict, retries: int = 2) -> dict:
    return generate_json(
        [{"file_data": {"file_uri": url}}, {"text": prompt}],
        model, key, schema, retries)


def normalize(data: dict) -> dict:
    from .contract import CONTRACT_VERSION
    data.setdefault("_contract_version", CONTRACT_VERSION)
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
        if guide.get("importance") is None:
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
        default=os.environ.get("STEPKEEPER_LANGUAGE", "ko"),
        help="사용자 프로파일 출력 언어(BCP-47, 예: ko, en, ja)")
    ap.add_argument("--max-guides", type=int, default=0,
                    help="시각 가이드 상한. 0이면 무제한(기본) — 애매한 표현마다 모두 만든다. "
                         "문서를 짧게 유지하고 싶을 때만 값을 준다")
    ap.add_argument("--force", action="store_true", help="캐시 무시하고 재분석")
    ap.add_argument("--passes", type=int, default=1,
                    help="분석 반복 횟수. 2 이상이면 실행마다 다르게 나오는 "
                         "가이드를 합쳐 더 촘촘한 문서를 만든다 (호출 비용 비례)")
    args = ap.parse_args()
    if args.max_guides < 0:
        ap.error("--max-guides는 0 이상이어야 합니다.")
    if args.passes < 1:
        ap.error("--passes는 1 이상이어야 합니다.")

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
        try:
            prompt = load_prompt(
                args.profile, hms(duration), args.language, args.max_guides)
            schema = load_schema(args.profile)
        except UnknownProfileError as error:
            sys.exit(str(error))
        print(f"[1/2] Gemini({args.model}) 영상 분석 중... (수십 초~수 분)"
              + (f" x{args.passes}회" if args.passes > 1 else ""))
        try:
            runs = []
            for attempt in range(args.passes):
                if attempt:
                    print(f"  {attempt + 1}회차 분석 (합집합으로 가이드를 늘립니다)")
                runs.append(normalize(call_gemini(
                    args.url, prompt, args.model, key, schema)))
            data = (merge_runs(runs, args.max_guides) if len(runs) > 1
                    else dict(runs[0], visual_guides=trim_guides(
                        runs[0].get("visual_guides", []), args.max_guides)))
        except RateLimitError as error:
            print("Gemini 무료 티어/속도 한도에 도달했습니다.")
            print(str(error))
            sys.exit(75)
        data["_duration"] = duration
        data["_asset_digest"] = asset_digest(args.profile)
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
