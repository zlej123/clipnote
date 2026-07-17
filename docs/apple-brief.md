# clipnote Apple 앱 개발 브리프

Mac에서 iOS/iPadOS/macOS 앱(`clipnote-apple`) 개발을 시작하는 세션을 위한 핸드오버 문서.
이 문서 + 세 레포가 컨텍스트의 전부다.

## 프로젝트 구조 (3-레포)

| 레포 | 역할 | 상태 |
|------|------|------|
| [clipnote](https://github.com/zlej123/clipnote) | Python 코어 + `src/clipnote/skill-core/` 언어중립 자산 | 완료 (테스트 6도메인 54영상 통과) |
| [clipnote-server](https://github.com/zlej123/clipnote-server) | 얇은 REST API (분석 두뇌) | 완료 (라이브 스모크 통과) |
| [clipnote-extension](https://github.com/zlej123/clipnote-extension) | 크롬 확장 (캡처 클라이언트 참고 구현) | 완료 (수동 테스트 가이드 포함) |
| clipnote-apple | SwiftUI 멀티플랫폼 앱 | **이번에 만들 것** |

## 제품 한 줄

**영상을 문서로. 애매한 순간은 실제 화면으로.** 유튜브 how-to 영상 → 단계별 문서. "한입 크기", "자작해질 때까지" 같은 애매 표현마다 그 상태가 보이는 실제 프레임을 첨부.

## 확정된 아키텍처 결정 (변경하려면 근거 필요)

1. **서버는 두뇌만, 캡처는 클라이언트** — 앱이 플레이어 화면에서 프레임을 딴다. 서버는 ffmpeg/yt-dlp 없음, stateless.
2. **BYOK** — 사용자 본인 Gemini 키(AI Studio 무료, 카드 불필요). 앱은 키를 Keychain에 저장, `X-Gemini-Key`로 서버에 패스스루. 우리가 비용 부담하지 않음.
3. **duration은 앱이 보낸다** — 플레이어에서 아는 값. 그러면 서버는 유튜브에 아예 접속하지 않음.
4. **자동 프레임 선택 없음** — before/center/after 3후보를 사용자에게 보여주고 고르게 한다. 전부 부적합이면 타임스탬프 링크 폴백.
5. **App Store 5.2.3 방어** — 영상 다운로드 금지. WKWebView에 youtube.com을 로드하고 재생 화면의 스틸만 캡처. 심사 리젝 대비 **링크 모드**(캡처 없이 타임스탬프 링크만)를 설정으로 상시 제공 — 링크 모드만으로도 제품이 성립한다.

## 앱이 호출할 API (clipnote-server, 검증 완료)

```
POST {server}/v1/analyze
  header X-Gemini-Key: <사용자 키>
  { "url", "profile": "generic|recipe", "language": "ko", "max_guides": 5, "duration": <초> }
  → { "video_id", "analysis": { title, summary, category, materials[],
        steps[{id,summary,detail,t_start,t_end}],
        visual_guides[{id,step_id,source_phrase,phrase,type,what_to_show,
                       best_visual_timestamp,guide_text,importance}] } }
  오류: 401 키없음 / 422 URL·duration / 429 Gemini 한도 / 502 모델·계약 위반

POST {server}/v1/documents
  { "video_id", "analysis", "image_refs": {"vg-1": "<앱이 저장한 이미지 경로/URL>"} }
  → { "markdown", "screenshots", "link_fallbacks" }
```

앱은 마크다운 조립을 로컬 Swift로 해도 된다(확장의 `content.js buildMarkdown` 참고) — 출력 형태의 원본은 `skill-core/profiles/*/template.md`.

## 캡처 구현 참고 (크롬 확장과 동일 로직)

- 후보 시각: `candidate_times` — before = step.t_start-1, center = best_visual_timestamp, after = step.t_end+1 (영상 범위로 클램프). 원본: `clipnote/src/clipnote/capture.py`, JS 포팅: `clipnote-extension/content.js`.
- WKWebView에 `https://m.youtube.com/watch?v=...` 로드 → `evaluateJavaScript`로 video 엘리먼트 seek → canvas `drawImage` + `toDataURL` (유튜브는 MSE blob이라 canvas 오염 없음. 확장에서 동일 기법 사용).
- 캡처 전 음소거+pause, 캡처 후 원위치 복원.

## 앱 화면 최소 구성 (v1)

1. **공유 시트 확장**: 유튜브 앱에서 공유 → clipnote (URL 수신이 주 진입점)
2. 분석 진행 화면 → 가이드별 3후보 선택 화면 (확장의 패널 UX 참고)
3. 결과 문서 뷰 + 내보내기: 공유시트(md), Goodnotes(PDF는 서버 확장 예정 — v1은 md+이미지), Obsidian(파일 저장)
4. 설정: Gemini 키(Keychain), 언어, 서버 URL, **링크 모드 토글**

## 품질 기준 (코어에서 검증된 수치)

- 6개 도메인(요리·공예·DIY·뷰티·운동·SW) 54영상 구조 검증 100%, 후보 3장 내 의미 적중 94%.
- 실패 패턴: 화면에 실제로 안 보이는 것을 가이드로 잡는 경우(예: 화면에 없는 OS UI) → 링크 폴백이 안전판. 절대 억지 이미지를 넣지 말 것.

## Mac 세션 시작 절차

```bash
git clone https://github.com/zlej123/clipnote        # 이 문서 + skill-core
git clone https://github.com/zlej123/clipnote-server # 로컬 서버 실행용
git clone https://github.com/zlej123/clipnote-extension # 캡처 로직 참고
cd clipnote-server && pip install -r requirements.txt && python app.py  # 127.0.0.1:8787
# Xcode에서 clipnote-apple 신규 생성 (SwiftUI, iOS+iPadOS+macOS 멀티플랫폼 타깃)
```
