#!/usr/bin/env python3
"""Extract three candidate frames for each independent visual guide.

Usage:
    python -m stepkeeper.capture VIDEO_ID --profile generic --language ko

picker.html lets a person choose one candidate per guide (or mark all
unsuitable) and download picks.json / semantic-evaluation.json.
When picks.json already exists (e.g. written by stepkeeper.autopick), the picker
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


def playable(path: Path) -> bool:
    """프레임이 **실제로 디코드되는지** 확인 (다운로드·캐시 검증 공용).

    스트림 메타만 보면 안 된다: 실측된 깨진 파일은 헤더가 멀쩡해서 ffprobe가
    "h264, 122초"를 정상 보고했지만 (48KB뿐이라) 프레임 데이터가 없었다.
    한 장 디코드가 유일하게 확실한 판정이다.
    """
    result = subprocess.run(
        ["ffmpeg", "-v", "error", "-i", str(path), "-frames:v", "1", "-f", "null", "-"],
        capture_output=True, text=True)
    return result.returncode == 0 and not result.stderr.strip()


def ensure_video(vid: str) -> Path:
    """480p 영상을 받아 두고 재사용한다. **받은 파일이 재생 가능한지 확인한다.**

    yt-dlp는 포맷을 못 가져와도 exit 0으로 끝나며 쓸 수 없는 조각 파일을 남길 수 있다
    (실측: 48KB 파일 → ffmpeg "Invalid data found"). 그 파일이 캐시로 남으면 이후 실행이
    영원히 같은 에러로 죽는다 — 검증에 실패하면 지우고 원인을 알려주며 멈춘다.
    """
    mp4 = data_root() / "work" / f"{vid}.mp4"
    if mp4.exists() and not playable(mp4):
        print("[1/3] 캐시된 영상이 손상됨 — 지우고 다시 받습니다")
        mp4.unlink()
    if not mp4.exists():
        print("[1/3] 480p 영상 다운로드...")
        sh(sys.executable, "-m", "yt_dlp", "-f",
           "bv*[height<=480]+ba/b[height<=480]/b",
           "--merge-output-format", "mp4", "-o", str(mp4),
           f"https://www.youtube.com/watch?v={vid}")
        if not mp4.exists() or not playable(mp4):
            size = mp4.stat().st_size if mp4.exists() else 0
            mp4.unlink(missing_ok=True)
            sys.exit(
                f"영상을 받지 못했습니다 ({vid}, {size}바이트로 중단). yt-dlp가 포맷을 "
                "가져오지 못했을 수 있습니다 — 최신 yt-dlp로 올리거나, YouTube 추출에 "
                "필요한 JS 런타임(deno 등)을 설치한 뒤 다시 시도하세요.\n"
                "  pip install -U yt-dlp   /   brew install deno")
    else:
        print("[1/3] 영상 캐시 사용")
    return mp4


# 후보 간격 상한(초). 동작은 같은 동작 안에 머물도록 더 촘촘히 본다.
ACTION_CANDIDATE_SPREAD = 1
DEFAULT_CANDIDATE_SPREAD = 2


def candidate_times(step: dict, guide: dict, duration: int):
    """center 주변에서 세 후보를 뽑는다 (스텝 경계가 아니라).

    예전에는 before/after를 스텝 경계(t_start-1, t_end+1)에 뒀는데, 긴 스텝에서는 그 둘이
    **다른 주제**를 찍는다. 실측 사례: 19초짜리 스텝의 가이드에서 후보가 18·31·39초로 잡혔고,
    18초는 이전 섹션, 39초는 다음 섹션이었다. 정작 가이드가 요구한 동작은 26~29초에 있었는데
    세 장 중 어디에도 없어서, 사람이 골라도 실패할 선택지가 됐다.

    동작 가이드는 center±1초, 상태·위치·각도 등은 최대 ±2초로 제한한다. 실측 리뷰에서
    ±4초 후보가 결과·준비·다음 동작으로 갈라져 같은 가이드의 비교가 아니게 된 문제를 막는다.
    """
    center = guide["best_visual_timestamp"]
    last = max(0, duration - 1)
    limit = (ACTION_CANDIDATE_SPREAD if guide.get("type") == "action"
             else DEFAULT_CANDIDATE_SPREAD)
    if step:
        length = max(0, step.get("t_end", center) - step.get("t_start", center))
        spread = max(1, min(limit, length // 4))
    else:
        spread = limit
    before = max(0, center - spread)
    after = min(last, center + spread)
    return dict(zip(SLOTS, (before, center, after)))


def sync_candidate_meta(out: Path, times: dict) -> bool:
    """candidates.json에 후보별 타임스탬프를 기록하고, 달라졌으면 선택을 무효화한다.

    창 규칙이나 분석이 바뀌면 같은 "vg-1_center.jpg" 파일명이 전혀 다른 장면을
    가리키게 된다 — 원인이 무엇이든 결국 타임스탬프 변화로 나타나므로, 이 파일
    하나와 비교해 어긋나면 picks.json/picks-meta.json을 지운다.
    반환값: 기존 선택을 무효화했으면 True.
    """
    meta = out / "candidates.json"
    previous = json.loads(meta.read_text(encoding="utf-8")) if meta.exists() else None
    meta.write_text(json.dumps(times, ensure_ascii=False, indent=2), encoding="utf-8")
    # 기록이 없으면(candidates.json 도입 전 데이터) 선택이 지금 후보와 맞는지 검증할
    # 방법이 없다 — 맞다고 가정하지 않고 무효화한다 (fail-closed).
    if previous == times:
        return False
    invalidated = False
    for stale in (out / "picks.json", out / "picks-meta.json"):
        if stale.exists():
            stale.unlink()
            invalidated = True
    return invalidated


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
    # re-capture does not wipe AI or human selections (picker re-reads them) —
    # unless the candidate timestamps changed, in which case the same "center"
    # filename would point at a different scene and old picks become lies.
    for stale in list(out.glob("vg-*.jpg")) + [out / "contact-sheet.jpg"]:
        if stale.exists():
            stale.unlink()

    steps = {step["id"]: step for step in data.get("steps", [])}
    guides = [guide for guide in data.get("visual_guides", [])
              if guide.get("best_visual_timestamp") is not None]
    times = {guide["id"]: candidate_times(
                 steps.get(guide["step_id"], {}), guide, data.get("_duration", 0))
             for guide in guides}
    if sync_candidate_meta(out, times):
        print("후보 타임스탬프가 달라져 기존 선택(picks)을 무효화했습니다 — 다시 선택하세요.")

    print(f"[2/3] 시각 가이드 {len(guides)}개 x {len(SLOTS)}장 프레임 추출...")
    for guide in guides:
        for slot, timestamp in times[guide["id"]].items():
            sh("ffmpeg", "-y", "-loglevel", "error", "-ss", str(timestamp),
               "-i", str(mp4), "-frames:v", "1", "-q:v", "3",
               "-strict", "unofficial", str(out / f"{guide['id']}_{slot}.jpg"))

    print("[3/3] picker.html 생성...")
    picker = build_picker(vid, args.profile, args.language)
    print(f"완료: {picker}")
    print("자동 선택 없음: picker.html에서 선택하거나 stepkeeper.autopick을 실행하세요.")


if __name__ == "__main__":
    main()
