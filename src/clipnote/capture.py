#!/usr/bin/env python3
"""Extract three candidate frames for each independent visual guide.

Usage:
    python -m clipnote.capture VIDEO_ID --profile generic --language ko

picker.html lets a person choose one candidate per guide (or mark all
unsuitable) and download picks.json / semantic-evaluation.json.
When picks.json already exists (e.g. written by clipnote.autopick), the picker
pre-selects those picks and the evaluation download records agree/disagree
per guide — that file doubles as the auto-pick feedback record.
"""
import argparse
import html
import json
import subprocess
import sys
from pathlib import Path

from .common import analysis_file, data_root, frames_dir, hms

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


def build_picker(vid: str, profile: str, language: str) -> Path:
    """(Re)generate picker.html from analysis + frames on disk.

    If picks.json exists, its choices are pre-selected and marked as AI picks
    so the evaluation download becomes a feedback record.
    """
    source = analysis_file(data_root(), vid, profile, language)
    data = json.loads(source.read_text(encoding="utf-8"))
    out = frames_dir(data_root(), vid, profile, language)

    picks_file = out / "picks.json"
    ai_picks = {}
    if picks_file.exists():
        ai_picks = {key: value for key, value in
                    json.loads(picks_file.read_text(encoding="utf-8")).items()
                    if not key.startswith("_")}

    steps = {step["id"]: step for step in data.get("steps", [])}
    guides = [guide for guide in data.get("visual_guides", [])
              if guide.get("best_visual_timestamp") is not None]

    rows = []
    guide_ids = []
    for guide in guides:
        guide_id = guide["id"]
        guide_ids.append(guide_id)
        step = steps.get(guide["step_id"], {})
        times = candidate_times(step, guide, data.get("_duration", 0))
        preset = ai_picks.get(guide_id)
        cells = "".join(
            f'<label class="cell"><input type="radio" name="{guide_id}" value="{slot}"'
            f'{" checked" if preset == slot else ""}>'
            f'<img src="{guide_id}_{slot}.jpg"><span>{hms(times[slot])} ({slot})'
            f'{" · AI 선택" if preset == slot else ""}</span></label>'
            for slot in SLOTS)
        cells += (
            f'<label class="cell none"><input type="radio" name="{guide_id}" value="none"'
            f'{" checked" if preset == "none" else ""}>'
            f'<span class="none-box">세 장 모두 부적합<br>링크만 사용'
            f'{"<br>· AI 선택" if preset == "none" else ""}</span></label>')
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
        "profile": profile,
        "language": language,
        "guide_ids": guide_ids,
        "ai_picks": ai_picks,
    }, ensure_ascii=False)
    intro = ("AI가 고른 장면이 미리 선택되어 있습니다. 틀린 것만 바꾼 뒤 "
             "피드백(semantic-evaluation.json)을 내려받아 주세요."
             if ai_picks else
             "각 가이드에서 의미를 가장 잘 보여주는 장면 하나를 선택하세요. 자동 선택은 없습니다.")
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
<p>{intro}</p>
{"".join(rows)}
<div><button onclick="downloadPicks()">picks.json 내려받기</button>
<button onclick="downloadEvaluation()">semantic-evaluation.json 내려받기 (피드백)</button></div>
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
  const guides=META.guide_ids.map(id=>{{
    const slot=selected[id]||null;
    const ai=META.ai_picks[id]||null;
    return {{guide_id:id,
      selected_slot:slot&&slot!=='none'?slot:null,
      candidate_hit:Boolean(slot&&slot!=='none'),
      reviewed:Boolean(slot),
      ai_slot:ai,
      agree:ai?ai===slot:null}};
  }});
  download('semantic-evaluation.json',{{video_id:META.video_id,profile:META.profile,
    language:META.language,ai_reviewed:Object.keys(META.ai_picks).length>0,guides}});
}}
</script>"""
    picker = out / "picker.html"
    picker.write_text(page, encoding="utf-8")
    return picker


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
    # Refresh candidate JPEGs only. Keep picks.json / picks-meta.json so a
    # re-capture does not wipe AI or human selections (picker re-reads them).
    for stale in list(out.glob("vg-*.jpg")) + [out / "contact-sheet.jpg"]:
        if stale.exists():
            stale.unlink()

    steps = {step["id"]: step for step in data.get("steps", [])}
    guides = [guide for guide in data.get("visual_guides", [])
              if guide.get("best_visual_timestamp") is not None]

    print(f"[2/3] 시각 가이드 {len(guides)}개 x {len(SLOTS)}장 프레임 추출...")
    for guide in guides:
        step = steps.get(guide["step_id"], {})
        for slot, timestamp in candidate_times(
                step, guide, data.get("_duration", 0)).items():
            sh("ffmpeg", "-y", "-loglevel", "error", "-ss", str(timestamp),
               "-i", str(mp4), "-frames:v", "1", "-q:v", "3",
               "-strict", "unofficial", str(out / f"{guide['id']}_{slot}.jpg"))

    print("[3/3] picker.html 생성...")
    picker = build_picker(vid, args.profile, args.language)
    print(f"완료: {picker}")
    print("자동 선택 없음: picker.html에서 선택하거나 clipnote.autopick을 실행하세요.")


if __name__ == "__main__":
    main()
