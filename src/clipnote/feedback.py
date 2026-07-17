#!/usr/bin/env python3
"""Feedback log for AI frame picks.

Usage:
    python -m clipnote.feedback add path/to/semantic-evaluation.json
    python -m clipnote.feedback summary

Records land in <data-root>/feedback/feedback.jsonl. Each record compares the
AI pick with the human's final choice, so accuracy is measurable over time and
disagreements become prompt-tuning material.
"""
import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

from .common import data_root

sys.stdout.reconfigure(encoding="utf-8")


def log_file() -> Path:
    return data_root() / "feedback" / "feedback.jsonl"


def add(evaluation_path: Path) -> int:
    evaluation = json.loads(evaluation_path.read_text(encoding="utf-8"))
    records = []
    for guide in evaluation.get("guides", []):
        if guide.get("ai_slot") is None or not guide.get("reviewed"):
            continue
        human = guide.get("selected_slot") or "none"
        records.append({
            "ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "video_id": evaluation.get("video_id"),
            "profile": evaluation.get("profile"),
            "language": evaluation.get("language"),
            "guide_id": guide.get("guide_id"),
            "ai_slot": guide["ai_slot"],
            "human_slot": human,
            "agree": guide["ai_slot"] == human,
        })
    if not records:
        return 0
    target = log_file()
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("a", encoding="utf-8") as handle:
        for record in records:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")
    return len(records)


def summary() -> dict:
    target = log_file()
    if not target.exists():
        return {"total": 0}
    records = [json.loads(line) for line in
               target.read_text(encoding="utf-8").splitlines() if line.strip()]
    agreed = sum(1 for record in records if record["agree"])
    disagreements = {}
    for record in records:
        if not record["agree"]:
            key = f"{record['ai_slot']}→{record['human_slot']}"
            disagreements[key] = disagreements.get(key, 0) + 1
    return {"total": len(records), "agreed": agreed,
            "accuracy": agreed / len(records) if records else None,
            "disagreements": disagreements}


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="command", required=True)
    add_parser = sub.add_parser("add", help="semantic-evaluation.json을 피드백 로그에 기록")
    add_parser.add_argument("evaluation")
    sub.add_parser("summary", help="누적 적중률 요약")
    args = ap.parse_args()

    if args.command == "add":
        count = add(Path(args.evaluation))
        print(f"기록됨: {count}건 -> {log_file()}")
        if count == 0:
            print("(ai_slot이 없는 평가 파일 — AI 선택 이후의 picker에서 내려받은 파일인지 확인)")
    stats = summary()
    if stats["total"]:
        print(f"누적: {stats['agreed']}/{stats['total']} "
              f"({stats['accuracy']:.0%}) | 불일치 패턴: {stats['disagreements'] or '없음'}")
    else:
        print("누적 피드백 없음")


if __name__ == "__main__":
    main()
