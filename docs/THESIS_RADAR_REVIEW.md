# Thesis Radar review resolution

This document records how the first critical design review changed v0.3. It is
not a completion claim.

| Review finding | v0.3 response |
|---|---|
| Evaluation corpus was missing from the MVP | Added ontology, labeling guide, deterministic evaluator, thresholds, and a validator that fails until 5–10 human-labeled videos exist |
| Counterevidence and verification state were unsafe model fields | Model schema forbids them; the model outputs questions only; ClaimPacket creates the initial `unverified` queue in code |
| Attribution needed to be correctness-critical | Speaker, epistemic mode, verbatim quote, and timestamp interval are required; recommendation attribution mismatches are critical evaluation failures |
| Normalization was still visual-guide-specific | Split both contracts and normalizers into common, visual-guide, and investment-claim modules |
| Apple and extension impact was omitted | Thesis Radar is explicitly CLI/server-only; both clients remain on the existing visual contract |
| Importance was ambiguous | Replaced it with bounded `decision_impact` and `verification_feasibility`; code computes review priority |
| Duration and cost needed bounds | Investment profile defaults to 3,600 seconds, has bounded Gemini retries, and uses exit 75 for exhausted rate limits |
| Project 2035 needed a stable boundary | Added a versioned ClaimPacket and JSON Schema; no database or execution authority is shared |

## Open risks and intentionally incomplete work

### No human gold corpus yet

`tests/thesis_radar/corpus.json` contains zero videos and status
`awaiting_human_labels`. Therefore prompt quality is not validated. The corpus
validator must continue to fail until independently reviewed labels exist.

### No online Gemini acceptance run yet

Unit, contract, renderer, package, and CLI tests do not prove that the current
Gemini model accepts the schema or produces good claims. An API key and a
licensed public test set are required for that gate.

### Runtime quote fidelity is not automatically proven

The runtime contract requires a quote and timestamp, but it cannot prove that
the quote is verbatim when a reliable transcript is unavailable. Gold-corpus
evaluation compares extracted quotes to human labels. Until an optional
caption/transcript adapter exists, a reviewer must open the timestamp link
before accepting attribution.

### Web columns are not implemented

The first adapter remains YouTube. Web columns need a separate fetch and
article-body extraction path, provenance rules, and a no-duration contract.
They should reuse the claim ontology and ClaimPacket only after the video
evaluation gate is credible.

### No portfolio or execution integration

Project 2035 ingestion, primary-source verification, approval messaging, and
broker execution are downstream work. Thesis Radar can only generate an
unverified input packet.
