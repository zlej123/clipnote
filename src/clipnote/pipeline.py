#!/usr/bin/env python3
"""End-to-end orchestrator: URL -> analysis -> (frames) -> document -> export.

This is the single entry point that any shell (AI-tool skill, Apple Shortcut,
REST API, desktop app) can call.

Two paths:
  1. --links-only: analyze then render with timestamp-link fallback only.
     No ffmpeg, no capture, one shot, fully automatic.
  2. default: analyze then capture candidates. Rendering waits for an explicit
     picks.json (from picker.html). Without picks it renders link-only and
     prints the picker path so a human/agent can choose, then rerun.

Usage:
    py -3.11 pipeline.py URL [--profile generic] [--language ko] [--max-guides 5]
        [--model gemini-flash-lite-latest] [--force]
        [--links-only] [--picks PATH]
        [--export bundle|obsidian|goodnotes|notion] [--destination DIR]
        [--parent PAGE_ID]   # required for --export notion
"""
import argparse
import subprocess
import sys
from pathlib import Path

from .common import analysis_file, data_root, frames_dir, video_id

sys.stdout.reconfigure(encoding="utf-8")


def run(module: str, *args: str) -> None:
    result = subprocess.run([sys.executable, "-m", f"clipnote.{module}", *args])
    if result.returncode != 0:
        sys.exit(f"[pipeline] {module} 실패 (exit {result.returncode})")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("url")
    ap.add_argument("--profile", default="generic")
    ap.add_argument("--language", default="ko")
    ap.add_argument("--max-guides", default="5")
    ap.add_argument("--model", default="gemini-flash-lite-latest")
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--links-only", action="store_true",
                    help="캡처 없이 타임스탬프 링크만으로 렌더 (완전 자동)")
    ap.add_argument("--picks", help="picker.html에서 내려받은 picks.json")
    ap.add_argument("--auto-pick", action="store_true",
                    help="캡처 후 AI가 후보 3장 중 장면을 자동 선택 (사람 검토는 picker에서)")
    ap.add_argument("--export", choices=("bundle", "obsidian", "goodnotes", "notion"))
    ap.add_argument("--destination")
    ap.add_argument("--parent", help="Notion 부모 페이지 ID (--export notion)")
    ap.add_argument("--notion-token",
                    help="Notion integration token (기본: NOTION_TOKEN 환경변수)")
    args = ap.parse_args()

    if args.export == "notion" and not args.parent:
        ap.error("--export notion에는 --parent <페이지 ID>가 필요합니다.")

    try:
        vid = video_id(args.url)
    except ValueError as error:
        sys.exit(str(error))
    common_flags = ["--profile", args.profile, "--language", args.language]

    print("[pipeline] 1) 분석")
    analyze_flags = ["--model", args.model, "--max-guides", str(args.max_guides)]
    if args.force:
        analyze_flags.append("--force")
    run("analyze", args.url, *common_flags, *analyze_flags)

    render_flags = list(common_flags)
    if args.links_only:
        print("[pipeline] 2) 렌더 (링크 전용)")
    else:
        print("[pipeline] 2) 후보 프레임 추출")
        run("capture", vid, *common_flags)
        if args.auto_pick:
            print("[pipeline] 2.5) AI 장면 선택")
            run("autopick", vid, *common_flags, "--model", args.model)
        picks = args.picks
        if not picks:
            default_picks = frames_dir(data_root(), vid, args.profile, args.language) / "picks.json"
            if default_picks.exists():
                picks = str(default_picks)
        if picks:
            render_flags += ["--picks", picks]
        else:
            picker = frames_dir(data_root(), vid, args.profile, args.language) / "picker.html"
            print(f"[pipeline] 선택 파일 없음 -> 링크 전용으로 렌더합니다.")
            print(f"[pipeline] 사진을 넣으려면 {picker} 에서 선택 후 "
                  f"--picks <picks.json>로 다시 실행하세요.")
        print("[pipeline] 3) 렌더")
    run("render", vid, *render_flags)

    if args.export:
        print(f"[pipeline] 4) 내보내기 ({args.export})")
        export_flags = [vid, *common_flags, "--target", args.export]
        if args.destination:
            export_flags += ["--destination", args.destination]
        if args.export == "notion":
            export_flags += ["--parent", args.parent]
            if args.notion_token:
                export_flags += ["--notion-token", args.notion_token]
        run("export", *export_flags)

    print(f"[pipeline] 완료: {analysis_file(data_root(), vid, args.profile, args.language)}")


if __name__ == "__main__":
    main()
