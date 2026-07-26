#!/usr/bin/env python3
"""stepkeeper 데모 GIF 생성 — 실제 산출물(docs/demo/*.jpg, README 문안)만 사용한 슬라이드 조립.

각 슬라이드를 헤드리스 크롬으로 캡처한 뒤 ffmpeg(팔레트 2-pass)로 GIF를 만든다.
"""
import base64
import pathlib
import subprocess
import sys

HERE = pathlib.Path(__file__).resolve().parent      # <repo>/docs/demo
OUT = HERE / "gif-frames"                           # 중간 프레임 (gitignore 대상)
CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
W, H = 900, 560

CORE = HERE.parent.parent


def data_uri(path):
    return "data:image/jpeg;base64," + base64.b64encode(path.read_bytes()).decode()


# 실제 파이프라인 산출 프레임 (stepkeeper <url> --auto-pick 로 생성된 것을 그대로 복사)
CRUST_IMG = data_uri(CORE / "docs/demo/steak-crust.jpg")        # kbpIYAnt-7k vg-2 (color)
DONENESS_IMG = data_uri(CORE / "docs/demo/steak-doneness.jpg")  # kbpIYAnt-7k vg-3 (state)
SANDING_IMG = data_uri(CORE / "docs/demo/sanding-grain.jpg")    # BUzQM5F0yJ4 vg-2 (action)

CSS = """
* { margin: 0; padding: 0; box-sizing: border-box; }
body {
  width: 900px; height: 560px; display: flex; align-items: center; justify-content: center;
  font-family: -apple-system, 'SF Pro Text', 'Helvetica Neue', sans-serif;
  background: #14110f; color: #f4efe9;
}
.slide { width: 800px; }
.kicker { font-size: 15px; letter-spacing: .14em; text-transform: uppercase; color: #d98b4a; margin-bottom: 18px; }
h1 { font-size: 44px; line-height: 1.2; font-weight: 700; }
h1 .dim { color: #8a8078; font-weight: 500; }
.sub { margin-top: 20px; font-size: 20px; color: #a89f96; line-height: 1.5; }
.quote { font-size: 34px; font-weight: 600; line-height: 1.35; }
.quote em { color: #d98b4a; font-style: normal; }
.ask { margin-top: 22px; font-size: 22px; color: #8a8078; }
.row { display: flex; gap: 26px; align-items: center; }
.frame { width: 440px; border-radius: 10px; display: block; box-shadow: 0 12px 30px rgba(0,0,0,.5); }
.answer { flex: 1; }
.answer .label { font-size: 17px; color: #d98b4a; margin-bottom: 10px; }
.answer .text { font-size: 26px; font-weight: 600; line-height: 1.35; }
.doc { background: #1d1a17; border: 1px solid #2f2a25; border-radius: 12px; padding: 26px 30px; font-size: 18px; line-height: 1.6; }
.doc .h { font-size: 22px; font-weight: 700; margin-bottom: 12px; }
.doc .li { color: #c8bfb5; }
.doc .guide { color: #e8b381; margin-top: 8px; }
.doc img { width: 300px; border-radius: 8px; margin-top: 14px; display: block; }
.exports { margin-top: 22px; display: flex; gap: 10px; }
.chip { border: 1px solid #3a342e; border-radius: 999px; padding: 8px 18px; font-size: 16px; color: #a89f96; }
"""

SLIDES = [
    # (본문 HTML, 이 슬라이드가 화면에 머무는 프레임 수 — 1프레임 = 0.5초)
    ("""<div class="slide">
      <div class="kicker">stepkeeper</div>
      <h1>The video gets deleted.<br><span class="dim">The steps stay yours.</span></h1>
      <div class="sub">A how-to video goes in. A document you keep comes out —<br>with the real frames at the moments words can't carry.</div>
    </div>""", 5),
    ("""<div class="slide">
      <div class="kicker">the problem</div>
      <div class="quote">"Sear it until you get a<br><em>golden brown crust</em>."</div>
      <div class="ask">Brown… how brown, exactly?</div>
    </div>""", 4),
    (f"""<div class="slide">
      <div class="kicker">stepkeeper's answer</div>
      <div class="row">
        <img class="frame" src="{CRUST_IMG}">
        <div class="answer">
          <div class="label">💡 "Golden brown crust" means</div>
          <div class="text">flip when the crust looks like this</div>
        </div>
      </div>
    </div>""", 5),
    ("""<div class="slide">
      <div class="kicker">the problem</div>
      <div class="quote">"Pull it at <em>medium-rare</em>."</div>
      <div class="ask">Everyone argues about this one.</div>
    </div>""", 4),
    (f"""<div class="slide">
      <div class="kicker">stepkeeper's answer</div>
      <div class="row">
        <img class="frame" src="{DONENESS_IMG}">
        <div class="answer">
          <div class="label">💡 "Medium-rare" means</div>
          <div class="text">120–125°F inside — this much pink</div>
        </div>
      </div>
    </div>""", 5),
    (f"""<div class="slide">
      <div class="kicker">not just recipes</div>
      <div class="row">
        <img class="frame" src="{SANDING_IMG}">
        <div class="answer">
          <div class="label">💡 "Sand it smooth" means</div>
          <div class="text">220-grit by hand, strictly along the grain</div>
        </div>
      </div>
    </div>""", 5),
    (f"""<div class="slide">
      <div class="kicker">what you keep</div>
      <div class="doc">
        <div class="h">5. Rest and slice the steak</div>
        <div class="li">• Remove the steak when it reaches medium-rare, rest 5 minutes, then slice.</div>
        <div class="guide">💡 "Medium-rare" means: 120–125°F inside, juicy and pink.</div>
        <img src="{DONENESS_IMG}">
      </div>
      <div class="exports"><div class="chip">Markdown</div><div class="chip">Notion</div><div class="chip">Obsidian</div><div class="chip">Goodnotes</div></div>
    </div>""", 7),
]


def main():
    OUT.mkdir(exist_ok=True)
    for old in OUT.glob("*.png"):
        old.unlink()

    index = 0
    for body, hold in SLIDES:
        html = f"<!doctype html><meta charset='utf-8'><style>{CSS}</style>{body}"
        page = OUT / "slide.html"
        page.write_text(html, encoding="utf-8")
        shot = OUT / f"src-{index:02d}.png"
        subprocess.run([
            CHROME, "--headless", "--disable-gpu", "--force-device-scale-factor=1",
            f"--window-size={W},{H}", f"--screenshot={shot}", f"file://{page}",
        ], check=True, capture_output=True)
        if not shot.exists():
            sys.exit(f"캡처 실패: {shot}")
        # 머무는 시간만큼 같은 프레임을 복제 (일정 프레임레이트 GIF)
        for _ in range(hold):
            (OUT / f"frame-{index:03d}.png").write_bytes(shot.read_bytes())
            index += 1

    palette = OUT / "palette.png"
    gif = HERE / "demo.gif"
    subprocess.run(["ffmpeg", "-y", "-framerate", "2", "-i", str(OUT / "frame-%03d.png"),
                    "-vf", "scale=800:-1:flags=lanczos,palettegen=max_colors=128",
                    str(palette)], check=True, capture_output=True)
    subprocess.run(["ffmpeg", "-y", "-framerate", "2", "-i", str(OUT / "frame-%03d.png"),
                    "-i", str(palette), "-lavfi",
                    "scale=800:-1:flags=lanczos[x];[x][1:v]paletteuse=dither=bayer:bayer_scale=3",
                    "-loop", "0", str(gif)], check=True, capture_output=True)
    print(f"{gif} ({gif.stat().st_size // 1024} KB, {index} frames)")


if __name__ == "__main__":
    main()
