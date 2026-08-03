#!/usr/bin/env python3
"""Feedback log for AI frame picks.

Usage:
    python -m stepkeeper.feedback add path/to/semantic-evaluation.json
    python -m stepkeeper.feedback summary

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


def _from_picker(evaluation: dict) -> list:
    """picker.html이 내려주는 semantic-evaluation.json (guides/selected_slot)."""
    records = []
    for guide in evaluation.get("guides", []):
        if guide.get("ai_slot") is None or not guide.get("reviewed"):
            continue
        human = guide.get("selected_slot") or "none"
        records.append({
            "video_id": evaluation.get("video_id"),
            "profile": evaluation.get("profile"),
            "language": evaluation.get("language"),
            "guide_id": guide.get("guide_id"),
            "ai_slot": guide["ai_slot"],
            "human_slot": human,
            "agree": guide["ai_slot"] == human,
        })
    return records


def _from_evaluation(evaluation: dict) -> list:
    """배치 평가 기록 (records/human_slot — feedback/evaluations/*.json).

    평가 단위 필드(evaluation_id, review_kind)와 candidate_hit을 보존한다 —
    이게 없으면 서로 다른 시점의 배치가 섞여 누적치가 무의미해진다.
    """
    records = []
    for row in evaluation.get("records", []):
        record = {
            "video_id": row.get("video_id"),
            "profile": row.get("profile"),
            "language": row.get("language"),
            "guide_id": row.get("guide_id"),
            "ai_slot": row.get("ai_slot"),
            "human_slot": row.get("human_slot") or "none",
            "agree": row.get("ai_slot") == (row.get("human_slot") or "none"),
            "evaluation_id": evaluation.get("evaluation_id"),
        }
        if evaluation.get("review_kind"):
            record["review_kind"] = evaluation["review_kind"]
        if "candidate_hit" in row:
            record["candidate_hit"] = row["candidate_hit"]
        records.append(record)
    return records


def _key(record: dict):
    return (record.get("evaluation_id"), record.get("video_id"),
            record.get("profile"), record.get("language"), record.get("guide_id"))


def add(evaluation_path: Path) -> int:
    evaluation = json.loads(evaluation_path.read_text(encoding="utf-8"))
    records = (_from_evaluation(evaluation) if "records" in evaluation
               else _from_picker(evaluation))
    if not records:
        return 0
    target = log_file()
    target.parent.mkdir(parents=True, exist_ok=True)
    # 같은 평가를 두 번 add해도 중복되지 않는다 (evaluation_id 있는 기록만 —
    # picker 기록은 id가 없어 회차 구분이 불가능하므로 그대로 append).
    existing = set()
    if target.exists():
        for line in target.read_text(encoding="utf-8").splitlines():
            if line.strip():
                existing.add(_key(json.loads(line)))
    stamp = datetime.now(timezone.utc).isoformat(timespec="seconds")
    written = 0
    with target.open("a", encoding="utf-8") as handle:
        for record in records:
            if record.get("evaluation_id") and _key(record) in existing:
                continue
            handle.write(json.dumps({"ts": stamp, **record}, ensure_ascii=False) + "\n")
            written += 1
    return written


def _tally(records: list) -> dict:
    agreed = sum(1 for record in records if record["agree"])
    disagreements = {}
    for record in records:
        if not record["agree"]:
            key = f"{record['ai_slot']}→{record['human_slot']}"
            disagreements[key] = disagreements.get(key, 0) + 1
    stats = {"total": len(records), "agreed": agreed,
             "accuracy": agreed / len(records) if records else None,
             "disagreements": disagreements}
    hits = [record for record in records if "candidate_hit" in record]
    if hits:
        stats["candidate_coverage"] = (
            sum(1 for record in hits if record["candidate_hit"]) / len(hits))
    return stats


def summary() -> dict:
    """평가 단위(evaluation_id)별 집계 — 전체 합산은 내지 않는다.

    회차마다 후보 규칙·프롬프트가 다르므로 섞은 누적치는 어떤 시점의 성능도
    아니다. evaluation_id가 없는 옛 기록은 "(pre-batch)" 묶음으로 남긴다.
    """
    target = log_file()
    if not target.exists():
        return {"total": 0, "evaluations": {}}
    records = [json.loads(line) for line in
               target.read_text(encoding="utf-8").splitlines() if line.strip()]
    groups = {}
    for record in records:
        groups.setdefault(record.get("evaluation_id") or "(pre-batch)",
                          []).append(record)
    return {"total": len(records),
            "evaluations": {name: _tally(rows) for name, rows in groups.items()}}


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
            print("(기록할 게 없음 — ai_slot 없는 picker 파일이거나 이미 기록된 평가)")
    stats = summary()
    if not stats["total"]:
        print("누적 피드백 없음")
        return
    for name, group in stats["evaluations"].items():
        line = (f"{name}: {group['agreed']}/{group['total']} "
                f"({group['accuracy']:.0%})")
        if "candidate_coverage" in group:
            line += f" | 후보 적중 {group['candidate_coverage']:.0%}"
        line += f" | 불일치: {group['disagreements'] or '없음'}"
        print(line)


if __name__ == "__main__":
    main()
