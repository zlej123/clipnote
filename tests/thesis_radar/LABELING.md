# Gold-label procedure

1. Watch the complete public video without reading a model output.
2. Record every decision-relevant claim using the ontology.
3. Copy the shortest source quote that preserves the claim and speaker intent.
4. Record start and end timestamps around the quote.
5. Record the actual speaker, including `quoted_third_party` attribution.
6. Mark explicit recommendations separately; never infer a recommendation.
7. Add entities only when named or unambiguously shown in the source.
8. Have a second reviewer resolve disagreements before marking the file `gold`.

For each model run, map every gold claim to at most one extracted `claim_id`.
Unmapped gold claims are false negatives. Extracted claims not mapped to a gold
claim are false positives. Recommendation attribution errors are critical
failures regardless of aggregate precision.

The initial corpus must contain 5–10 videos stratified across Korean and
English, 10–20 and 30–60 minute lengths, direct recommendations, rumors,
third-party quotations, chart-heavy presentations, and talking-head videos.

