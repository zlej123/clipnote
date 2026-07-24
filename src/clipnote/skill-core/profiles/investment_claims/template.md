# 렌더 템플릿 (투자 주장, mustache 부분집합, 플랫폼 중립)
---

## {{title}}

{{summary}}

> 이 문서는 원문의 주장을 구조화한 것이며 사실 검증이나 투자 조언이 아닙니다.

{{#claims}}
### {{id}} · {{claim_type}}

**주장:** {{statement}}

- 화자: {{speaker}} · 표현 방식: {{epistemic_mode}}
- 관련 대상: {{entities_text}}
- 판단 영향: {{decision_impact}}/3 · 검증 용이성: {{verification_feasibility}}/3
{{#time_horizon}}- 예상 기간: {{time_horizon}}{{/time_horizon}}
- 원문: “{{quote}}”
- ▶ [영상 {{timestamp_hms}}에서 확인]({{timestamp_link}})

**확인 질문**
{{#verification_questions}}
- {{text}}
{{/verification_questions}}

**반증 질문**
{{#falsification_questions}}
- {{text}}
{{/falsification_questions}}

{{/claims}}
---
*출처: [{{video_title}}]({{video_url}}) — Clipnote Thesis Radar로 생성*
