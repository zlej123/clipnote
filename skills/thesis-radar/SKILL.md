---
name: thesis-radar
description: Extract attributable, timestamped investment claims from a public YouTube market, company, or stock-analysis video and prepare a ClaimPacket for human review or Project 2035. Use when the user supplies an investment-video URL and wants claims, recommendations, rumors, forecasts, source quotes, verification questions, or a machine-readable review packet. Do not use for ordinary how-to videos; use the clipnote skill for those.
---

# Thesis Radar

Extract what a source actually claimed. Do not decide whether the claim is true
and do not turn the extraction into investment advice.

## Preconditions

- Work from the Clipnote repository and install it with `pip install -e .`.
- Require `GEMINI_API_KEY` or `GOOGLE_API_KEY`.
- Accept public YouTube URLs only.
- Default to videos of at most 60 minutes. A longer run requires an explicit
  `--max-duration` override through the underlying analyzer.
- Treat the profile as CLI/server-only. Do not modify or invoke the Apple app,
  browser extension, frame capture, or note-app export paths.

## Run

Use:

```bash
thesis-radar <YOUTUBE_URL> --language ko --max-claims 20
```

Use `--force` only when a cached extraction should be replaced. The command
analyzes and renders without frame capture.

Expected artifacts:

- `work/analyses/<video-id>/investment_claims.<language>.json`
- `output/<video-id>/investment_claims.<language>/document.md`
- `output/<video-id>/investment_claims.<language>/claim-packet.json`

## Review Contract

Before presenting or forwarding results:

1. Require every claim to have a nonempty speaker, verbatim source quote, and
   start/end timestamps.
2. Preserve `asserted`, `speculated`, and `quoted_third_party` attribution.
3. Never add external counterevidence, source grades, or truth judgments.
4. Keep extracted claims free of `verification_status`. The generated
   ClaimPacket owns an initial `unverified` review queue.
5. Treat verification and falsification entries as questions, not answers.
6. State that the output is unverified source intelligence, not a buy/sell
   decision.
7. Do not place orders or send the packet to an execution engine.

The final verification priority is deterministic:
`decision_impact × verification_feasibility`. The model supplies the two
bounded inputs; Clipnote computes the queue score and band.

## Quality Gate

Do not claim extraction quality is validated until the human-labeled corpus
passes:

```bash
python tests/thesis_radar/validate_corpus.py
python tests/thesis_radar/evaluate.py <prediction.json> <gold.json> <review.json>
```

The gold corpus must contain 5–10 independently labeled videos. Recommendation
attribution errors are critical failures even when aggregate scores look good.

## Project 2035 Boundary

Pass only `claim-packet.json` across the boundary. Do not share databases.
Project 2035 may verify claims against primary sources and update its own review
state, but Thesis Radar has no portfolio or trading authority.
