#!/usr/bin/env python3
"""AI frame selection: Gemini vision picks one candidate per visual guide.

Usage:
    python -m clipnote.autopick VIDEO_ID --profile generic --language ko

Reads the analysis and the before/center/after candidates from disk, asks
Gemini which frame actually shows each guide's `what_to_show` (or none),
writes picks.json (+ picks-meta.json with reasons), and regenerates
picker.html with the AI picks pre-selected so a human can review and export
a feedback record.
"""
import argparse
import base64
import json
import os
import sys

from .analyze import RateLimitError, generate_json
from .capture import SLOTS, build_picker
from .common import analysis_file, data_root, frames_dir

sys.stdout.reconfigure(encoding="utf-8")

PICK_SCHEMA = {
    "type": "object",
    "required": ["picks"],
    "properties": {
        "picks": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["guide_id", "slot", "reason"],
                "properties": {
                    "guide_id": {"type": "string"},
                    "slot": {"enum": ["before", "center", "after", "none"]},
                    "reason": {"type": "string"},
                },
            },
        }
    },
}

PROMPT = """당신은 시각 가이드용 대표 프레임을 고르는 검수자입니다.
각 가이드마다 후보 3장(before/center/after)이 순서대로 첨부됩니다.
가이드의 '보여야 할 것'이 실제로 가장 명확하게 보이는 후보 하나를 고르세요.
세 장 모두에서 그것이 보이지 않으면 반드시 "none"을 고르세요 — 억지로 고르지 않습니다.
각 선택에 한 문장 근거(reason)를 답하세요. JSON만 출력합니다."""


def auto_pick(vid: str, profile: str, language: str, model: str, key: str) -> dict:
    """Run AI selection; returns picks dict and writes picks.json / picks-meta.json."""
    source = analysis_file(data_root(), vid, profile, language)
    if not source.exists():
        raise FileNotFoundError(f"분석 결과 없음: {source}")
    data = json.loads(source.read_text(encoding="utf-8"))
    frames = frames_dir(data_root(), vid, profile, language)

    guides = [guide for guide in data.get("visual_guides", [])
              if guide.get("best_visual_timestamp") is not None]
    parts = [{"text": PROMPT}]
    asked = []
    for guide in guides:
        candidates = {slot: frames / f"{guide['id']}_{slot}.jpg" for slot in SLOTS}
        if not all(path.exists() for path in candidates.values()):
            continue
        asked.append(guide["id"])
        parts.append({"text": (
            f"[{guide['id']}] 표현: {guide.get('phrase', '')}\n"
            f"보여야 할 것: {guide.get('what_to_show', '')}\n"
            f"가이드: {guide.get('guide_text', '')}")})
        for slot in SLOTS:
            parts.append({"text": f"{guide['id']} 후보 {slot}:"})
            parts.append({"inline_data": {
                "mime_type": "image/jpeg",
                "data": base64.b64encode(candidates[slot].read_bytes()).decode(),
            }})
    if not asked:
        raise FileNotFoundError(f"후보 프레임 없음: {frames} (capture를 먼저 실행)")

    response = generate_json(parts, model, key, PICK_SCHEMA)
    picks = {}
    reasons = {}
    for item in response.get("picks", []):
        if item.get("guide_id") in asked and item.get("slot") in (*SLOTS, "none"):
            picks[item["guide_id"]] = item["slot"]
            reasons[item["guide_id"]] = item.get("reason", "")
    for guide_id in asked:  # 모델이 빠뜨린 가이드는 안전하게 링크 폴백
        picks.setdefault(guide_id, "none")

    (frames / "picks.json").write_text(
        json.dumps(picks, ensure_ascii=False, indent=2), encoding="utf-8")
    (frames / "picks-meta.json").write_text(json.dumps({
        "source": "auto", "model": model, "reasons": reasons,
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    return picks


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("video_id")
    ap.add_argument("--profile", default="generic")
    ap.add_argument("--language", default="ko")
    ap.add_argument("--model", default="gemini-flash-lite-latest")
    args = ap.parse_args()

    key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
    if not key:
        sys.exit("GEMINI_API_KEY 환경변수가 없습니다.")
    try:
        picks = auto_pick(args.video_id, args.profile, args.language, args.model, key)
    except FileNotFoundError as error:
        sys.exit(str(error))
    except RateLimitError as error:
        print("Gemini 한도 도달:", str(error)[-300:])
        sys.exit(75)

    picked = sum(1 for slot in picks.values() if slot != "none")
    print(f"AI 선택 완료: 사진 {picked}개, 링크 폴백 {len(picks) - picked}개")
    for guide_id, slot in picks.items():
        print(f"  {guide_id}: {slot}")
    picker = build_picker(args.video_id, args.profile, args.language)
    print(f"검토용 picker (AI 선택 미리표시): {picker}")
    print("다르게 고쳤다면 semantic-evaluation.json을 내려받아 "
          "`python -m clipnote.feedback add <파일>` 로 기록하세요.")


if __name__ == "__main__":
    main()
