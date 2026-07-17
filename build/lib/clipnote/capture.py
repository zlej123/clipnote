#!/usr/bin/env python3
"""Extract three candidate frames for each independent visual guide.

Usage:
    py -3.11 capture.py VIDEO_ID --profile generic --language ko

The generated picker.html has no automatic selection. A person or agent must
choose one candidate or mark all candidates unsuitable, then download
picks.json and semantic-evaluation.json.
"""
import argparse
import html
import json
import subprocess
import sys
from pathlib import Path

from .common import analysis_file, data_root, frames_dir

sys.stdout.reconfigure(encoding="utf-8")

SLOTS = ("before", "center", "after")


def sh(*args: str) -> None:
    result = subprocess.run(args, capture_output=True, text=True)
    if result.returncode != 0:
        sys.exit(f"실패: {' '.join(args[:3])}...\n{result.stderr[-2000:]}")


def ensure_video(vid: str) -> Path:
    mp4 = data_root() / "work" / f"{vid}.mp4"
    if not mp4.exists():
        print("[1/3] 480p 영상 다운로드...")
        sh(sys.executable, "-m", "yt_dlp", "-f",
           "bv*[height<=480]+ba/b[height<=480]/b",
           "--merge-output-format", "mp4", "-o", str(mp4),
           f"https://www.youtube.com/watch?v={vid}")
    else:
        print("[1/3] 영상 캐시 사용")
    return mp4


def hms(sec: int) -> str:
    return f"{sec // 60}:{sec % 60:02d}"
def candidate_times(step: dict, guide: dict, duration: int):
    """Spread three candidates across the linked step."""
    center = guide["best_visual_timestamp"]
    if step:
        before = max(0, step.get("t_start", center) - 1)
        after = min(max(0, duration - 1), step.get("t_end", center) + 1)
    else:
        before = max(0, center - 4)
        after = min(max(0, duration - 1), center + 4)
    return dict(zip(SLOTS, (before, center, after)))




def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("video_id")
    ap.add_argument("--profile", default="generic")
    ap.add_argument("--language", default="ko")
    args = ap.parse_args()

    vid = args.video_id
    source = analysis_file(data_root(), vid, args.profile, args.language)
    if not source.exists():
        sys.exit(f"분석 결과 없음: {source}")
    data = json.loads(source.read_text(encoding="utf-8"))
    mp4 = ensure_video(vid)

    out = frames_dir(data_root(), vid, args.profile, args.language)
    out.mkdir(parents=True, exist_ok=True)
    for stale in out.glob("vg-*.jpg"):
        stale.unlink()
    contact_sheet = out / "contact-sheet.jpg"
    if contact_sheet.exists():
        contact_sheet.unlink()

    steps = {step["id"]: step for step in data.get("steps", [])}
    guides = [guide for guide in data.get("visual_guides", [])
              if guide.get("best_visual_timestamp") is not None]

    print(f"[2/3] 시각 가이드 {len(guides)}개 x {len(SLOTS)}장 프레임 추출...")
    cards = []
    for guide in guides:
        step = steps.get(guide["step_id"], {})
        images = []
        for slot, timestamp in candidate_times(
                step, guide, data.get("_duration", 0)).items():
            name = f"{guide['id']}_{slot}.jpg"
            sh("ffmpeg", "-y", "-loglevel", "error", "-ss", str(timestamp),
               "-i", str(mp4), "-frames:v", "1", "-q:v", "3",
               "-strict", "unofficial", str(out / name))
            images.append((name, timestamp, slot))
        cards.append((guide, step, images))

    print("[3/3] picker.html 생성...")
    rows = []
    guide_ids = []
    for guide, step, images in cards:
        guide_id = guide["id"]
        guide_ids.append(guide_id)
        cells = "".join(
            f'<label class="cell"><input type="radio" name="{guide_id}" value="{slot}">'
            f'<img src="{name}"><span>{hms(timestamp)} ({slot})</span></label>'
            for name, timestamp, slot in images)
        cells += (
            f'<label class="cell none"><input type="radio" name="{guide_id}" value="none">'
            '<span class="none-box">세 장 모두 부적합<br>링크만 사용</span></label>')
        rows.append(
            f'<section data-guide="{html.escape(guide_id)}">'
            f'<h2>{html.escape(guide_id)} · 단계 {guide["step_id"]}: '
            f'{html.escape(step.get("summary", ""))}</h2>'
            f'<p><b>원문:</b> {html.escape(guide["source_phrase"])} &nbsp; '
            f'<b>표시:</b> {html.escape(guide["phrase"])}</p>'
            f'<p><b>판정 기준:</b> {html.escape(guide["what_to_show"])}<br>'
            f'<b>가이드:</b> {html.escape(guide["guide_text"])}</p>'
            f'<div class="row">{cells}</div></section>')

    metadata = json.dumps({
        "video_id": vid,
        "profile": args.profile,
        "language": args.language,
        "guide_ids": guide_ids,
    }, ensure_ascii=False)
    page = f"""<!doctype html><meta charset="utf-8">
<title>{html.escape(data['title'])} — 장면 선택</title>
<style>
 body{{font-family:-apple-system,'Malgun Gothic',sans-serif;max-width:1200px;margin:24px auto;padding:0 12px}}
 .row{{display:flex;gap:12px;align-items:stretch}} .cell{{flex:1;text-align:center;cursor:pointer}}
 .cell img{{width:100%;border:3px solid #ddd;border-radius:8px;box-sizing:border-box}}
 .cell input{{position:absolute;opacity:0}} .cell input:checked+img{{border-color:#e5484d}}
 .cell span{{font-size:13px;color:#666}} .none-box{{display:flex;height:100%;min-height:150px;border:3px solid #ddd;
 border-radius:8px;align-items:center;justify-content:center;box-sizing:border-box}}
 .none input:checked+.none-box{{border-color:#e5484d;background:#fff1f1}}
 section{{margin-bottom:42px}} button{{padding:12px 18px;margin:8px;font-size:15px}}
</style>
<h1>{html.escape(data['title'])}</h1>
<p>각 가이드에서 의미를 가장 잘 보여주는 장면 하나를 선택하세요. 자동 선택은 없습니다.</p>
{"".join(rows)}
<div><button onclick="downloadPicks()">picks.json 내려받기</button>
<button onclick="downloadEvaluation()">semantic-evaluation.json 내려받기</button></div>
<script>
const META={metadata};
function selections(){{
  const result={{}};
  for(const id of META.guide_ids){{
    const selected=document.querySelector(`input[name="${{id}}"]:checked`);
    if(selected) result[id]=selected.value;
  }}
  return result;
}}
function download(name,data){{
  const blob=new Blob([JSON.stringify(data,null,2)],{{type:'application/json'}});
  const a=document.createElement('a'); a.href=URL.createObjectURL(blob); a.download=name; a.click();
  URL.revokeObjectURL(a.href);
}}
function downloadPicks(){{download('picks.json',selections());}}
function downloadEvaluation(){{
  const selected=selections();
  const guides=META.guide_ids.map(id=>({{guide_id:id,
    selected_slot:selected[id] && selected[id]!=='none' ? selected[id] : null,
    candidate_hit:Boolean(selected[id] && selected[id]!=='none'),
    reviewed:Boolean(selected[id])}}));
  download('semantic-evaluation.json',{{video_id:META.video_id,profile:META.profile,
    language:META.language,guides}});
}}
</script>"""
    picker = out / "picker.html"
    picker.write_text(page, encoding="utf-8")
    print(f"완료: {picker}")
    print("자동 선택 없음: picker.html에서 선택 후 picks.json을 내려받으세요.")


if __name__ == "__main__":
    main()
