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
    candidates = [
        explicit,
        "C:/Windows/Fonts/malgun.ttf",
        "/System/Library/Fonts/AppleSDGothicNeo.ttc",
        "/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc",
    ]
    for candidate in candidates:
        if candidate and Path(candidate).exists():
            return Path(candidate)
    return None


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
    font = find_pdf_font(font_path)
    font_name = "Helvetica"
    if font:
        font_name = "ClipnoteFont"
        pdfmetrics.registerFont(TTFont(font_name, str(font)))

    styles = getSampleStyleSheet()
    title_style = ParagraphStyle(
        "ClipnoteTitle", parent=styles["Title"], fontName=font_name,
        fontSize=20, leading=26, alignment=TA_CENTER, spaceAfter=12)
    heading_style = ParagraphStyle(
        "ClipnoteHeading", parent=styles["Heading2"], fontName=font_name,
        fontSize=14, leading=19, textColor=colors.HexColor("#222222"))
    body_style = ParagraphStyle(
        "ClipnoteBody", parent=styles["BodyText"], fontName=font_name,
        fontSize=10.5, leading=16, spaceAfter=7)

    story = [
        Paragraph(escape(data.get("title", "")), title_style),
        Paragraph(escape(data.get("summary", "")), body_style),
        Paragraph(f'<link href="https://youtu.be/{video_id}">YouTube 원본</link>',
                  body_style),
        Spacer(1, 4 * mm),
        Paragraph("준비물", heading_style),
    ]
    materials = data.get("materials", [])
    if materials:
        for material in materials:
            story.append(Paragraph(
                f"• {escape(material.get('name', ''))} "
                f"{escape(material.get('amount', ''))}", body_style))
    else:
        story.append(Paragraph("별도 준비물 없음", body_style))

    guides_by_step = {}
    for guide in data.get("visual_guides", []):
        guides_by_step.setdefault(guide.get("step_id"), []).append(guide)

    story.extend([Spacer(1, 4 * mm), Paragraph("순서", heading_style)])
    for step in data.get("steps", []):
        story.append(Paragraph(
            f"{step['id']}. {escape(step.get('summary', ''))}", heading_style))
        story.append(Paragraph(escape(step.get("detail", "")), body_style))
        for guide in guides_by_step.get(step.get("id"), []):
            story.append(Paragraph(
                f"시각 가이드: {escape(guide.get('phrase', ''))}<br/>"
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
    """Analysis JSON -> Notion block list. image_ids: guide_id -> file_upload id."""
    blocks = []
    if data.get("summary"):
        blocks.append({"type": "paragraph",
                       "paragraph": {"rich_text": _rich(data["summary"])}})
    blocks.append({"type": "paragraph", "paragraph": {"rich_text": _rich(
        "YouTube 원본", f"https://youtu.be/{video_id}")}})

    materials = data.get("materials") or []
    if materials:
        blocks.append({"type": "heading_2",
                       "heading_2": {"rich_text": _rich("준비물")}})
        for material in materials:
            blocks.append({"type": "bulleted_list_item", "bulleted_list_item": {
                "rich_text": _rich(f"{material.get('name', '')} {material.get('amount', '')}")}})

    guides_by_step = {}
    for guide in data.get("visual_guides", []):
        guides_by_step.setdefault(guide.get("step_id"), []).append(guide)

    blocks.append({"type": "heading_2", "heading_2": {"rich_text": _rich("순서")}})
    for step in data.get("steps", []):
        blocks.append({"type": "numbered_list_item", "numbered_list_item": {
            "rich_text": _rich(f"{step.get('summary', '')} — {step.get('detail', '')}")}})
        for guide in guides_by_step.get(step.get("id"), []):
            blocks.append({"type": "quote", "quote": {"rich_text": _rich(
                f"💡 '{guide.get('phrase', '')}' 기준: {guide.get('guide_text', '')}")}})
            timestamp = guide.get("best_visual_timestamp")
            if guide.get("id") in image_ids:
                blocks.append({"type": "image", "image": {
                    "type": "file_upload",
                    "file_upload": {"id": image_ids[guide["id"]]}}})
            elif timestamp is not None:
                blocks.append({"type": "paragraph", "paragraph": {"rich_text": _rich(
                    f"▶ 영상 {timestamp // 60}:{timestamp % 60:02d}에서 직접 확인",
                    f"https://youtu.be/{video_id}?t={timestamp}")}})
    return blocks


def export_notion(data: dict, rendered: Path, video_id: str,
                  parent_page_id: str, token: str) -> str:
    image_ids = {}
    for image in sorted((rendered / "images").glob("vg-*.jpg")):
        guide_id = image.name.split("_")[0]
        image_ids[guide_id] = notion_upload_image(image, token)

    blocks = build_notion_blocks(data, video_id, image_ids)
    page = notion_request("/pages", token, payload={
        "parent": {"page_id": parent_page_id},
        "properties": {"title": {"title": _rich(data.get("title", "clipnote"))}},
        "children": blocks[:100],
    })
    for start in range(100, len(blocks), 100):
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
