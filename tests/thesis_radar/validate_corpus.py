#!/usr/bin/env python3
"""Fail closed until a reviewable 5-10 video gold corpus exists."""
import json
import sys
from pathlib import Path

HERE = Path(__file__).parent


def main():
    corpus = json.loads((HERE / "corpus.json").read_text(encoding="utf-8"))
    videos = corpus.get("videos", [])
    minimum = corpus["_required_video_count"]["minimum"]
    maximum = corpus["_required_video_count"]["maximum"]
    errors = []
    if not minimum <= len(videos) <= maximum:
        errors.append(
            f"gold corpus requires {minimum}-{maximum} videos; found {len(videos)}")
    for video in videos:
        for field in ("url", "language", "gold"):
            if not video.get(field):
                errors.append(f"corpus entry missing {field}: {video}")
        gold_path = HERE / video.get("gold", "")
        if video.get("gold") and not gold_path.exists():
            errors.append(f"missing gold file: {gold_path}")
    if errors:
        print("\n".join(f"- {error}" for error in errors))
        sys.exit(1)
    print(f"Thesis Radar gold corpus ready: {len(videos)} videos")


if __name__ == "__main__":
    main()

