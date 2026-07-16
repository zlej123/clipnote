#!/usr/bin/env python3
"""Render normalized analysis and explicit frame picks into a portable document.

Usage:
    py -3.11 render.py VIDEO_ID --profile generic --language ko \
        [--picks path/to/picks.json]

Only explicit picks are embedded. Without picks, every visual guide falls back
to a timestamp link; no sharpness or semantic auto-selection is performed.
"""
import argparse
import json
import re
import shutil
import sys
from pathlib import Path
from common import analysis_file, frames_dir as artifact_frames_dir, output_dir
sys.stdout.reconfigure(encoding="utf-8")

HERE = Path(__file__).parent
def load_template(profile: str) -> str:
    p = HERE / "skill-core" / "profiles" / profile / "template.md"
    if not p.exists():
        sys.exit(f"알 수 없는 프로파일: {profile} ({p} 없음)")
    return p.read_text(encoding="utf-8")

SLOTS = ("before", "center", "after")


def hms(sec: int) -> str:
    return f"{sec // 60}:{sec % 60:02d}"




# ---- 최소 mustache 렌더러 (sections/inverted/vars, 재귀 중첩 지원) -------------
TOKEN = re.compile(r"\{\{([#^/]?)\s*([\w.]+)\s*\}\}")


def _lookup(stack, key):
    for ctx in reversed(stack):
        if isinstance(ctx, dict) and key in ctx:
            return ctx[key]
    return None


def render(tmpl: str, data: dict) -> str:
    # standalone 섹션 태그 라인({{#x}}/{{^x}}/{{/x}}만 있는 줄)의 들여쓰기+줄바꿈 제거
    tmpl = re.sub(r"(?m)^[ \t]*(\{\{[#^/][\w.]+\}\})[ \t]*\r?\n", r"\1", tmpl)
    pos = 0
    out = []
    stack = [data]

    def parse(text, start, stack):
        i = start
        buf = []
        while i < len(text):
            m = TOKEN.search(text, i)
            if not m:
                buf.append(text[i:])
                i = len(text)
                break
            buf.append(text[i:m.start()])
            sigil, key = m.group(1), m.group(2)
            if sigil in ("#", "^"):
                inner, i = capture_block(text, m.end(), key)
                val = _lookup(stack, key)
                truthy = bool(val) and val != [] and val != ""
                if sigil == "#":
                    if isinstance(val, list):
                        for item in val:
                            buf.append(parse(inner, 0, stack + [item])[0])
                    elif isinstance(val, dict):
                        buf.append(parse(inner, 0, stack + [val])[0])
                    elif truthy:
                        buf.append(parse(inner, 0, stack)[0])
                else:  # inverted ^
                    if not truthy:
                        buf.append(parse(inner, 0, stack)[0])
            elif sigil == "/":
                return "".join(buf), i  # unreachable via capture_block
            else:
                val = _lookup(stack, key)
                buf.append("" if val is None else str(val))
                i = m.end()
        return "".join(buf), i

    def capture_block(text, start, key):
        """{{#key}} 다음부터 매칭되는 {{/key}}까지 (중첩 고려) 잘라낸다."""
        depth = 1
        i = start
        while i < len(text):
            m = TOKEN.search(text, i)
            if not m:
                break
            sigil, k = m.group(1), m.group(2)
            if sigil in ("#", "^") and k == key:
                depth += 1
            elif sigil == "/" and k == key:
                depth -= 1
                if depth == 0:
                    return text[start:m.start()], m.end()
            i = m.end()
        raise ValueError(f"닫히지 않은 섹션: {{{{#{key}}}}}")

    result, _ = parse(tmpl, pos, stack)
    return result


# ---- 데이터 조립 --------------------------------------------------------------
def build_context(vid: str, data: dict, picks: dict, source_frames: Path,
                  images_dir: Path, image_refs: dict = None) -> dict:
    """image_refs: 클라이언트가 직접 캡처·호스팅한 이미지 참조(guide_id -> URL/경로).
    디스크 프레임보다 우선한다. 서버/확장처럼 프레임이 로컬에 없는 호출자용."""
    image_refs = image_refs or {}
    duration = data.get("_duration")
    by_step = {}
    for guide in data.get("visual_guides", []):
        by_step.setdefault(guide.get("step_id"), []).append(guide)

    steps_ctx = []
    for step in data.get("steps", []):
        guide_contexts = []
        for guide in by_step.get(step.get("id"), []):
            timestamp = guide.get("best_visual_timestamp")
            guide_ctx = {
                "id": guide.get("id", ""),
                "phrase": guide.get("phrase", ""),
                "source_phrase": guide.get("source_phrase", ""),
                "guide_text": guide.get("guide_text", ""),
                "importance": guide.get("importance", 0),
                "has_screenshot": False,
                "screenshot": "",
                "timestamp_hms": hms(timestamp) if timestamp is not None else "",
                "timestamp_link": (
                    f"https://youtu.be/{vid}?t={timestamp}"
                    if timestamp is not None else f"https://youtu.be/{vid}"),
            }
            if guide.get("id") in image_refs:
                guide_ctx["has_screenshot"] = True
                guide_ctx["screenshot"] = image_refs[guide["id"]]
            elif timestamp is not None and (duration is None or timestamp < duration):
                chosen = choose_frame(guide["id"], picks, source_frames)
                if chosen is not None:
                    dst = images_dir / f"{guide['id']}_{guide.get('type', 'x')}.jpg"
                    shutil.copyfile(chosen, dst)
                    guide_ctx["has_screenshot"] = True
                    guide_ctx["screenshot"] = f"images/{dst.name}"
            guide_contexts.append(guide_ctx)

        steps_ctx.append({
            "id": step["id"],
            "summary": step.get("summary", ""),
            "detail": step.get("detail", ""),
            "visual_guides": guide_contexts,
        })

    materials = data.get("materials") or data.get("ingredients") or []
    summary = data.get("summary") or data.get("video_summary") or ""
    return {
        "title": data.get("title", ""),
        "summary": summary,
        "video_summary": summary,
        "category": data.get("category", ""),
        "servings": data.get("servings", ""),
        "materials": materials,
        "ingredients": materials,
        "steps": steps_ctx,
        "video_title": data.get("title", ""),
        "video_url": f"https://youtu.be/{vid}",
    }


def choose_frame(guide_id: str, picks: dict, source_frames: Path):
    """Return only an explicitly selected candidate; otherwise link fallback."""
    selected = picks.get(guide_id)
    if selected in (None, "none"):
        return None
    if selected not in SLOTS:
        raise ValueError(
            f"{guide_id}의 잘못된 선택값: {selected!r} (허용: {SLOTS} 또는 'none')")
    candidate = source_frames / f"{guide_id}_{selected}.jpg"
    return candidate if candidate.exists() else None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("video_id")
    ap.add_argument("--profile", default="generic")
    ap.add_argument("--language", default="ko")
    ap.add_argument("--picks", help="picker.html에서 내려받은 picks.json")
    args = ap.parse_args()

    vid = args.video_id
    source = analysis_file(HERE, vid, args.profile, args.language)
    if not source.exists():
        sys.exit(f"분석 결과 없음: {source}")
    data = json.loads(source.read_text(encoding="utf-8"))

    picks = {}
    if args.picks:
        picks_path = Path(args.picks)
        if not picks_path.exists():
            sys.exit(f"선택 파일 없음: {picks_path}")
        picks = json.loads(picks_path.read_text(encoding="utf-8"))

    source_frames = artifact_frames_dir(
        HERE, vid, args.profile, args.language)
    out_dir = output_dir(HERE, vid, args.profile, args.language)
    images_dir = out_dir / "images"
    images_dir.mkdir(parents=True, exist_ok=True)
    for stale in images_dir.glob("*.jpg"):
        stale.unlink()

    profile = data["_profile"]
    template = load_template(profile)
    # 템플릿 프론트매터(주석 + '---') 제거: 첫 '---' 줄 이후만 렌더
    body = template
    if "\n---\n" in template:
        body = template.split("\n---\n", 1)[1]

    ctx = build_context(vid, data, picks, source_frames, images_dir)
    md = render(body, ctx).strip() + "\n"

    out_md = out_dir / "document.md"
    out_md.write_text(md, encoding="utf-8")

    guides = [guide for step in ctx["steps"]
              for guide in step["visual_guides"]]
    shots = sum(1 for guide in guides if guide["has_screenshot"])
    links = len(guides) - shots
    print(f"완료: {out_md}")
    print(f"  명시적으로 선택된 스크린샷: {shots}개, 링크 폴백: {links}개")
    print(f"  이미지 폴더: {images_dir}")


if __name__ == "__main__":
    main()
