#!/usr/bin/env python3
"""Export rendered documents for note applications.

- Portable bundle: document.md + manifest.json + images.
- Obsidian: Markdown and images copied directly into a vault folder.
- Goodnotes: PDF generated for the platform's document import/share flow.
- Notion: direct upload via the Notion API (user's own integration token).
"""
import argparse
import json
import mimetypes
import os
import re
import shutil
import sys
import urllib.request
import uuid
from datetime import datetime, timezone
from pathlib import Path

from .common import analysis_file, data_root, output_dir, variant_key

sys.stdout.reconfigure(encoding="utf-8")


# 문서 산출물(Notion·PDF)의 절 제목·라벨. render.py의 template[.<lang>].md와 같은 규칙 —
# 번역본이 없는 언어는 영어로 떨어진다(한국어로 새지 않는다).
DOC_STRINGS = {
    "en": {
        "source_link": "Watch on YouTube",
        "materials": "What you need",
        "ingredients": "Ingredients",
        "no_materials": "Nothing to prepare",
        "steps": "Steps",
        "guide_prefix": "What '{phrase}' looks like:",
        "guide_label": "Visual guide: {phrase}",
        "see_at": "▶ See it in the video at {time}",
    },
    "ko": {
        "source_link": "YouTube 원본",
        "materials": "준비물",
        "ingredients": "준비 재료",
        "no_materials": "별도 준비물 없음",
        "steps": "순서",
        "guide_prefix": "'{phrase}' 기준:",
        "guide_label": "시각 가이드: {phrase}",
        "see_at": "▶ 영상 {time}에서 직접 확인",
    },
    "ja": {
        "source_link": "YouTube で見る",
        "materials": "用意するもの",
        "ingredients": "材料",
        "no_materials": "特に用意するものはありません",
        "steps": "手順",
        "guide_prefix": "「{phrase}」とは:",
        "guide_label": "ビジュアルガイド: {phrase}",
        "see_at": "▶ 動画の {time} で確認",
    },
}


def doc_strings(language: str = "") -> dict:
    """출력 언어에 맞는 문서 라벨. 미지원 언어는 영어."""
    return DOC_STRINGS.get(language or "", DOC_STRINGS["en"])


def safe_name(value: str) -> str:
    name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "-", value).strip(" .-")
    return name[:80] or "document"


def load_source(video_id: str, profile: str, language: str):
    analysis_path = analysis_file(data_root(), video_id, profile, language)
    rendered = output_dir(data_root(), video_id, profile, language)
    document = rendered / "document.md"
    if not analysis_path.exists():
        sys.exit(f"분석 결과 없음: {analysis_path}")
    if not document.exists():
        sys.exit(f"렌더 결과 없음: {document} (render.py를 먼저 실행)")
    return json.loads(analysis_path.read_text(encoding="utf-8")), rendered, document


def copy_images(source_dir: Path, destination: Path):
    destination.mkdir(parents=True, exist_ok=True)
    copied = []
    for image in sorted((source_dir / "images").glob("*")):
        if image.is_file():
            target = destination / image.name
            shutil.copyfile(image, target)
            copied.append(target)
    return copied


def manifest(data: dict, video_id: str, profile: str, language: str,
             document_name: str, images):
    return {
        "version": 1,
        "video_id": video_id,
        "profile": profile,
        "output_language": language,
        "title": data.get("title", ""),
        "category": data.get("category", ""),
        "source_url": f"https://youtu.be/{video_id}",
        "document": document_name,
        "attachments": [
            {"path": str(path).replace("\\", "/"), "media_type": "image/jpeg"}
            for path in images
        ],
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }


def export_bundle(data, rendered: Path, document: Path, destination: Path,
                  video_id: str, profile: str, language: str):
    destination.mkdir(parents=True, exist_ok=True)
    target_document = destination / "document.md"
    shutil.copyfile(document, target_document)
    images = copy_images(rendered, destination / "images")
    relative_images = [Path("images") / image.name for image in images]
    info = manifest(data, video_id, profile, language,
                    target_document.name, relative_images)
    (destination / "manifest.json").write_text(
        json.dumps(info, ensure_ascii=False, indent=2), encoding="utf-8")
    return target_document


def export_obsidian(data, rendered: Path, document: Path, vault: Path,
                    video_id: str, profile: str, language: str):
    vault.mkdir(parents=True, exist_ok=True)
    slug = safe_name(data.get("title", "document"))
    attachment_rel = Path("attachments") / slug
    copied = copy_images(rendered, vault / attachment_rel)
    text = document.read_text(encoding="utf-8")
    text = text.replace("(images/", f"({str(attachment_rel).replace(chr(92), '/')}/")
    target = vault / f"{slug}.md"
    target.write_text(text, encoding="utf-8")
    info = manifest(
        data, video_id, profile, language, target.name,
        [attachment_rel / image.name for image in copied])
    (vault / f"{slug}.manifest.json").write_text(
        json.dumps(info, ensure_ascii=False, indent=2), encoding="utf-8")
    return target


def find_pdf_font(explicit: str = None):
    """등록을 시도할 CJK 폰트 후보들 (존재하는 것만, 우선순위 순).

    단일 반환이 아니라 목록인 이유: 후보가 존재해도 등록이 실패할 수 있다.
    실측 — macOS 기본 AppleSDGothicNeo.ttc는 reportlab이 posts 테이블을 못 읽어
    항상 실패하고, 예전 코드는 그대로 Helvetica로 떨어져 한글 PDF가 깨졌다
    (외부 리뷰에서 재현됨). Supplemental의 ttf들이 실제로 등록되는 후보다.
    """
    candidates = [
        explicit,
        "C:/Windows/Fonts/malgun.ttf",
        "/System/Library/Fonts/Supplemental/AppleGothic.ttf",
        "/System/Library/Fonts/Supplemental/NotoSansGothic-Regular.ttf",
        "/System/Library/Fonts/AppleSDGothicNeo.ttc",
        "/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc",
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
    ]
    return [Path(c) for c in candidates if c and Path(c).exists()]


def _has_cjk(text: str) -> bool:
    return any("\uac00" <= ch <= "\ud7a3" or "\u3040" <= ch <= "\u30ff"
               or "\u4e00" <= ch <= "\u9fff" for ch in text)


def export_goodnotes(data, rendered: Path, destination: Path,
                     video_id: str, font_path: str = None):
    from reportlab.lib import colors
    from reportlab.lib.enums import TA_CENTER
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.lib.units import mm
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont
    from reportlab.platypus import (
        Image, Paragraph, SimpleDocTemplate, Spacer)
    from xml.sax.saxutils import escape

    destination.mkdir(parents=True, exist_ok=True)
    target = destination / f"{safe_name(data.get('title', 'document'))}.pdf"
    font_name = "Helvetica"
    for font in find_pdf_font(font_path):
        try:
            pdfmetrics.registerFont(TTFont("StepkeeperFont", str(font)))
            font_name = "StepkeeperFont"
            break
        except Exception as error:
            print(f"[export] 폰트 등록 실패 ({font.name}): {error}; 다음 후보 시도")
    if font_name == "Helvetica" and _has_cjk(json.dumps(data, ensure_ascii=False)):
        # 조용한 폴백이 깨진 PDF를 "완료"처럼 보이게 했다 — 소리 내서 알린다
        print("[export] ⚠️ CJK 텍스트가 있는데 등록 가능한 CJK 폰트가 없습니다. "
              "이 PDF의 한글·일본어·한자는 깨져 보입니다 — --font <ttf 경로>로 지정하세요.")

    styles = getSampleStyleSheet()
    title_style = ParagraphStyle(
        "StepkeeperTitle", parent=styles["Title"], fontName=font_name,
        fontSize=20, leading=26, alignment=TA_CENTER, spaceAfter=12)
    heading_style = ParagraphStyle(
        "StepkeeperHeading", parent=styles["Heading2"], fontName=font_name,
        fontSize=14, leading=19, textColor=colors.HexColor("#222222"))
    body_style = ParagraphStyle(
        "StepkeeperBody", parent=styles["BodyText"], fontName=font_name,
        fontSize=10.5, leading=16, spaceAfter=7)

    labels = doc_strings(data.get("_output_language", ""))
    is_recipe = data.get("_profile") == "recipe"
    story = [
        Paragraph(escape(data.get("title", "")), title_style),
        Paragraph(escape(data.get("summary", "")), body_style),
        Paragraph(f'<link href="https://youtu.be/{video_id}">{labels["source_link"]}</link>',
                  body_style),
        Spacer(1, 4 * mm),
        Paragraph(labels["ingredients"] if is_recipe else labels["materials"], heading_style),
    ]
    materials = data.get("materials", [])
    if materials:
        for material in materials:
            story.append(Paragraph(
                f"• {escape(material.get('name', ''))} "
                f"{escape(material.get('amount', ''))}", body_style))
    else:
        story.append(Paragraph(labels["no_materials"], body_style))

    guides_by_step = {}
    for guide in data.get("visual_guides", []):
        guides_by_step.setdefault(guide.get("step_id"), []).append(guide)

    story.extend([Spacer(1, 4 * mm), Paragraph(labels["steps"], heading_style)])
    for step in data.get("steps", []):
        story.append(Paragraph(
            f"{step['id']}. {escape(step.get('summary', ''))}", heading_style))
        story.append(Paragraph(escape(step.get("detail", "")), body_style))
        for guide in guides_by_step.get(step.get("id"), []):
            story.append(Paragraph(
                f"{labels['guide_label'].format(phrase=escape(guide.get('phrase', '')))}<br/>"
                f"{escape(guide.get('guide_text', ''))}", body_style))
            matches = list((rendered / "images").glob(f"{guide['id']}_*.jpg"))
            if matches:
                image = Image(str(matches[0]))
                max_width, max_height = 170 * mm, 90 * mm
                scale = min(max_width / image.imageWidth,
                            max_height / image.imageHeight, 1)
                image.drawWidth = image.imageWidth * scale
                image.drawHeight = image.imageHeight * scale
                story.extend([image, Spacer(1, 3 * mm)])
            elif guide.get("best_visual_timestamp") is not None:
                timestamp = guide["best_visual_timestamp"]
                story.append(Paragraph(
                    f'<link href="https://youtu.be/{video_id}?t={timestamp}">'
                    f"영상에서 확인 ({timestamp}초)</link>", body_style))

    pdf = SimpleDocTemplate(
        str(target), pagesize=A4, rightMargin=18 * mm, leftMargin=18 * mm,
        topMargin=16 * mm, bottomMargin=16 * mm)
    pdf.build(story)
    return target


# ---- Notion ------------------------------------------------------------------
NOTION_API = "https://api.notion.com/v1"
NOTION_VERSION = "2022-06-28"


def notion_request(path: str, token: str, payload: dict = None,
                   data: bytes = None, content_type: str = None) -> dict:
    headers = {
        "Authorization": f"Bearer {token}",
        "Notion-Version": NOTION_VERSION,
    }
    if payload is not None:
        data = json.dumps(payload).encode()
        headers["Content-Type"] = "application/json"
    elif content_type:
        headers["Content-Type"] = content_type
    request = urllib.request.Request(
        f"{NOTION_API}{path}", data=data, headers=headers,
        method="POST" if data is not None else "GET")
    try:
        with urllib.request.urlopen(request, timeout=120) as response:
            return json.loads(response.read().decode())
    except urllib.error.HTTPError as error:
        detail = error.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"Notion API {error.code}: {detail[:500]}") from error


def notion_upload_image(image_path: Path, token: str) -> str:
    """Upload a local image; returns the file_upload id."""
    created = notion_request("/file_uploads", token, payload={})
    upload_id = created["id"]
    boundary = uuid.uuid4().hex
    mime = mimetypes.guess_type(image_path.name)[0] or "image/jpeg"
    body = (
        f"--{boundary}\r\n"
        f'Content-Disposition: form-data; name="file"; filename="{image_path.name}"\r\n'
        f"Content-Type: {mime}\r\n\r\n"
    ).encode() + image_path.read_bytes() + f"\r\n--{boundary}--\r\n".encode()
    notion_request(f"/file_uploads/{upload_id}/send", token, data=body,
                   content_type=f"multipart/form-data; boundary={boundary}")
    return upload_id


def _rich(text: str, link: str = None) -> list:
    item = {"type": "text", "text": {"content": text[:2000]}}
    if link:
        item["text"]["link"] = {"url": link}
    return [item]


def build_notion_blocks(data: dict, video_id: str, image_ids: dict) -> list:
    """Analysis JSON -> Notion block list. image_ids: guide_id -> file_upload id.

    절 제목·라벨은 data["_output_language"]를 따른다 (문서 뼈대와 같은 규칙).
    """
    labels = doc_strings(data.get("_output_language", ""))
    blocks = []
    if data.get("summary"):
        blocks.append({"type": "paragraph",
                       "paragraph": {"rich_text": _rich(data["summary"])}})
    blocks.append({"type": "paragraph", "paragraph": {"rich_text": _rich(
        labels["source_link"], f"https://youtu.be/{video_id}")}})

    materials = data.get("materials") or []
    if materials:
        blocks.append({"type": "heading_2",
                       "heading_2": {"rich_text": _rich(
                           labels["ingredients"] if data.get("_profile") == "recipe"
                           else labels["materials"])}})
        for material in materials:
            blocks.append({"type": "bulleted_list_item", "bulleted_list_item": {
                "rich_text": _rich(f"{material.get('name', '')} {material.get('amount', '')}")}})

    guides_by_step = {}
    for guide in data.get("visual_guides", []):
        guides_by_step.setdefault(guide.get("step_id"), []).append(guide)

    blocks.append({"type": "heading_2",
                   "heading_2": {"rich_text": _rich(labels["steps"])}})
    for step in data.get("steps", []):
        blocks.append({"type": "numbered_list_item", "numbered_list_item": {
            "rich_text": _rich(f"{step.get('summary', '')} — {step.get('detail', '')}")}})
        for guide in guides_by_step.get(step.get("id"), []):
            blocks.append({"type": "quote", "quote": {"rich_text": _rich(
                "💡 " + labels["guide_prefix"].format(phrase=guide.get("phrase", ""))
                + f" {guide.get('guide_text', '')}")}})
            timestamp = guide.get("best_visual_timestamp")
            if guide.get("id") in image_ids:
                blocks.append({"type": "image", "image": {
                    "type": "file_upload",
                    "file_upload": {"id": image_ids[guide["id"]]}}})
            elif timestamp is not None:
                blocks.append({"type": "paragraph", "paragraph": {"rich_text": _rich(
                    labels["see_at"].format(
                        time=f"{timestamp // 60}:{timestamp % 60:02d}"),
                    f"https://youtu.be/{video_id}?t={timestamp}")}})
    return blocks


def export_notion(data: dict, rendered: Path, video_id: str,
                  parent_page_id: str, token: str) -> str:
    """이미지를 올리기 **전에** 페이지를 만든다.

    순서가 중요하다. 예전에는 업로드를 먼저 하고 마지막에 페이지를 만들었는데, 가장 흔한
    실패(부모 페이지 미연결·잘못된 ID·토큰 만료)가 바로 그 마지막 단계에서 터진다. 그러면
    올라간 이미지가 전부 어디에도 붙지 않은 채 남는다 — Notion API에는 업로드를 지우는
    엔드포인트가 없어서 만료될 때까지 되돌릴 방법이 없다.

    페이지를 먼저 만들면 그 실패는 업로드 0건으로 끝나고, 이후 단계가 실패해도 사용자에게
    보이는 페이지가 남아 직접 지우거나 다시 시도할 수 있다.
    """
    page = notion_request("/pages", token, payload={
        "parent": {"page_id": parent_page_id},
        "properties": {"title": {"title": _rich(data.get("title", "stepkeeper"))}},
    })

    image_ids = {}
    for image in sorted((rendered / "images").glob("vg-*.jpg")):
        guide_id = image.name.split("_")[0]
        image_ids[guide_id] = notion_upload_image(image, token)

    blocks = build_notion_blocks(data, video_id, image_ids)
    for start in range(0, len(blocks), 100):
        notion_request(f"/blocks/{page['id']}/children", token,
                       payload={"children": blocks[start:start + 100]})
    return page.get("url", page["id"])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("video_id")
    ap.add_argument("--profile", default="generic")
    ap.add_argument("--language", default="ko")
    ap.add_argument("--target", choices=("bundle", "obsidian", "goodnotes", "notion"),
                    default="bundle")
    ap.add_argument("--destination")
    ap.add_argument("--font", help="Goodnotes PDF용 TTF/TTC 폰트 경로")
    ap.add_argument("--parent", help="Notion 부모 페이지 ID (--target notion)")
    ap.add_argument("--notion-token", help="Notion integration token (기본: NOTION_TOKEN 환경변수)")
    args = ap.parse_args()

    data, rendered, document = load_source(
        args.video_id, args.profile, args.language)
    if args.destination:
        destination = Path(args.destination)
    elif args.target in ("bundle", "goodnotes"):
        destination = (data_root() / "exports" / args.video_id /
                       variant_key(args.profile, args.language) / args.target)
    elif args.target == "obsidian":
        ap.error("--target obsidian에는 --destination <vault-folder>가 필요합니다.")
    else:
        destination = None  # notion은 로컬 대상 없음

    if args.target == "bundle":
        result = export_bundle(data, rendered, document, destination,
                               args.video_id, args.profile, args.language)
    elif args.target == "obsidian":
        result = export_obsidian(data, rendered, document, destination,
                                 args.video_id, args.profile, args.language)
    elif args.target == "goodnotes":
        result = export_goodnotes(
            data, rendered, destination, args.video_id, args.font)
    else:
        token = args.notion_token or os.environ.get("NOTION_TOKEN")
        if not token:
            ap.error("--target notion에는 NOTION_TOKEN(또는 --notion-token)이 필요합니다.")
        if not args.parent:
            ap.error("--target notion에는 --parent <페이지 ID>가 필요합니다.")
        result = export_notion(data, rendered, args.video_id, args.parent, token)
    print(f"내보내기 완료: {result}")


if __name__ == "__main__":
    main()
