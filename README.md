# clipnote

**영상을 문서로. 애매한 순간은 실제 화면으로.**

clipnote는 유튜브 how-to 영상을 따라 하기 쉬운 문서로 바꿉니다. "한입 크기로", "국물이 자작해질 때까지", "여기에 끼우고" 처럼 **말로만 들으면 기준을 알 수 없는 순간**을, 그 상태가 실제로 보이는 영상 프레임과 함께 문서로 만들어 줍니다. 요리·DIY·수리·공예·뷰티·운동·소프트웨어 튜토리얼 등 도메인을 가리지 않으며, 결과물은 Notion·Obsidian·Goodnotes로 내보낼 수 있습니다.

Google Gemini가 영상을 직접(화면+음성) 분석하므로, 자막이 없거나 말과 행동의 시점이 어긋나는 영상에서도 "그 장면"의 타임스탬프를 찾아냅니다.

## 동작 원리

```
URL ─▶ analyze ─▶ 분석 JSON ─▶ capture ─▶ 후보 프레임 3장 ─▶ [사람/에이전트 선택] ─▶ render ─▶ document.md ─▶ export
        (Gemini)   (계약 검증)    (ffmpeg)    before/center/after                     (+ images)      Notion/Obsidian/Goodnotes
```

- **steps**: 절차만 담습니다.
- **visual_guides[]**: 애매한 순간이 최상위 독립 배열로 분리되어 각각 `step_id`로 단계에 연결됩니다. 타입은 `size/thickness/color/state/amount/position/angle/action/texture`.
- 자동 선택은 없습니다. 흐린 프레임 제거가 아니라 **의미 판단은 사람 또는 에이전트가** `before/center/after` 후보 중에서 고릅니다. 적절한 장면이 없으면 타임스탬프 링크로 폴백합니다.

## 설치

```bash
pip install -r requirements.txt   # yt-dlp, reportlab, opencv-python-headless
# 시스템 의존성: ffmpeg (PATH에 있어야 함)
export GEMINI_API_KEY=...          # Google AI Studio 키
```

## 사용법

한 명령으로 전체 파이프라인을 실행합니다.

```bash
# 1) 완전 자동 (ffmpeg 불필요, 스크린샷 대신 타임스탬프 링크)
python pipeline.py "https://www.youtube.com/watch?v=..." --profile generic --language ko --links-only

# 2) 스크린샷 포함 + 내보내기
python pipeline.py "https://www.youtube.com/watch?v=..." --profile recipe --language ko
#   → 출력된 picker.html에서 가이드별 후보 1장을 고르고 picks.json 저장
python pipeline.py "https://www.youtube.com/watch?v=..." --profile recipe --language ko \
    --picks work/frames/<id>/recipe.ko/picks.json --export goodnotes
```

주요 옵션: `--profile generic|recipe`, `--language ko|en|ja|...`, `--max-guides N`, `--model`, `--export bundle|obsidian|goodnotes`.

## 노트 앱 연동

| 대상 | 방식 | 상태 |
|------|------|------|
| Obsidian | Markdown + 첨부 이미지를 vault 폴더로 복사 | 구현 완료 |
| Goodnotes | 한글 폰트 PDF 생성 → 문서 가져오기/공유로 사용 | 구현 완료 |
| Notion | `bundle/`(document.md + manifest.json + images) 생성 → File Upload API가 소비 | 업로드 준비 완료 |

```bash
python export.py <id> --profile recipe --language ko --target obsidian --destination /path/to/vault
python export.py <id> --profile recipe --language ko --target goodnotes
```

## 다른 곳에서 모듈로 재사용하기

재사용 경계는 두 층입니다.

1. **`skill-core/` (언어 중립 자산)** — `profiles/<name>/{prompt.md, schema.json, template.md}` 와 `engine/rules.md`. 어떤 언어·플랫폼이든 그대로 가져다 씁니다. Swift로 iOS 앱을 만들 때도 이 프롬프트/스키마를 공유 자산으로 사용합니다.
2. **Python 패키지 (analyze/capture/render/export/pipeline)** — **파이썬이 실행되는 곳**에서 재사용합니다.

| 사용처 | 방법 |
|--------|------|
| REST API 서버 (Python) | `from pipeline import main` 또는 각 모듈 import / `pip install .` 후 `clipnote` CLI 호출 |
| 데스크톱 앱 (Python) | 동일 |
| 다른 파이썬 툴·에이전트 스킬 | 동일 (`SKILL.md` 참고) |
| **iOS 네이티브 앱** | 파이썬을 직접 import할 수 없음. 위 REST API를 호출하거나, `skill-core/` 자산을 가져가 Swift로 얇게 재구현 |

즉 서버/데스크톱은 이 저장소를 **그대로 모듈로 가져다 쓸 수 있고**, 아이폰은 이 코드를 감싼 API를 호출하거나 `skill-core/`만 공유합니다.

## 프로파일 추가

`skill-core/profiles/<name>/` 에 `prompt.md`(끝에 `{{RULES}}` 포함), `schema.json`, `template.md` 세 파일을 넣으면 새 도메인이 됩니다. 파이프라인 코드는 수정하지 않습니다.

## 테스트

```bash
python -m unittest discover -s tests        # 단위: 계약/정규화/선택/내보내기
python tests/validate_fixtures.py --online  # 픽스처 URL 접근성 + 층화 검증
python tests/batch.py                        # 6개 도메인 구조 + 의미 회귀
```

`tests/fixtures/urls.json` 은 6개 도메인 × 8~12개 영상을 길이/음성/자막/편집/프레이밍/언어 조건으로 층화한 회귀 코퍼스입니다. `tests/evaluations/` 는 후보 프레임 의미 적중 여부의 라벨입니다.

## 한계

- 공개 영상만 지원. 비용·시간상 30분 이하 권장.
- Gemini 무료 티어는 대량 배치에서 rate limit에 걸립니다. 기본 모델은 `gemini-flash-lite-latest`.
- 타임스탬프 정확도는 ±2~3초이며 before/center/after 후보로 보정합니다.
- 강연·리뷰·브이로그처럼 "보여줄 행동/상태"가 없는 영상에는 적합하지 않습니다.

## 라이선스

MIT
