#!/usr/bin/env python3
"""Validate fixture shape, uniqueness, availability, and real duration strata."""
import argparse
import json
import re
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
HERE = Path(__file__).parent
FIXTURES = HERE / "fixtures" / "urls.json"
VIDEO_ID = re.compile(r"(?:v=|youtu\.be/|shorts/)([\w-]{11})")


def expected_length(duration: int) -> str:
    if duration < 180:
        return "short"
    if duration <= 900:
        return "medium"
    return "long"


def metadata(entry):
    domain, video = entry
    result = subprocess.run([
        sys.executable, "-m", "yt_dlp", "--skip-download", "--no-warnings",
        "--print", "%(id)s\t%(duration)s\t%(title)s", video["url"],
    ], capture_output=True, text=True, timeout=90)
    if result.returncode != 0:
        return domain, video, None, result.stderr[-300:].strip()
    line = result.stdout.strip().splitlines()[-1]
    parts = line.split("\t", 2)
    if len(parts) != 3 or not parts[1].isdigit():
        return domain, video, None, f"metadata parse: {line}"
    return domain, video, {
        "id": parts[0], "duration": int(parts[1]), "title": parts[2]
    }, None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--online", action="store_true")
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--max-duration", type=int, default=1800,
                    help="테스트 영상 최대 길이(초)")
    args = ap.parse_args()

    data = json.loads(FIXTURES.read_text(encoding="utf-8"))
    dimensions = data.get("_dimensions", {})
    errors, warnings, entries = [], [], []
    seen = {}

    for domain, config in data.items():
        if domain.startswith("_"):
            continue
        videos = config.get("videos", [])
        if not 8 <= len(videos) <= 12:
            errors.append(f"{domain}: 영상 {len(videos)}개 (계약: 8~12개)")
        for index, video in enumerate(videos):
            tag = f"{domain}[{index}]"
            match = VIDEO_ID.search(video.get("url", ""))
            if not match:
                errors.append(f"{tag}: 유효한 YouTube ID 없음")
                continue
            vid = match.group(1)
            if vid in seen:
                errors.append(f"{tag}: 중복 ID {vid} (기존 {seen[vid]})")
            seen[vid] = tag
            strata = video.get("strata", {})
            for dimension, allowed in dimensions.items():
                value = strata.get(dimension)
                if value not in allowed:
                    errors.append(f"{tag}: {dimension}={value!r}, 허용={allowed}")
            entries.append((domain, video))

    rows = []
    if args.online:
        with ThreadPoolExecutor(max_workers=max(1, args.workers)) as pool:
            futures = [pool.submit(metadata, entry) for entry in entries]
            for future in as_completed(futures):
                domain, video, meta, error = future.result()
                vid = VIDEO_ID.search(video["url"]).group(1)
                if error:
                    errors.append(f"{domain}/{vid}: 접근 실패: {error}")
                    rows.append((domain, vid, "실패", "-", video.get("note", "")))
                    continue
                actual = expected_length(meta["duration"])
                declared = video["strata"]["length"]
                if actual != declared:
                    warnings.append(
                        f"{domain}/{vid}: length {declared}→{actual} ({meta['duration']}s)")
                if meta["duration"] > args.max_duration:
                    errors.append(
                        f"{domain}/{vid}: 테스트 최대 길이 초과 "
                        f"({meta['duration']}>{args.max_duration}s)")
                rows.append((domain, vid, "통과", f"{meta['duration']}s/{actual}", meta["title"]))

    report_lines = [
        "# Fixture 검증 리포트", "",
        f"- 오류: {len(errors)}", f"- 경고: {len(warnings)}", "",
    ]
    if rows:
        report_lines += [
            "| domain | video | 접근 | 실제 길이 | 제목 |",
            "|--------|-------|------|-----------|------|",
        ]
        report_lines += [f"| {d} | {v} | {ok} | {length} | {title[:60]} |"
                         for d, v, ok, length, title in sorted(rows)]
        report_lines.append("")
    if errors:
        report_lines += ["## 오류", ""] + [f"- {item}" for item in errors] + [""]
    if warnings:
        report_lines += ["## 경고", ""] + [f"- {item}" for item in warnings] + [""]
    report = HERE / "fixture-validation.md"
    report.write_text("\n".join(report_lines), encoding="utf-8")
    print(f"fixtures={len(entries)} errors={len(errors)} warnings={len(warnings)}")
    print(report)
    if errors:
        sys.exit(1)


if __name__ == "__main__":
    main()
