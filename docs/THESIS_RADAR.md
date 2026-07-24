# Thesis Radar

Thesis Radar is Clipnote's CLI/server-only investment-claim profile. It reuses
video ingestion, Gemini invocation, caching, profile loading, rendering, and
artifact paths without reusing the visual-guide contract.

## Scope and safety boundary

The extractor records what a source said. It does not verify truth, search for
counterevidence, assign a source grade, modify a portfolio, or place an order.
The Apple client and browser extension remain on the `visual_guides` contract
and are intentionally outside the v0.3 scope.

```text
YouTube video
  -> investment_claims prompt/schema
  -> source-anchored claims
  -> profile contract
  -> document.md + claim-packet.json
  -> human review / Project 2035 verification queue
```

`contract.py` and `analyze.normalize()` are dispatchers. Common validation and
representation cleanup live separately from profile-specific behavior:

```text
contracts/common.py
contracts/visual_guides.py
contracts/investment_claims.py

normalizers/common.py
normalizers/visual_guides.py
normalizers/investment_claims.py
```

## Use

```bash
pip install -e .
export GEMINI_API_KEY=...
thesis-radar "https://www.youtube.com/watch?v=..." \
  --language ko \
  --max-claims 20
```

The default investment-video limit is 3,600 seconds. The shared analyzer
and dedicated command support an explicit `--max-duration` override.

## Extraction contract

Each claim contains:

- a minimal independently checkable statement;
- claim type and epistemic mode;
- actual speaker;
- named entities only;
- verbatim source quote and start/end timestamps;
- time horizon when stated;
- decision impact and verification feasibility, each 1–3;
- verification and falsification questions.

The model is forbidden from writing `verification_status`, `review_status`,
`source_grade`, counterarguments, or counterevidence. Unknown truth is not a
model failure; invented truth is.

## ClaimPacket

`claim-packet.json` is the stable Project 2035 boundary. It contains source
metadata, extraction metadata, the untouched extracted claims, and a
system-generated review queue:

```json
{
  "contract_version": 1,
  "source": {
    "type": "youtube",
    "url": "https://youtu.be/...",
    "video_id": "...",
    "title": "...",
    "author": "...",
    "published_at": "2026-07-23"
  },
  "claims": [],
  "review_queue": [
    {
      "claim_id": "claim-1",
      "verification_status": "unverified",
      "priority_score": 6,
      "priority_band": "high"
    }
  ]
}
```

Priority is calculated by code as:

```text
decision_impact × verification_feasibility
1–2 low, 3–4 medium, 6–9 high
```

This is review order, not investment conviction.

The machine-readable contract is versioned in
`src/clipnote/skill-core/profiles/investment_claims/claim-packet.schema.json`.

Gemini rate-limit exhaustion exits with status 75 after bounded retries. Other
metadata, schema, and contract failures stop the pipeline without emitting a
new ClaimPacket.

## Evaluation before prompt tuning

The evaluation corpus is intentionally fail-closed. It is not complete until
5–10 videos have independent human gold labels.

```bash
python tests/thesis_radar/validate_corpus.py
python tests/thesis_radar/evaluate.py \
  prediction.json gold.json review.json
```

The evaluator reports precision, recall, type accuracy, attribution accuracy,
quote fidelity, timestamp error, false positives/negatives, and critical
recommendation-attribution errors. Thresholds are versioned in
`tests/thesis_radar/corpus.json`.

Do not tune the prompt against unlabeled examples and do not describe the
profile as validated while the corpus status is `awaiting_human_labels`.

Review findings, implemented corrections, and remaining risks are tracked in
[THESIS_RADAR_REVIEW.md](THESIS_RADAR_REVIEW.md).
