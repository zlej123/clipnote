# 렌더 템플릿(일본어) (범용 how-to, mustache 부분집합, 플랫폼 중립)
#
# - 선택된 사진이 없으면 타임스탬프 링크로 폴백
# - 앱/확장/AI 도구가 명시적으로 선택한 사진만 문서에 포함
---

## 📋 {{title}}

{{summary}}

{{#category}}**カテゴリ:** {{category}}{{/category}}

**■ 用意するもの**
{{#materials}}
- {{name}} {{amount}}
{{/materials}}

**■ 手順**
{{#steps}}
{{id}}. **{{summary}}**
   - {{detail}}
{{#visual_guides}}
   - 💡 *「{{phrase}}」とは:* {{guide_text}}
{{#has_screenshot}}
   ![{{phrase}}]({{screenshot}})
{{/has_screenshot}}
{{^has_screenshot}}
   ▶ [動画の {{timestamp_hms}} で確認]({{timestamp_link}})
{{/has_screenshot}}
{{/visual_guides}}
{{/steps}}

---
*出典: [{{video_title}}]({{video_url}}) — stepkeeper で作成*
