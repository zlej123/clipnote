# 렌더 템플릿 (범용 how-to, mustache 부분집합, 플랫폼 중립)
#
# - 기본(영어) 템플릿. 언어별 파일이 있으면 template.<language>.md가 우선한다 (예: template.ko.md)
# - 선택된 사진이 없으면 타임스탬프 링크로 폴백
# - 앱/확장/AI 도구가 명시적으로 선택한 사진만 문서에 포함
---

## 📋 {{title}}
{{#high_risk}}

> ⚠️ **Safety-critical topic.** Treat this document as reference only — do not follow it without expert guidance.
{{/high_risk}}

{{summary}}

{{#category}}**Category:** {{category}}{{/category}}

**■ What you need**
{{#materials}}
- {{name}} {{amount}}
{{/materials}}

**■ Steps**
{{#steps}}
{{id}}. **{{summary}}**
   - {{detail}}
{{#visual_guides}}
   - 💡 *What '{{phrase}}' looks like:* {{guide_text}}
{{#has_screenshot}}
   ![{{phrase}}]({{screenshot}})
{{/has_screenshot}}
{{^has_screenshot}}
   ▶ [See it in the video at {{timestamp_hms}}]({{timestamp_link}})
{{/has_screenshot}}
{{/visual_guides}}
{{/steps}}

---
*From [{{video_title}}]({{video_url}}) — kept with stepkeeper*
