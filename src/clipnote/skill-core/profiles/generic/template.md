# 렌더 템플릿 (범용 how-to, mustache 부분집합, 플랫폼 중립)
#
# - 선택된 사진이 없으면 타임스탬프 링크로 폴백
# - 앱/확장/AI 도구가 명시적으로 선택한 사진만 문서에 포함
---

## 📋 {{title}}

{{summary}}

{{#category}}**분류:** {{category}}{{/category}}

**■ 준비물**
{{#materials}}
- {{name}} {{amount}}
{{/materials}}

**■ 순서**
{{#steps}}
{{id}}. **{{summary}}**
   - {{detail}}
{{#visual_guides}}
   - 💡 *'{{phrase}}' 기준:* {{guide_text}}
{{#has_screenshot}}
   ![{{phrase}}]({{screenshot}})
{{/has_screenshot}}
{{^has_screenshot}}
   ▶ [영상 {{timestamp_hms}}에서 직접 확인]({{timestamp_link}})
{{/has_screenshot}}
{{/visual_guides}}
{{/steps}}

---
*출처: [{{video_title}}]({{video_url}}) — clipnote로 생성*
