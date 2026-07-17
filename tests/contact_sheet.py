#!/usr/bin/env python3
"""Build a labeled contact sheet for semantic review of three frame candidates."""
import argparse
import json
import sys
from pathlib import Path

import cv2
import numpy as np

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT / "src"))
from clipnote.common import analysis_file, frames_dir  # noqa: E402

SLOTS = ("before", "center", "after")
WIDTH, HEIGHT = 320, 180


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("video_id")
    ap.add_argument("--profile", default="generic")
    ap.add_argument("--language", default="ko")
    args = ap.parse_args()

    source = analysis_file(ROOT, args.video_id, args.profile, args.language)
    data = json.loads(source.read_text(encoding="utf-8"))
    source_frames = frames_dir(ROOT, args.video_id, args.profile, args.language)
    rows = []
    for guide in data.get("visual_guides", []):
        if guide.get("best_visual_timestamp") is None:
            continue
        cells = []
        for slot in SLOTS:
            image = cv2.imread(str(source_frames / f"{guide['id']}_{slot}.jpg"))
            if image is None:
                image = np.zeros((HEIGHT, WIDTH, 3), dtype=np.uint8)
            image = cv2.resize(image, (WIDTH, HEIGHT))
            cv2.rectangle(image, (0, 0), (WIDTH, 28), (0, 0, 0), -1)
            cv2.putText(image, f"{guide['id']} {slot}", (8, 20),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.55, (255, 255, 255), 1,
                        cv2.LINE_AA)
            cells.append(image)
        rows.append(np.hstack(cells))
    if not rows:
        sys.exit("후보 프레임 없음")
    sheet = np.vstack(rows)
    destination = source_frames / "contact-sheet.jpg"
    cv2.imwrite(str(destination), sheet)
    print(destination)


if __name__ == "__main__":
    main()
